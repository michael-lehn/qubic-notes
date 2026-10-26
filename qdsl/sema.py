"""Semantic analysis: names, constants, types, inlining.  AST -> MIR.

MIR is a small tree of timed ops, classical ops and structured control flow.
Scope inference and barrier insertion happen later (lower.py)."""
from __future__ import annotations

import difflib
import math
from dataclasses import dataclass, field

from . import syntax as A
from .diag import Diagnostics, Pos, QdError
from .target import CHANNELS, DEFAULT_FREQ, Target

UNITS = {'ns': ('time', 1e-9), 'us': ('time', 1e-6), 'ms': ('time', 1e-3), 's': ('time', 1.0),
         'Hz': ('freq', 1.0), 'kHz': ('freq', 1e3), 'MHz': ('freq', 1e6), 'GHz': ('freq', 1e9)}
REGISTER_TYPES = ('int', 'amp', 'phase', 'time')     # time registers hold clock ticks
SHIFT_REG = '__qclk_shift'                           # scratch register for runtime delays
TIER3_DELAY = ('a runtime delay takes a time register:  tau : time = 0 us;  ...  delay(tau);\n'
               'or unroll the sweep at compile time:  #unroll for t in [...] { delay(t); }')
MAX_UNROLL = 4096


# ---------------------------------------------------------------- values

@dataclass(frozen=True)
class CVal:
    type: str            # int amp phase time freq num qubit channel env str
    value: object


class _RuntimeRef(Exception):
    """Raised by const evaluation when it meets a register variable."""
    def __init__(self, name: str, pos: Pos):
        self.name, self.pos = name, pos


@dataclass
class VarInfo:
    name: str
    type: str
    pos: Pos


# ---------------------------------------------------------------- MIR

@dataclass
class MTimed:
    kind: str                      # pulse gate delay barrier
    ir: dict
    qubits: frozenset | None       # None: inherit the enclosing scope (unscoped delay)
    pos: Pos
    uses: set = field(default_factory=set)


@dataclass
class MClassical:
    ir: dict
    defs: set
    uses: set
    pos: Pos


@dataclass
class MIf:
    lhs: object                    # constant value or variable name
    op: str                        # ge le eq  (QubiC alu_cond)
    rhs: str | None                # variable name; None for an FPROC condition
    func_id: str | None            # 'Q0.meas' for measurement conditions
    then: list
    els: list
    pos: Pos
    uses: set = field(default_factory=set)
    measured: str | None = None


@dataclass
class MLoop:                       # post-test loop: body runs, then continues while (lhs op rhs)
    lhs: object
    op: str
    rhs: str
    body: list
    pos: Pos
    uses: set = field(default_factory=set)


@dataclass
class MParallel:                   # independent branches; the end is a join
    branches: list
    pos: Pos


# ---------------------------------------------------------------- analysis

_ALU = {'>': 'ge', '<': 'le', '==': 'eq'}
_FLIP = {'>': '<', '<': '>', '==': '==', '>=': '<=', '<=': '>=', '!=': '!='}
_NEGATE = {'<=': '>', '>=': '<', '!=': '=='}


class Sema:
    def __init__(self, target: Target, diag: Diagnostics):
        self.t = target
        self.diag = diag
        self.qubits: dict[str, Pos] = {}
        self.vars: dict[str, VarInfo] = {}
        self.procs: dict[str, A.ProcDecl] = {}
        self.env: list[dict[str, CVal]] = [{}]
        self.inlining: list[str] = []
        self.loop_depth = 0
        self.taint_src: dict[str, Pos] = {}         # amp vars that may hold a negative/wrapped word
        self.flows: list[tuple[str, str]] = []      # (dst, src) between amp vars
        self.ordering_sites: list[tuple[set, Pos]] = []
        self.delay_sites: list[tuple[str, Pos]] = []      # runtime delays: register must stay >= 0

    # ------------------------------------------------------------ entry
    def run(self, prog: A.Program) -> list:
        mir = self.items(prog.items)
        self._check_amp_ordering()
        return mir

    # ------------------------------------------------------------ names
    def _taken(self, name: str, pos: Pos):
        if name in self.qubits or name in self.vars or name in self.procs or self._lookup(name):
            raise QdError(pos, f"'{name}' is already declared")

    def _lookup(self, name: str) -> CVal | None:
        for scope in reversed(self.env):
            if name in scope:
                return scope[name]
        return None

    def _qubit(self, e, pos: Pos) -> str:
        v = self.const(e)
        if v.type != 'qubit':
            raise QdError(pos, f'expected a qubit, got {v.type}')
        return v.value

    # ------------------------------------------------------------ constants
    def const(self, e) -> CVal:
        if isinstance(e, A.Num):
            return CVal('num', e.value)
        if isinstance(e, A.Quantity):
            kind, scale = UNITS[e.unit]
            return CVal(kind, e.value * scale)
        if isinstance(e, A.Pi):
            return CVal('num', math.pi)
        if isinstance(e, A.Str):
            return CVal('str', e.value)
        if isinstance(e, A.Name):
            v = self._lookup(e.id)
            if v is not None:
                return v
            if e.id in self.qubits:
                return CVal('qubit', e.id)
            if e.id in self.vars:
                raise _RuntimeRef(e.id, e.pos)
            raise QdError(e.pos, f"unknown name '{e.id}'", self._suggest(e.id))
        if isinstance(e, A.Attr):
            q = self._qubit(A.Name(e.base, e.pos), e.pos)
            if e.attr in CHANNELS:
                if not self.t.has_channel(f'{q}.{e.attr}'):
                    raise QdError(e.pos, f"channel '{q}.{e.attr}' is not in the channel configuration",
                                  f'{q} has: ' + ', '.join(self.t.cores.channels_of_qubit(q)))
                return CVal('channel', f'{q}.{e.attr}')
            if e.attr in self.t.qubit_attrs(q):
                return CVal('freq', f'{q}.{e.attr}')       # named, resolved from the calibration
            raise QdError(e.pos, f"'{q}' has no channel or frequency '{e.attr}'",
                          'channels: ' + ', '.join(CHANNELS) + '; frequencies: ' + ', '.join(self.t.qubit_attrs(q)))
        if isinstance(e, A.Neg):
            v = self.const(e.operand)
            if v.type not in ('num', 'int', 'amp', 'phase', 'time', 'freq') or isinstance(v.value, str):
                raise QdError(e.pos, f'cannot negate a {v.type}')
            return CVal(v.type, -v.value)
        if isinstance(e, A.BinOp):
            return self._const_binop(e)
        if isinstance(e, A.Call):
            if e.func in self.t.envelopes:
                return self._envelope(e)
            if e.func == 'measure':
                raise QdError(e.pos, 'measure() is only allowed as a statement, an assignment source, '
                              'or one side of an if-condition')
            raise QdError(e.pos, f"'{e.func}(...)' is not a constant expression")
        raise QdError(getattr(e, 'pos', Pos(0, 0)), 'unsupported expression')

    def _const_binop(self, e: A.BinOp) -> CVal:
        a, b = self.const(e.lhs), self.const(e.rhs)
        num = ('num',)
        for v in (a, b):
            if v.type not in ('num', 'int', 'amp', 'phase', 'time', 'freq') or isinstance(v.value, str):
                raise QdError(e.pos, f"cannot use a {v.type} in arithmetic")
        if e.op in '+-':
            if a.type != b.type and num[0] not in (a.type, b.type):
                raise QdError(e.pos, f'cannot combine {a.type} and {b.type}')
            t = a.type if a.type != 'num' else b.type
            if t in ('time', 'freq') and 'num' in (a.type, b.type):
                raise QdError(e.pos, f'a plain number has no unit; write e.g. 10 {"us" if t == "time" else "MHz"}')
            return CVal(t, a.value + b.value if e.op == '+' else a.value - b.value)
        if e.op == '*':
            if a.type != 'num' and b.type != 'num':
                raise QdError(e.pos, f'cannot multiply {a.type} by {b.type}')
            return CVal(a.type if a.type != 'num' else b.type, a.value * b.value)
        if b.value == 0:
            raise QdError(e.pos, 'division by zero')
        if a.type == b.type and a.type != 'num':
            return CVal('num', a.value / b.value)
        if b.type != 'num':
            raise QdError(e.pos, f'cannot divide {a.type} by {b.type}')
        return CVal(a.type, a.value / b.value)

    def _envelope(self, e: A.Call) -> CVal:
        params = self.t.envelopes[e.func]
        paradict = {}
        for i, arg in enumerate(e.args):
            key = arg.name
            if key is None:
                if i >= len(params):
                    raise QdError(arg.pos, f'{e.func} takes at most {len(params)} parameters')
                key = params[i]
            if key not in params:
                raise QdError(arg.pos, f"{e.func} has no parameter '{key}'", 'parameters: ' + ', '.join(params))
            v = self.const(arg.value)
            paradict[key] = v.value
        return CVal('env', {'env_func': e.func, 'paradict': paradict})

    def coerce(self, v: CVal, t: str, pos: Pos):
        if v.type == t:
            if t == 'amp' and abs(v.value) > 1:
                raise QdError(pos, f'amplitude {v.value} outside [-1, 1]')
            return v.value
        if v.type == 'num':
            if t == 'int':
                if float(v.value) != int(v.value):
                    raise QdError(pos, f'{v.value} is not an integer')
                return int(v.value)
            if t == 'amp':
                if abs(v.value) > 1:
                    raise QdError(pos, f'amplitude {v.value} outside [-1, 1]')
                return float(v.value)
            if t == 'phase':
                return float(v.value)
            if t in ('time', 'freq'):
                raise QdError(pos, f'a plain number has no unit; write e.g. {v.value} {"us" if t == "time" else "MHz"}')
        raise QdError(pos, f'expected {t}, got {v.type}')

    # ------------------------------------------------------------ operands (constant or register)
    def operand(self, e, want: str | None, pos: Pos):
        """('const', value) or ('var', name); None if e is not a plain operand."""
        if isinstance(e, A.Name) and e.id in self.vars and self._lookup(e.id) is None:
            vt = self.vars[e.id].type
            if want and vt != want:
                raise QdError(pos, f"'{e.id}' is {vt}, expected {want}")
            return ('var', e.id)
        try:
            v = self.const(e)
        except _RuntimeRef:
            return None
        if not want:
            return ('const', v)
        value = self.coerce(v, want, pos)
        return ('const', self.clocks(value, pos) if want == 'time' else value)

    def clocks(self, seconds: float, pos: Pos) -> int:
        period = self.t.fpga.fpga_clk_period
        n = round(seconds / period)
        if abs(n * period - seconds) > 1e-15:
            self.diag.warn(pos, f'{seconds:g} s is not a multiple of the {period * 1e9:g} ns clock; rounded')
        return n

    def _var_type_of(self, *exprs):
        for e in exprs:
            if isinstance(e, A.Name) and e.id in self.vars and self._lookup(e.id) is None:
                return self.vars[e.id].type
        return None

    # ------------------------------------------------------------ statements
    def items(self, items) -> list:
        out = []
        for it in items:
            out += self.item(it)
        return out

    def block(self, b: A.Block) -> list:
        self.env.append({})
        try:
            return self.items(b.items)
        finally:
            self.env.pop()

    def item(self, it) -> list:
        m = getattr(self, '_' + type(it).__name__, None)
        if m is None:
            raise QdError(getattr(it, 'pos', Pos(0, 0)), f'{type(it).__name__} not supported')
        return m(it)

    def _QubitDecl(self, d: A.QubitDecl):
        if self.inlining or len(self.env) > 1:
            raise QdError(d.pos, 'qubits must be declared at top level')
        for q in d.names:
            self._taken(q, d.pos)
            if not self.t.has_qubit(q):
                raise QdError(d.pos, f"no calibrated qubit '{q}' in {self.t.qchip_path}")
            self.qubits[q] = d.pos
        return []

    def _ConstDecl(self, d: A.ConstDecl):
        self._taken(d.name, d.pos)
        try:
            v = self.const(d.value)
        except _RuntimeRef as r:
            raise QdError(r.pos, f"constant '{d.name}' depends on register '{r.name}'",
                          f'use  {d.name} : <type> = ...  for a runtime variable') from None
        if d.type:
            v = CVal(d.type, self.coerce(v, d.type, d.pos))
        self.env[-1][d.name] = v
        return []

    def _ProcDecl(self, d: A.ProcDecl):
        self._taken(d.name, d.pos)
        if len(self.env) > 1:
            raise QdError(d.pos, 'procs must be declared at top level')
        self.procs[d.name] = d
        return []

    def _VarDecl(self, d: A.VarDecl):
        if self.inlining:
            raise QdError(d.pos, 'registers cannot be declared inside a proc (it is inlined)',
                          'declare it at top level and pass it in by name')
        self._taken(d.name, d.pos)
        t = d.type
        if t is None:
            if isinstance(d.init, A.Call) and d.init.func == 'measure':
                t = 'int'
            else:
                try:
                    v = self.const(d.init)
                except _RuntimeRef as r:
                    t = self.vars[r.name].type
                else:
                    if v.type == 'num' and isinstance(v.value, int):
                        t = 'int'
                    elif v.type in REGISTER_TYPES:
                        t = v.type
                    elif v.type == 'num':
                        raise QdError(d.pos, f"cannot infer the type of '{d.name}' from {v.value}",
                                      f'write  {d.name} : amp = {v.value};  or  {d.name} : phase = {v.value};')
                    else:
                        t = v.type
        if t not in REGISTER_TYPES:
            raise QdError(d.pos, f'{t} registers are not supported; registers are int, amp, phase or time',
                          f'use a constant:  {d.name} : {t} : ...;')
        self.vars[d.name] = VarInfo(d.name, t, d.pos)
        return self._assign(d.name, d.init if d.init is not None else A.Num(0, d.pos), d.pos)

    def _Assign(self, s: A.Assign):
        if s.target not in self.vars or self._lookup(s.target) is not None:
            if self._lookup(s.target) is not None:
                raise QdError(s.pos, f"'{s.target}' is a constant")
            raise QdError(s.pos, f"unknown register '{s.target}'", self._suggest(s.target))
        value = s.value
        if s.op != '=':
            value = A.BinOp(s.op[0], A.Name(s.target, s.pos), s.value, s.pos)
        return self._assign(s.target, value, s.pos)

    def _assign(self, dst: str, e, pos: Pos) -> list:
        t = self.vars[dst].type
        if isinstance(e, A.Call) and e.func == 'measure':
            if t != 'int':
                raise QdError(pos, f"measure() yields an int; '{dst}' is {t}")
            q = self._measure_qubit(e)
            self._fproc_check(q, e.pos)
            return [self._read(q, pos),
                    MClassical({'name': 'read_fproc', 'func_id': f'{q}.meas', 'var': dst}, {dst}, set(), pos)]
        op = self.operand(e, t, pos)
        if op is not None:
            if op[0] == 'const':
                if t in ('amp', 'phase', 'time') and op[1] < 0:
                    self.taint_src.setdefault(dst, pos)
                return [MClassical({'name': 'set_var', 'var': dst, 'value': op[1]}, {dst}, set(), pos)]
            self.flows.append((dst, op[1]))
            return [MClassical({'name': 'alu', 'op': 'add', 'lhs': 0, 'rhs': op[1], 'out': dst},
                               {dst}, {op[1]}, pos)]
        if isinstance(e, A.BinOp) and e.op in '+-':
            a, b = self.operand(e.lhs, t, pos), self.operand(e.rhs, t, pos)
            if a is not None and b is not None:
                return [self._alu(dst, t, e.op, a, b, pos)]
        raise QdError(pos, 'too complex for the processor ALU: one + or - between a register and a '
                      'constant or register per statement',
                      'split it into steps; * and / are only allowed between constants')

    def _alu(self, dst, t, op, a, b, pos) -> MClassical:
        uses = {x[1] for x in (a, b) if x[0] == 'var'}
        for u in uses:
            self.flows.append((dst, u))
        if a[0] == 'const' and b[0] == 'const':
            v = a[1] + b[1] if op == '+' else a[1] - b[1]
            return MClassical({'name': 'set_var', 'var': dst, 'value': v}, {dst}, set(), pos)
        negative = op == '-' or any(x[0] == 'const' and x[1] < 0 for x in (a, b))
        if t in ('amp', 'phase', 'time') and negative:
            self.taint_src.setdefault(dst, pos)
        if op == '+':
            lhs, rhs = (a, b) if b[0] == 'var' else (b, a)
            ir = {'name': 'alu', 'op': 'add', 'lhs': lhs[1], 'rhs': rhs[1], 'out': dst}
        elif b[0] == 'var':                                  # x - var  -> sub
            ir = {'name': 'alu', 'op': 'sub', 'lhs': a[1], 'rhs': b[1], 'out': dst}
        else:                                                # var - c  -> add(-c)
            ir = {'name': 'alu', 'op': 'add', 'lhs': -b[1], 'rhs': a[1], 'out': dst}
        return MClassical(ir, {dst}, uses, pos)

    # ------------------------------------------------------------ conditions
    def cond(self, c: A.Cond, allow_negate: bool) -> dict:
        """Normalize to the hardware form  lhs <ge|le|eq> rhs_var  (or FPROC data).
        Returns {'static': bool} for constant conditions."""
        sides = (c.lhs, c.rhs)
        meas = [isinstance(s, A.Call) and s.func == 'measure' for s in sides]
        if any(meas):
            if not allow_negate:
                raise QdError(c.pos, 'a loop condition cannot read a measurement directly',
                              'measure into a register first:  m = measure(Q0);  ... while m == 1;')
            if all(meas):
                raise QdError(c.pos, 'cannot compare two measurements')
            q = self._measure_qubit(sides[meas.index(True)])
            self._fproc_check(q, c.pos)
            other = self.operand(sides[1 - meas.index(True)], 'int', c.pos)
            if other is None:
                raise QdError(c.pos, 'compare a measurement with an int constant or register')
            op = c.op if meas[1] else _FLIP[c.op]                 # form: other OP data
            negate = op in _NEGATE
            if negate:
                op = _NEGATE[op]
            return {'lhs': other[1], 'op': _ALU[op], 'rhs': None, 'func_id': f'{q}.meas',
                    'measured': q, 'negate': negate, 'uses': {other[1]} if other[0] == 'var' else set()}

        t = self._var_type_of(c.lhs, c.rhs)
        a, b = self.operand(c.lhs, t, c.pos), self.operand(c.rhs, t, c.pos)
        if a is None or b is None:
            raise QdError(c.pos, 'compare a register with a constant or another register',
                          'compute the expression into a register first')
        if t is None:
            av, bv = a[1].value, b[1].value
            return {'static': {'==': av == bv, '!=': av != bv, '<': av < bv, '>': av > bv,
                               '<=': av <= bv, '>=': av >= bv}[c.op]}
        if c.op != '==' and c.op != '!=':
            if t == 'phase':
                raise QdError(c.pos, 'phase registers cannot be ordered: they wrap modulo 2*pi',
                              'compare with == or keep a separate int counter')
            if t == 'amp':
                self.ordering_sites.append(({x[1] for x in (a, b) if x[0] == 'var'}, c.pos))
        if t == 'amp' and any(x[0] == 'const' and x[1] < 0 for x in (a, b)):
            raise QdError(c.pos, 'negative amp constant in a comparison',
                          'the constant is encoded as a 16-bit word and compared as a positive 32-bit value')
        op, negate = c.op, False
        if op in _NEGATE:
            if allow_negate:
                op, negate = _NEGATE[op], True
            elif t == 'int' and op in ('<=', '>=') and (a[0] == 'const' or b[0] == 'const'):
                # x <= c  ->  x < c+1 ;  c <= x  ->  c-1 < x
                if b[0] == 'const':
                    b = ('const', b[1] + (1 if op == '<=' else -1))
                else:
                    a = ('const', a[1] - (1 if op == '<=' else -1))
                op = op[0]
            else:
                raise QdError(c.pos, f"'{c.op}' is not available in a loop condition for {t}",
                              'the hardware compares with <, > and == only, and a loop cannot negate its test.\n'
                              'For int, compare against a constant (rewritten to < or > with +-1).')
        if b[0] == 'var':
            lhs, aop, rhs = a[1], _ALU[op], b[1]
        else:
            lhs, aop, rhs = b[1], _ALU[_FLIP[op]], a[1]
        return {'lhs': lhs, 'op': aop, 'rhs': rhs, 'func_id': None, 'measured': None, 'negate': negate,
                'uses': {x[1] for x in (a, b) if x[0] == 'var'}}

    def _check_amp_ordering(self):
        tainted = dict(self.taint_src)
        changed = True
        while changed:
            changed = False
            for dst, src in self.flows:
                if src in tainted and dst not in tainted:
                    tainted[dst] = tainted[src]
                    changed = True
        for var, pos in self.delay_sites:
            if var in tainted:
                raise QdError(pos, f"runtime delay '{var}' may become negative (line {tainted[var].line})",
                              'a negative delay puts the next trigger in the past and the core hangs\n'
                              '(RTL test t3). Only add non-negative amounts to delay registers.')
        for used, pos in self.ordering_sites:
            bad = sorted(v for v in used if v in tainted)
            if bad:
                src = tainted[bad[0]]
                raise QdError(pos, f"ordering compare on amp register '{bad[0]}', which may hold a "
                              f"negative step (line {src.line})",
                              'amp is a 16-bit word: pulses use the low 16 bits and play the right value,\n'
                              'but the 32-bit comparison sees the wrapped word (RTL test t6).\n'
                              'Count iterations in an int register instead.')

    # ------------------------------------------------------------ calls
    def _CallStmt(self, s: A.CallStmt):
        c = s.call
        f = getattr(self, '_call_' + c.func, None)
        if f is not None:
            return f(c)
        if c.func in self.procs:
            return self._inline(c)
        return self._gate(c.func, c.args, c.pos)

    def _read(self, q: str, pos: Pos) -> MTimed:
        if not self.t.has_gate('read', [q]):
            raise QdError(pos, f'no calibrated read for {q}')
        return MTimed('gate', {'name': 'read', 'qubit': [q]}, frozenset([q]), pos)

    def _fproc_check(self, q: str, pos: Pos):
        """Measurement feedback: the result must be addressable through FPROC."""
        if f'{q}.meas' not in self.t.fpga.fproc_channels:
            raise QdError(pos, f'measurement feedback on {q} is not available: FPROC has no channel {q}.meas',
                          'distproc.hwconfig.FPGAConfig defines Q0.meas ... Q15.meas (hwconfig.py:101-103)')
        problem = self.t.cores.fproc_problem(q)
        if problem:
            raise QdError(pos, f'measurement feedback on {q} is ambiguous or unavailable', problem)

    def _measure_qubit(self, c: A.Call) -> str:
        if len(c.args) != 1 or c.args[0].name:
            raise QdError(c.pos, 'measure takes one qubit')
        return self._qubit(c.args[0].value, c.args[0].pos)

    def _call_measure(self, c: A.Call):
        return [self._read(self._measure_qubit(c), c.pos)]

    def _call_barrier(self, c: A.Call):
        qs = [self._qubit(a.value, a.pos) for a in c.args]
        if not qs:
            raise QdError(c.pos, 'barrier needs at least one qubit')
        return [MTimed('barrier', {'name': 'barrier', 'qubit': sorted(qs)}, frozenset(qs), c.pos)]

    def _call_delay(self, c: A.Call):
        if not c.args or c.args[0].name:
            raise QdError(c.pos, 'delay(t [, qubits...])')
        try:
            v = self.const(c.args[0].value)
        except _RuntimeRef as r:
            return self._runtime_delay(r, c)
        t = self.coerce(v, 'time', c.args[0].pos)
        if t < 0:
            raise QdError(c.pos, 'negative delay')
        qs = [self._qubit(a.value, a.pos) for a in c.args[1:]]
        return [MTimed('delay', {'name': 'delay', 't': t}, frozenset(qs) if qs else None, c.pos)]

    def _runtime_delay(self, r: _RuntimeRef, c: A.Call):
        if not isinstance(c.args[0].value, A.Name):
            raise QdError(r.pos, 'a runtime delay takes a single time register', TIER3_DELAY)
        if self.vars[r.name].type != 'time':
            raise QdError(r.pos, f"delay needs a time; '{r.name}' is {self.vars[r.name].type}", TIER3_DELAY)
        if len(c.args) > 1:
            raise QdError(c.pos, 'a runtime delay always applies to every qubit',
                          'it shifts the clock of every core, so cores stay aligned')
        if SHIFT_REG not in self.vars:
            self.vars[SHIFT_REG] = VarInfo(SHIFT_REG, 'int', c.pos)
        self.delay_sites.append((r.name, c.pos))
        return [MTimed('rdelay', {'var': r.name}, None, c.pos, {r.name, SHIFT_REG})]

    def _call_gate(self, c: A.Call):
        if not c.args or not isinstance(c.args[0].value, A.Str):
            raise QdError(c.pos, 'gate("name", qubits...)')
        return self._gate(c.args[0].value.value, c.args[1:], c.pos)

    def _gate(self, name: str, args: list, pos: Pos):
        if any(a.name for a in args):
            raise QdError(pos, f'gate {name} takes qubits only')
        qs = [self._qubit(a.value, a.pos) for a in args]
        if not qs:
            raise QdError(pos, f"unknown statement '{name}()'")
        if not self.t.has_gate(name, qs):
            avail = self.t.gates_for(qs)
            close = difflib.get_close_matches(name, avail, n=1)
            hint = (f"did you mean '{close[0]}'? " if close else '') + \
                   (f'calibrated gates for {"".join(qs)}: {", ".join(avail)}' if avail else
                    f'no gates are calibrated for {"".join(qs)}')
            raise QdError(pos, f"unknown gate '{name}' for {', '.join(qs)}", hint)
        if self.loop_depth and self.t.gate_has_virtual_z(name, qs):
            self.diag.warn(pos, f'{name} on {", ".join(qs)} applies a virtual-Z phase update inside a loop; '
                           'QubiC tracks frame phases statically, so iterations after the first may play '
                           'pulses with the wrong phase')
        return [MTimed('gate', {'name': name, 'qubit': qs}, frozenset(qs), pos)]

    def _call_pulse(self, c: A.Call):
        args = list(c.args)
        if not args or args[0].name:
            raise QdError(c.pos, 'pulse(channel, freq=, amp=, phase=, width=, env=)')
        ch = self.const(args[0].value)
        if ch.type != 'channel':
            raise QdError(args[0].pos, 'first argument must be a channel such as Q0.qdrv')
        q, kind = ch.value.split('.')
        kw = {}
        for a in args[1:]:
            if a.name not in ('freq', 'amp', 'phase', 'width', 'env'):
                raise QdError(a.pos, f"unknown pulse parameter '{a.name}'",
                              'parameters: freq, amp, phase, width, env')
            kw[a.name] = a
        for need in ('amp', 'width', 'env'):
            if need not in kw:
                raise QdError(c.pos, f'pulse needs {need}=')
        uses = set()

        def reg_or_const(name, t):
            a = kw.get(name)
            if a is None:
                return 0.0
            op = self.operand(a.value, t, a.pos)
            if op is None:
                raise QdError(a.pos, f'{name} must be a constant or a single {t} register')
            if op[0] == 'var':
                uses.add(op[1])
            return op[1]

        amp, phase = reg_or_const('amp', 'amp'), reg_or_const('phase', 'phase')
        try:
            width = self.coerce(self.const(kw['width'].value), 'time', kw['width'].pos)
        except _RuntimeRef as r:
            raise QdError(r.pos, 'pulse width must be a constant: it fixes the envelope samples', TIER3_DELAY) from None
        env = self.const(kw['env'].value)
        if env.type != 'env':
            raise QdError(kw['env'].pos, 'env must be an envelope such as cos_edge_square(0.25)',
                          'envelopes: ' + ', '.join(sorted(self.t.envelopes)))
        if 'freq' in kw:
            f = self.const(kw['freq'].value)
            if f.type != 'freq':
                raise QdError(kw['freq'].pos, f'freq must be a frequency (e.g. Q0.freq or 4.9 GHz), got {f.type}')
            freq = f.value
        else:
            freq = f'{q}.{DEFAULT_FREQ[kind]}'
        if len(uses) > 1:
            self.diag.warn(c.pos, 'pulse with several register parameters becomes several instructions; '
                           'the QubiC scheduler does not budget for the extra pulse_write')
        ir = {'name': 'pulse', 'dest': ch.value, 'freq': freq, 'amp': amp, 'phase': phase,
              'twidth': width, 'env': env.value, 'tag': f'L{c.pos.line}'}
        return [MTimed('pulse', ir, frozenset([q]), c.pos, uses)]

    def _inline(self, c: A.Call):
        p = self.procs[c.func]
        if c.func in self.inlining:
            raise QdError(c.pos, f"recursive proc '{c.func}'")
        if len(c.args) != len(p.params):
            raise QdError(c.pos, f'{c.func} takes {len(p.params)} arguments, got {len(c.args)}')
        bind = {}
        for (pname, ptype), a in zip(p.params, c.args):
            try:
                v = self.const(a.value)
            except _RuntimeRef as r:
                raise QdError(r.pos, f"proc arguments are compile-time; '{r.name}' is a register",
                              'use the register by name inside the proc instead') from None
            bind[pname] = v if ptype == 'qubit' and v.type == 'qubit' else CVal(ptype, self.coerce(v, ptype, a.pos))
        self.inlining.append(c.func)
        self.env.append(bind)
        try:
            return self.items(p.body.items)
        finally:
            self.env.pop()
            self.inlining.pop()

    # ------------------------------------------------------------ control flow
    def _If(self, s: A.If):
        cnd = self.cond(s.cond, allow_negate=True)
        then = self.block(s.then)
        els = [] if s.els is None else (self.block(s.els) if isinstance(s.els, A.Block) else self._If(s.els))
        if 'static' in cnd:
            self.diag.warn(s.pos, f'condition is always {cnd["static"]}')
            return then if cnd['static'] else els
        if cnd['negate']:
            then, els = els, then
        node = MIf(cnd['lhs'], cnd['op'], cnd['rhs'], cnd['func_id'], then, els, s.pos, cnd['uses'], cnd['measured'])
        return ([self._read(cnd['measured'], s.cond.pos)] if cnd['measured'] else []) + [node]

    def _loop(self, c: A.Cond, body: list, pos: Pos) -> MLoop | None:
        cnd = self.cond(c, allow_negate=False)
        if 'static' in cnd:
            if cnd['static']:
                raise QdError(c.pos, 'loop condition is always true: the program would never end')
            return None
        return MLoop(cnd['lhs'], cnd['op'], cnd['rhs'], body, pos, cnd['uses'])

    def _loop_body(self, b: A.Block) -> list:
        self.loop_depth += 1
        try:
            return self.block(b)
        finally:
            self.loop_depth -= 1

    def _DoWhile(self, s: A.DoWhile):
        body = self._loop_body(s.body)
        loop = self._loop(s.cond, body, s.pos)
        return body if loop is None else [loop]

    def _ForCond(self, s: A.ForCond):
        probe = self.cond(s.cond, allow_negate=True)
        if 'static' in probe:
            if probe['static']:
                raise QdError(s.cond.pos, 'loop condition is always true: the program would never end')
            self.diag.warn(s.pos, 'loop condition is always false')
            return []
        self.loop_depth += 1
        try:
            guard = self._If(A.If(s.cond, s.body, None, s.pos))  # pre-test = if (c) { do {...} while (c) }
        finally:
            self.loop_depth -= 1
        node = guard[-1]
        loop = self._loop(s.cond, node.then or node.els, s.pos)
        if node.then:
            node.then = [loop]
        else:
            node.els = [loop]
        return guard

    def _ForRange(self, s: A.ForRange):
        if s.var not in self.vars:
            self._taken(s.var, s.pos)
            self.vars[s.var] = VarInfo(s.var, 'int', s.pos)
        elif self.vars[s.var].type != 'int':
            raise QdError(s.pos, f"loop variable '{s.var}' must be int")
        init = self._assign(s.var, s.lo, s.pos)
        body = self._loop_body(s.body) + [self._alu(s.var, 'int', '+', ('var', s.var), ('const', 1), s.pos)]
        loop = self._loop(A.Cond('<', A.Name(s.var, s.pos), s.hi, s.pos), body, s.pos)
        guard = self.cond(A.Cond('<', s.lo, s.hi, s.pos), allow_negate=True)
        if 'static' in guard:
            return init + ([loop] if guard['static'] else [])
        then, els = ([loop], []) if not guard['negate'] else ([], [loop])
        return init + [MIf(guard['lhs'], guard['op'], guard['rhs'], None, then, els, s.pos, guard['uses'])]

    def _Unroll(self, s: A.Unroll):
        if s.values is not None:
            values = [self.const(v) for v in s.values]
        else:
            lo, hi = self.const(s.lo), self.const(s.hi)
            step = self.const(s.step) if s.step is not None else CVal(lo.type, 1)
            if step.value <= 0:
                raise QdError(s.pos, 'step must be positive')
            n = math.ceil((hi.value - lo.value) / step.value - 1e-9)
            if n > MAX_UNROLL:
                raise QdError(s.pos, f'{n} iterations exceed the unroll limit of {MAX_UNROLL}')
            values = [CVal(lo.type, lo.value + k * step.value) for k in range(max(n, 0))]
        out = []
        for v in values:
            self.env.append({s.var: v})
            try:
                out += self.block(s.body)
            finally:
                self.env.pop()
        return out

    def _Parallel(self, s: A.Parallel):
        return [MParallel([self.block(b) for b in s.branches], s.pos)]

    def _Block(self, b: A.Block):
        return self.block(b)

    # ------------------------------------------------------------ helpers
    def _suggest(self, name: str) -> str | None:
        known = list(self.vars) + list(self.qubits) + list(self.procs) + [k for s in self.env for k in s]
        close = difflib.get_close_matches(name, known, n=1)
        return f"did you mean '{close[0]}'?" if close else None

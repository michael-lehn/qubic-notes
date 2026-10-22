"""MIR -> QubiC-IR: scope inference and barrier insertion.

Scopes.  QubiC replicates each register on every core in its scope, and a core
only executes the control flow (loops, branches) whose scope contains it.  So:
  - a register used by a pulse on Q lives on Q's core;
  - a loop/branch must span every qubit touched in its body *and* every core
    holding a register used inside it, or those cores would run the body once;
  - a register tested by a loop/branch condition must live on every core of
    that loop/branch, because each core evaluates the condition itself;
  - registers combined in one ALU op share a scope (the IR requires it).
These constraints feed each other; we iterate to a fixed point.

Sequencing.  Statements separated by ';' run strictly one after another: before
each timed statement we insert barrier(previous footprint | this footprint).
`par` branches start together (barrier over all branches) and the next
statement waits for the longest one.  Barriers do not carry across QubiC basic
blocks, so every branch body starts with its own barrier (loops get one from
FlattenProgram)."""
from __future__ import annotations

from .diag import QdError
from .sema import SHIFT_REG, MClassical, MIf, MLoop, MPar, MTimed, Sema
from .target import N_REGS, Target


class Lowering:
    def __init__(self, sema: Sema, mir: list, target: Target):
        self.sema, self.mir, self.t = sema, mir, target
        self.var_scope: dict[str, set] = {v: set() for v in sema.vars}
        self.node_scope: dict[int, set] = {}
        # every qubit the program touches; runtime delays span all of them
        self.all_qubits = {q for n in self._walk(mir) if isinstance(n, MTimed) and n.qubits for q in n.qubits} | \
                          {n.measured for n in self._walk(mir) if isinstance(n, MIf) and n.measured}

    # ------------------------------------------------------------ queries
    @staticmethod
    def _children(n) -> list[list]:
        if isinstance(n, MIf):
            return [n.then, n.els]
        if isinstance(n, MLoop):
            return [n.body]
        if isinstance(n, MPar):
            return n.branches
        return []

    def _walk(self, nodes):
        for n in nodes:
            yield n
            for child in self._children(n):
                yield from self._walk(child)

    def _static_qubits(self, nodes) -> set:
        qs = {q for n in self._walk(nodes) if isinstance(n, MTimed) and n.qubits for q in n.qubits} | \
             {n.measured for n in self._walk(nodes) if isinstance(n, MIf) and n.measured}
        if any(isinstance(n, MTimed) and n.kind == 'rdelay' for n in self._walk(nodes)):
            qs |= self.all_qubits
        return qs

    def _vars_in(self, nodes) -> set:
        vs = set()
        for n in self._walk(nodes):
            if isinstance(n, MClassical):
                vs |= n.defs | n.uses
            elif isinstance(n, (MTimed, MIf, MLoop)):
                vs |= n.uses
        return vs

    # ------------------------------------------------------------ scope inference
    def infer_scopes(self):
        nodes = list(self._walk(self.mir))
        controls = [n for n in nodes if isinstance(n, (MIf, MLoop))]
        groups = self._alu_groups(nodes)
        for n in nodes:
            if isinstance(n, MTimed):
                for v in n.uses:
                    self.var_scope[v] |= set(n.qubits) if n.qubits else set(self.all_qubits)

        default = self._default_qubit()
        for _ in range(2):                              # second round after giving idle registers a home
            changed = True
            while changed:
                changed = False
                for n in controls:
                    s = self._static_qubits([n]) | set().union(*(self.var_scope[v] for v in self._vars_in([n])))
                    if s != self.node_scope.get(id(n)):
                        self.node_scope[id(n)] = s
                        changed = True
                    for v in n.uses:
                        if not s <= self.var_scope[v]:
                            self.var_scope[v] |= s
                            changed = True
                for g in groups:
                    u = set().union(*(self.var_scope[v] for v in g))
                    for v in g:
                        if self.var_scope[v] != u:
                            self.var_scope[v] = set(u)
                            changed = True
            idle = [v for v, s in self.var_scope.items() if not s]
            if not idle:
                break
            for v in idle:
                self.var_scope[v] = {default}
        self._check_registers()

    def _alu_groups(self, nodes) -> list[set]:
        parent = {v: v for v in self.var_scope}

        def find(v):
            while parent[v] != v:
                parent[v] = parent[parent[v]]
                v = parent[v]
            return v

        for n in nodes:
            if isinstance(n, MClassical):
                vs = list(n.defs | n.uses)
                for v in vs[1:]:
                    parent[find(v)] = find(vs[0])
        groups: dict[str, set] = {}
        for v in parent:
            groups.setdefault(find(v), set()).add(v)
        return [g for g in groups.values() if len(g) > 1]

    def _default_qubit(self) -> str:
        used = self._static_qubits(self.mir)
        for q in self.sema.qubits:
            if q in used:
                return q
        if self.sema.qubits:
            return next(iter(self.sema.qubits))
        raise QdError(next(iter(self.sema.vars.values())).pos,
                      'registers need a core: declare at least one qubit')

    def _check_registers(self):
        per_core: dict[int, list[str]] = {}
        for v, s in self.var_scope.items():
            for core in {self.t.core_of(q) for q in s}:
                per_core.setdefault(core, []).append(v)
        for core, vs in sorted(per_core.items()):
            if len(vs) > N_REGS:
                vs = sorted(vs, key=lambda v: (self.sema.vars[v].pos.line, self.sema.vars[v].pos.col))
                raise QdError(self.sema.vars[vs[N_REGS]].pos,
                              f'core {core} needs {len(vs)} registers; the processor has {N_REGS}',
                              'registers on this core: ' + ', '.join(vs))

    # ------------------------------------------------------------ footprints
    def footprint(self, n, enclosing: set) -> set:
        if isinstance(n, MTimed):
            if n.kind == 'rdelay':
                return set(self.all_qubits)
            return set(n.qubits) if n.qubits else set(enclosing)
        if isinstance(n, (MIf, MLoop)):
            return set(self.node_scope[id(n)])
        if isinstance(n, MPar):
            return set().union(*(self._branch_fp(b, enclosing) for b in n.branches))
        return set()

    def _branch_fp(self, branch: list, enclosing: set) -> set:
        own = self._static_qubits(branch)
        inner = set(own) or set(enclosing)
        for n in branch:
            inner |= self.footprint(n, inner) if not isinstance(n, MClassical) else set()
        return inner

    def _check_par(self, n: MPar, enclosing: set):
        seen: dict[str, int] = {}
        for i, b in enumerate(n.branches):
            for q in self._branch_fp(b, enclosing):
                if q in seen:
                    hint = ('branches must use disjoint qubits: they run on separate cores.\n'
                            'Two pulses on one core start 3 clocks apart; on one channel they serialize.')
                    for j in (seen[q], i):
                        bj = n.branches[j]
                        regs = sorted(v for v in self._vars_in(bj) if q in self.var_scope[v])
                        if q not in self._static_qubits(bj) and regs:
                            hint += (f"\nHere {q} enters branch {j + 1} through register(s) {', '.join(regs)}, "
                                     f"whose condition must be evaluated on {q}'s core too.")
                    raise QdError(n.pos, f'par branches {seen[q] + 1} and {i + 1} both use {q}', hint)
                seen[q] = i

    # ------------------------------------------------------------ emission
    def emit(self) -> list[dict]:
        self.infer_scopes()
        decls = [{'name': 'declare', 'var': v, 'dtype': 'int' if info.type == 'time' else info.type,
                  'scope': sorted(self.var_scope[v])}
                 for v, info in self.sema.vars.items()]
        top = self._static_qubits(self.mir) or {self._default_qubit()}
        return decls + self._seq(self.mir, top)

    @staticmethod
    def _barrier(qs) -> dict:
        return {'name': 'barrier', 'qubit': sorted(qs)}

    def _seq(self, nodes: list, enclosing: set) -> list[dict]:
        out, prev = [], None
        for n in nodes:
            if isinstance(n, MClassical):
                out.append(dict(n.ir))
                continue
            fp = self.footprint(n, enclosing)
            if prev is not None:
                out.append(self._barrier(prev | fp))
            elif isinstance(n, MPar):
                out.append(self._barrier(fp))
            out += self._node(n, enclosing, fp)
            prev = fp
        return out

    def _node(self, n, enclosing: set, fp: set) -> list[dict]:
        if isinstance(n, MTimed):
            ir = dict(n.ir)
            if n.kind == 'delay':
                ir['qubit'] = sorted(fp)
            if n.kind == 'rdelay':          # qclk += -tau on every core (patched IR op inc_qclk)
                return [{'name': 'alu', 'op': 'sub', 'lhs': 0, 'rhs': ir['var'], 'out': SHIFT_REG},
                        {'name': 'inc_qclk', 'var': SHIFT_REG, 'scope': sorted(fp)}]
            return [ir]
        if isinstance(n, MIf):
            scope = sorted(fp)
            then = [self._barrier(fp)] + self._seq(n.then, fp) if n.then else []
            els = [self._barrier(fp)] + self._seq(n.els, fp) if n.els else []
            if n.func_id:
                return [{'name': 'branch_fproc', 'cond_lhs': n.lhs, 'alu_cond': n.op, 'func_id': n.func_id,
                         'scope': scope, 'true': then, 'false': els}]
            return [{'name': 'branch_var', 'cond_lhs': n.lhs, 'alu_cond': n.op, 'cond_rhs': n.rhs,
                     'scope': scope, 'true': then, 'false': els}]
        if isinstance(n, MLoop):
            return [{'name': 'loop', 'cond_lhs': n.lhs, 'alu_cond': n.op, 'cond_rhs': n.rhs,
                     'scope': sorted(fp), 'body': self._seq(n.body, fp)}]
        if isinstance(n, MPar):
            self._check_par(n, enclosing)
            out = []
            for b in n.branches:
                out += self._seq(b, self._branch_fp(b, enclosing))
            return out
        raise AssertionError(n)

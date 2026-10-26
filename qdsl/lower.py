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
A parallel block is one statement: a barrier over all branches before it, the
branches one after another in the IR (each scheduled from that barrier, so on
different cores they overlap; on a shared core QubiC issues them in turn), and
the next statement's barrier is the join.  Barriers do not carry across QubiC
basic blocks, so every branch body starts with its own barrier (loops get one
from FlattenProgram).

Cross-core order.  Cores agree on time only through timestamps.  QubiC rewinds
qclk by the body length at the end of every loop iteration (inc_qclk -delta) and
schedules what follows a loop from the loop's start time (passes.py:1020-1026);
that is right only on cores that ran the loop.  A core outside the loop would
fire its next pulse while the loop is still running.  So:
  - a runtime loop also spans every qubit with a quantum operation after it
    (`later`), and those cores run its control flow, reading the same registers
    and FPROC results (control-flow replication);
  - every core that runs a loop, or reads a measurement result, must have run
    the same runtime loops and delays before, so that its qclk maps to the same
    physical time (`_check_frames`).  Otherwise the program is rejected: two
    runtime loops in different parallel branches cannot both be followed by one core."""
from __future__ import annotations

from .diag import QdError
from .sema import SHIFT_REG, MClassical, MIf, MLoop, MParallel, MTimed, Sema
from .target import N_REGS, CoreId, Target


class Lowering:
    def __init__(self, sema: Sema, mir: list, target: Target):
        self.sema, self.mir, self.t = sema, mir, target
        # Scopes map to cores through target.cores. Sema accepted only placements that agree
        # with it, so the explicit placements and the configuration are the same mapping.
        for ch, (core, pos) in sema.placements.items():
            if target.cores.core_of_channel(ch) != core:
                raise QdError(pos, f'internal error: placement of {ch} disagrees with the channel configuration')
        self.var_scope: dict[str, set] = {v: set() for v in sema.vars}
        self.node_scope: dict[int, set] = {}
        # every qubit the program touches; runtime delays span all of them
        self.all_qubits = {q for n in self._walk(mir) if isinstance(n, MTimed) and n.qubits for q in n.qubits} | \
                          {n.measured for n in self._walk(mir) if isinstance(n, MIf) and n.measured}
        self.later: dict[int, set] = {}                 # loop -> qubits with quantum operations after it
        self._mark_later(mir, set())

    # ------------------------------------------------------------ queries
    @staticmethod
    def _children(n) -> list[list]:
        if isinstance(n, MIf):
            return [n.then, n.els]
        if isinstance(n, MLoop):
            return [n.body]
        if isinstance(n, MParallel):
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
        for n in self._walk(nodes):
            if isinstance(n, MLoop):
                qs |= self.later[id(n)]
        return qs

    def _op_qubits(self, nodes) -> set:
        """Qubits of the quantum operations (pulses, gates, reads, runtime delays) in nodes."""
        qs = set()
        for n in self._walk(nodes):
            if isinstance(n, MTimed) and n.kind in ('pulse', 'gate'):
                qs |= set(n.qubits)
            elif isinstance(n, MTimed) and n.kind == 'rdelay':
                qs |= self.all_qubits
        return qs

    def _mark_later(self, nodes: list, after: set):
        """later[loop] = qubits whose operations must wait for the loop: the rest of every
        enclosing sequence, the whole body of every enclosing loop (its next iteration), and
        nothing from other parallel branches."""
        for i, n in enumerate(nodes):
            rest = self._op_qubits(nodes[i + 1:]) | after
            if isinstance(n, MLoop):
                self.later[id(n)] = rest
                self._mark_later(n.body, rest | self._op_qubits(n.body))
            else:
                for child in self._children(n):
                    self._mark_later(child, rest)

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
        # QubiC replicates a register on every core holding a channel of its scope's qubits
        per_core: dict[CoreId, list[str]] = {}
        for v, s in self.var_scope.items():
            for core in self.t.cores.cores_of(*s):
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
        if isinstance(n, MParallel):
            return set().union(*(self._branch_fp(b, enclosing) for b in n.branches))
        return set()

    def _branch_fp(self, branch: list, enclosing: set) -> set:
        own = self._static_qubits(branch)
        inner = set(own) or set(enclosing)
        for n in branch:
            inner |= self.footprint(n, inner) if not isinstance(n, MClassical) else set()
        return inner

    def _check_parallel(self, n: MParallel):
        """Branches must be independent: disjoint qubits, and no register written in one
        branch and used in another.  Sharing a processor core is fine: the core issues one
        branch's instructions after the other's, which QubiC's scheduler accounts for."""
        for b in n.branches:
            for m in self._walk(b):
                if isinstance(m, MTimed) and m.kind == 'rdelay':
                    raise QdError(m.pos, 'a runtime delay cannot be inside a parallel branch',
                                  'it shifts the clock of every core, so it would delay the other branches too;\n'
                                  'put it before or after the parallel block')
        used = [{q for m in self._walk(b) if isinstance(m, MTimed) and m.qubits for q in m.qubits} |
                {m.measured for m in self._walk(b) if isinstance(m, MIf) and m.measured} for b in n.branches]
        for i in range(len(used)):
            for j in range(i):
                common = sorted(used[i] & used[j])
                if common:
                    raise QdError(n.pos, f'parallel branches {j + 1} and {i + 1} both use {common[0]}',
                                  'parallel branches must be independent: operations on one qubit have an order,\n'
                                  'so write them in one branch (or sequentially)')
        defs = [{v for m in self._walk(b) if isinstance(m, MClassical) for v in m.defs} for b in n.branches]
        uses = [self._vars_in(b) for b in n.branches]
        for i in range(len(defs)):
            for j in range(len(defs)):
                race = sorted(defs[i] & uses[j]) if i != j else []
                if race:
                    raise QdError(n.pos, f"parallel branches {min(i, j) + 1} and {max(i, j) + 1} both use register "
                                  f"'{race[0]}', and branch {i + 1} writes it",
                                  'the branches are independent, so the other branch would see the old or the new '
                                  'value\ndepending on the schedule. Compute it before the block, or use it after '
                                  'the join.')

    def _check_fproc(self, func_id: str, readers: set, pos):
        q = func_id.removesuffix('.meas')
        problem = self.t.cores.fproc_problem(q, self.t.cores.cores_of(*readers))
        if problem:
            followers = sorted(set(readers) & set().union(*self.later.values()) - {q})
            if followers:
                problem += (f"\n{', '.join(followers)} must follow a loop that depends on this result: an "
                            'operation after a runtime loop starts only once the loop has ended, so its core '
                            "repeats the loop's control flow and needs the result too.")
            raise QdError(pos, f'measurement feedback on {q} could read the wrong result', problem)

    # ------------------------------------------------------------ cross-core time frames
    def _cores(self, qubits) -> set:
        return set(self.t.cores.cores_of(*qubits)) if qubits else set()

    def _check_frames(self):
        """Each core runs its loops and runtime delays in program order; its qclk maps to
        physical time through the ones it has run.  Cores that run a loop together, or read a
        measurement together with the measuring core, must have run the same ones before."""
        self._frames(self.mir, {})

    def _same_frame(self, cores: set, hist: dict, what: str, pos, followers: set = frozenset()):
        seen = {}
        for c in sorted(cores):
            seen.setdefault(hist.get(c, ()), c)
        if len(seen) < 2:
            return
        (ha, a), (hb, b) = sorted(seen.items(), key=lambda kv: len(kv[0]), reverse=True)[:2]
        extra = next(e for e in ha if e not in hb)
        why = ''
        for c in (a, b):
            qs = sorted(q for q in followers if c in self.t.cores.cores_of(q))
            if qs:
                why += f'; {c} takes part because {", ".join(qs)} must wait for it'
        raise QdError(pos, f'cannot guarantee the order of {what}: processor cores {a} and {b} both take part, '
                      f'but only {a} has run the {extra[1]} at line {extra[2].line} before{why}',
                      'a core runs its control flow in program order, and cores agree on time only through '
                      'timestamps.\nAfter a runtime loop, every core with later operations repeats the loop to '
                      'stay in step; one core cannot\nfollow two runtime loops that run at the same time in '
                      'different parallel branches, and current QubiC hardware\nhas no runtime barrier. Make the loops '
                      'sequential, unroll fixed counts (#unroll for), or drop the\noperations that need both.')

    def _frames(self, nodes: list, hist: dict):
        for n in nodes:
            if isinstance(n, MClassical) and n.ir['name'] == 'read_fproc':
                q = n.ir['func_id'].removesuffix('.meas')
                self._same_frame(self._cores(self.var_scope[n.ir['var']]) | self._cores({q}), hist,
                                 f'the measurement of {q}', n.pos)
            elif isinstance(n, MTimed) and n.kind == 'rdelay':
                for c in self._cores(self.all_qubits):
                    hist[c] = hist.get(c, ()) + (('rdelay', 'runtime delay', n.pos),)
            elif isinstance(n, MLoop):
                cores = self._cores(self.node_scope[id(n)])
                self._same_frame(cores, hist, 'the loop', n.pos, self.later[id(n)] - self._op_qubits(n.body))
                before = {c: hist.get(c, ()) for c in cores}
                self._frames(n.body, hist)
                for c in cores:
                    hist[c] = before[c] + (('loop', 'runtime loop', n.pos, hist.get(c, ())[len(before[c]):]),)
            elif isinstance(n, MIf):
                cores = self._cores(self.node_scope[id(n)])
                if n.func_id:
                    q = n.func_id.removesuffix('.meas')
                    self._same_frame(cores | self._cores({q}), hist, f'the measurement of {q}', n.pos)
                before = {c: hist.get(c, ()) for c in cores}
                arms = []
                for arm in (n.then, n.els):
                    h = dict(hist)
                    self._frames(arm, h)
                    arms.append(h)
                for c in cores:
                    inner = tuple(h.get(c, ())[len(before[c]):] for h in arms)
                    hist[c] = before[c] + ((('if', 'branch with a runtime loop', n.pos, inner),) if any(inner) else ())
            elif isinstance(n, MParallel):
                for b in n.branches:                      # cores run the branches in this order
                    self._frames(b, hist)

    # ------------------------------------------------------------ emission
    def emit(self) -> list[dict]:
        self.infer_scopes()
        self._check_frames()
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
                if n.ir['name'] == 'read_fproc':      # runs on every core of the register's scope
                    self._check_fproc(n.ir['func_id'], self.var_scope[n.ir['var']], n.pos)
                out.append(dict(n.ir))
                continue
            fp = self.footprint(n, enclosing)
            if prev is not None:
                out.append(self._barrier(prev | fp))
            elif isinstance(n, MParallel):
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
                self._check_fproc(n.func_id, fp, n.pos)
                return [{'name': 'branch_fproc', 'cond_lhs': n.lhs, 'alu_cond': n.op, 'func_id': n.func_id,
                         'scope': scope, 'true': then, 'false': els}]
            return [{'name': 'branch_var', 'cond_lhs': n.lhs, 'alu_cond': n.op, 'cond_rhs': n.rhs,
                     'scope': scope, 'true': then, 'false': els}]
        if isinstance(n, MLoop):
            return [{'name': 'loop', 'cond_lhs': n.lhs, 'alu_cond': n.op, 'cond_rhs': n.rhs,
                     'scope': sorted(fp), 'body': self._seq(n.body, fp)}]
        if isinstance(n, MParallel):
            self._check_parallel(n)
            out = []
            for b in n.branches:
                out += self._seq(b, self._branch_fp(b, enclosing))
            return out
        raise AssertionError(n)

"""
Preliminary specification:
    qubits and gates:
        - quantum gates supported according to gate_map.GateMap
        - mapping between declared qubits (e.g. qubit q[n]) given by qubit_map.QubitMap
    classical variables:
        - all sized integers are cast to 32 bit native int types
        - all bit types are cast to an array of integers
        - all floats are cast to native amp types
        - all angles are cast to native phase types
    classical flow:
        - if/else are converted to branch_var statements
        - for and while loops are supported
            - break, continue not supported
"""

NATIVE_INT_SIZE = 32

from openqasm3.visitor import QASMVisitor
import openpulse.ast as ast
from distproc.openqasm.qubit_map import QubitMap, QASMQubitMap, OpenPulseQubitMap
from distproc.openqasm.gate_map import GateMap, QASMGateMap, OpenPulseGateMap
import numpy as np
import operator
import os
import sys
import warnings
from attrs import define

__all__ = ['QASMQubiCVisitor',
           'OpenPulseQubiCVisitor',
          ]


class QASMQubiCParserError(Exception):
    def __init__(self, message, location):
        self._message = message
        self._location = location

    def __str__(self):
        return "'%s' at line %s" % (self._message, self._location)

class UndeclaredQubit(QASMQubiCParserError):
    pass

class UndeclaredVariable(QASMQubiCParserError):
    pass

class FloatingPointComputation(QASMQubiCParserError):
    pass


time_units = {
    ast.TimeUnit.ns: 1e-9,
    ast.TimeUnit.us: 1e-6,
    ast.TimeUnit.ms: 1e-3,
    ast.TimeUnit.s:  1e-0,
}

constants = {
    'pi' : np.pi,
}

op_mapping = {
    '==': 'eq',
    '>':  'ge',
    '<':  'le',
    '+':  'add',
    '-':  'sub',
}

unary_ops = {
    '+' : operator.pos,
    '-' : operator.neg,
}

binary_ops = {
    '+' : operator.add,
    '-' : operator.sub,
    '*' : operator.mul,
    '/' : operator.truediv,
}


@define
class _VariableContainer:
    var_names: list
    type: str = 'int'
    value: "int|float" = None


class QASMQubiCVisitor(QASMVisitor):
    DEF_NQUBITS = 16

    def __init__(self, qubit_map: QubitMap=QASMQubitMap(), gate_map: GateMap=QASMGateMap(), options: dict={}):
        self.qubit_map = qubit_map
        self.gate_map  = gate_map
        self.options   = options

        self.program = []
        self._cur_block = self.program      # pointer to current instr list

        self.qubits = {"$%d" % q : None for q in range(self.DEF_NQUBITS)}   # implicitly declared
        self.vars = {}
        self.params = {}

        self._vardecls = dict()
        self._measurements = dict()

        super().__init__()

    def _eval_expression(self, node: ast.Expression, scope: set=None):
        if isinstance(node, ast.FloatLiteral):
            return float(node.value)
        elif isinstance(node, ast.IntegerLiteral):
            return int(node.value)
        elif isinstance(node, ast.DurationLiteral):
            return node.value * time_units[node.unit]
        elif isinstance(node, ast.Identifier):
            for d in (constants, self.params):
                value = d.get(node.name, None)
                if value is not None:
                    return value
            var = self.vars.get(node.name, None)
            if var:
                if scope is not None:
                    self._update_scope(node.name, scope)
            return node.name
        elif isinstance(node, ast.UnaryExpression):
            operand = self._eval_expression(node.expression, scope)
            return unary_ops[node.op.name](operand)
        elif isinstance(node, ast.BinaryExpression):
            lhs = self._eval_expression(node.lhs, scope)
            rhs = self._eval_expression(node.rhs, scope)
            if (type(lhs) is str or type(rhs) is str) and\
                    (type(lhs) is float or type(rhs) is float):
                raise FloatingPointComputation(node.op.name, node.span.start_line)
            return binary_ops[node.op.name](lhs, rhs)
        elif isinstance(node, ast.IndexExpression):
            assert len(node.index) == 1 and "only single indexing is supported"
            index = node.index[0]
            return node.collection.name + ('_%d' % index.value)
        else:
            raise NotImplementedError(str(node))

    def _eval_variable(self, node: ast.QASMNode):
        if isinstance(node, ast.IndexedIdentifier):
            name = node.name.name
            assert len(node.indices) == 1 and \
                   len(node.indices[0]) == 1 and "only single indexing is supported"
            index = node.indices[0][0].value
            name += ('_%d' % index)
        elif isinstance(node, ast.Identifier):
            name = node.name
            if not name in self.vars:
                raise UndeclaredVariable(name, node.span.start_line)
        else:
            raise NotImplementedError(str(node))

        return name

    def _bind_phase(self, qubit):
        varname = "_bind_phase"+qubit
        if not varname in self._vardecls:
            vardecl = {'name': 'declare', 'var': varname, 'dtype': 'phase', 'scope': [qubit]}
            self._vardecls[varname] = vardecl
            self.program.insert(0, {'name': 'bind_phase', 'freq': f'{qubit}.freq', 'var': varname})
            self.program.insert(0, vardecl)

    def _declare_unscoped_var(self, varname: str, vartype: str=None, init: ast.Expression=None):
        vardecl = {'name': 'declare', 'var': varname, 'scope': None}
        self._cur_block.append(vardecl)

        value = None
        if init is not None:
            value = self._eval_expression(init)
            self._cur_block.append({'name': 'set_var', 'var': varname, 'value': value})

        self._vardecls[varname] = vardecl
        if vartype is not None:
            self.vars[varname] = _VariableContainer([varname], vartype, value)

    def _capture_scope(self, block: list):
        scope = set()

        for instr in block:
            try:
                qubits = instr['qubit']
                if type(qubits) == str:
                    qubits = [qubits]
                [scope.add(q) for q in qubits]
            except KeyError:
                continue

            if instr['name'] == 'virtual_z':
                # conditional Z can not be virtual, so bind it to a variable
                [self._bind_phase(q) for q in qubits]

        return scope

    def _update_scope(self, varname: str, scope: set):
        cur = self._vardecls[varname]['scope']
        if cur is None:
            self._vardecls[varname]['scope'] = scope
        else:
            self._vardecls[varname]['scope'].update(cur)

    def _get_hardware_qubits(self, qasm_qubits: list, context=None):
        hw_qubits = list()
        for qid in qasm_qubits:
            if isinstance(qid, ast.Identifier):          # single qubit
                if not qid.name in self.qubits:
                    raise UndeclaredQubit(qid.name, qid.span.start_line)
                hw_qubits.append(self.qubit_map.get_hardware_qubit(qid.name))
            elif isinstance(qid, ast.IndexedIdentifier): # index into qubit register
                idx = qid.indices[0][0].value
                if context:
                    indexed_qubits = context.get("indexed_qubits", None)
                    if indexed_qubits:
                        idx = indexed_qubits[idx]
                # a common case in Qiskit to declare qubits as arrays of size 1, in
                # which case the name is the enumerated label, not the index
                if idx == 0 and self.qubits.get(qid.name.name, -1) in (None, 1):
                    try:
                        int(qid.name.name[-1])   # ie. conventionally labeled, eg. "Q2"
                        idx = None
                    except ValueError:
                        pass
                hw_qubits.append(self.qubit_map.get_hardware_qubit(qid.name.name, idx))
            else:
                raise RuntimeError("cannot identify hardware qubit for", str(qid))

        return hw_qubits

    def visit(self, node: ast.QASMNode, context=None, qubits=None):
        try:
            if not context:
                context = {"label": "top", "indexed_qubits": qubits}
            elif qubits:
                context["indexed_qubits"] = qubits

            return super().visit(node, context)

        except Exception as e:
            tb = None
            if not isinstance(e, QASMQubiCParserError) or os.getenv('DISTPROC_FULL_TRACEBACKS'):
                tb = sys.exc_info()[2]
            raise e.with_traceback(tb)

    def visit_Program(self, node: ast.Program, context=None):
        # default, loops over all statements
        super().generic_visit(node, context)

        # QASM programs do not necessarily have an explicit reset; if none is provided,
        # add an implicit one (defaults to 500us).
        resets = set()
        for pc, instr in enumerate(self.program):
            if instr["name"] == "delay":          # assume this is the passive reset
                break

            elif instr["name"] == "_reset":       # fake instruction indicating active reset
                [resets.add(q) for q in instr["qubit"]]

            if "qubit" in instr:
                # verify that the qubit has been actively reset
                if resets:
                    qubits = instr["qubit"]
                    if type(qubits) == str: qubits = [qubits]
                    for q in qubits:
                        if not q in resets:
                            warnings.warn(f"qubit {q} was not reset")
                    continue

                # or insert a passive delay
                elif not "delay" in instr and self.options.get("reset", "passive") is not None:
                    delay = self.options.get("reset_delay", 500E-6)
                    self.program.insert(pc, {'name': 'barrier'})
                    self.program.insert(pc, {'name': 'delay', 't': delay})
                    break

        if resets:
            # remove reset bookkeeping
            self.program = [instr for instr in self.program if instr["name"] != "_reset"]

    def visit_BinaryExpression(self, node: ast.BinaryExpression, context=None):
        op = node.op.name
        lhs = self._eval_expression(node.lhs)
        rhs = self._eval_expression(node.rhs)

        if not isinstance(rhs, str):
            # rhs must be a variable; if it is a value, then invert the logic,
            # which requires rhs to be an int and lhs to be of bit type until
            # the IR is extended to support other types

            # workaround for a Qiskit bug: generated qasm code regularly has
            # "var" instead of "var[0]" if "var" is an array of 1 element
            if not lhs in self.vars and lhs+'_0' in self.vars:
                lhs = lhs+'_0'

            assert self.vars[lhs].type in ('bit', 'int')
            assert isinstance(rhs, int)
            if op == "==":
                t = lhs; lhs = rhs; rhs = t
            else:
                assert not "operation inversion not yet implemented"

        if context and context.get("label", "") != "branch":
            self._cur_block.append({'name': 'alu', 'op': op_mapping[op],
                                    'lhs': lhs, 'rhs': rhs, 'out': rhs})

        return lhs, op_mapping[op], rhs

    def visit_BranchingStatement(self, node: ast.BranchingStatement, context=None):
        context = context.copy()
        context["label"] = "branch"
        cond_lhs, op, cond_rhs = self.visit(node.condition, context=context)

        true_block, false_block = list(), list()
        for qasm_block, qubic_block in ((node.if_block, true_block),
                                        (node.else_block, false_block)):
            self._cur_block = qubic_block
            for instr in qasm_block:
                self.visit(instr, context=context)

        self._cur_block = self.program

        scope = set()
        for block in (true_block, false_block):
            scope.update(self._capture_scope(block))

        if scope:
            self._update_scope(cond_rhs, scope)

        instr = {'cond_lhs': cond_lhs, 'alu_cond': op,
                 'scope': list(self._vardecls[cond_rhs]['scope']),
                 'true': true_block,
                 'false': false_block}

        if cond_rhs in self._measurements:
            # condition is on a measurement result; the OpenQASM variable does
            # not matter per se: the measurement output is directly identified
            instr['name'] = 'branch_fproc'
            qubits = self._measurements[cond_rhs]
            assert len(qubits) == 1
            instr['func_id'] = qubits[0]+'.meas'
        else:
            # condition is on a variable that received its value through some
            # other means than a measurement
            instr['name'] = 'branch_var'
            instr['cond_rhs'] = cond_rhs

        self._cur_block.append(instr)

    def visit_ClassicalDeclaration(self, node: ast.ClassicalDeclaration, context=None):
        if isinstance(node.type, ast.BitType):
            if node.type.size is not None:
                array_size = self._eval_expression(node.type.size)
                for i in range(array_size):
                    self._declare_unscoped_var(f'{node.identifier.name}_{i}', 'int')
            else:
                self._declare_unscoped_var(node.identifier.name, 'int', node.init_expression)

            return

        elif isinstance(node.type, (ast.IntType, ast.UintType)):
            if node.type.size is not None:
                tsize = 8*self._eval_expression(node.type.size)
                if tsize != NATIVE_INT_SIZE:
                    warnings.warn(f'casting integer of size {tsize} to {NATIVE_INT_SIZE}')
            self._declare_unscoped_var(node.identifier.name, 'int', node.init_expression)

            return

        elif isinstance(node.type, ast.ArrayType):
            # unroll the array, declaring single variables for each element
            assert len(node.type.dimensions) == 1 and "only 1-dim arrays supported"
            for i in range(node.type.dimensions[0].value):
                self._declare_unscoped_var(f'{node.identifier.name}_{i}', 'int')

            return

        elif isinstance(node.type, ast.DurationType):
            duration = self._eval_expression(node.init_expression)
            # TODO: durations are assumed to be const; may not always be correct
            self.params[node.identifier.name] = duration

            return

        assert not node

    def visit_ConstantDeclaration(self, node: ast.ConstantDeclaration, context=None):
        self.params[node.identifier.name] = self._eval_expression(node.init_expression)

    def visit_DelayInstruction(self, node: ast.DelayInstruction, context=None):
        qubits = self._get_hardware_qubits(node.qubits)
        delay = self._eval_expression(node.duration, set(qubits))
        self._cur_block.append({'name': 'delay', 't': delay, 'qubit': qubits})

    def visit_FloatLiteral(self, node: ast.FloatLiteral, context=None):
        return self._eval_expression(node)

    def visit_ForInLoop(self, node: ast.ForInLoop, context=None):
        loopvar  = node.identifier.name
        loopdecl = node.set_declaration

        step = 1
        if node.set_declaration.step:
            step = node.set_declaration.step

        try:
            assert isinstance(node.type, ast.IntType) and "int is assumed"
            self._cur_block = list()
            self._declare_unscoped_var(loopvar, 'int', loopdecl.start)
            loopvardecl = self._cur_block
            self._cur_block = self.program

            try:
                self._cur_block = list()
                for instr in node.block:
                    self.visit(instr, context)
                body = self._cur_block
            finally:
                self._cur_block = self.program

            scope = self._capture_scope(body)
            if scope:
                self._update_scope(loopvar, scope)
            else:
                scope = None

            end = self._eval_expression(loopdecl.end, scope=scope)

            self._cur_block.extend(loopvardecl)
            self._cur_block.append(
                {'name': 'loop',
                 'cond_lhs': end, 'alu_cond': 'eq', 'cond_rhs': loopvar, 'scope': scope,
                 'body': body +\
                     [{'name': 'alu', 'lhs': step, 'op': 'add', 'rhs': loopvar, 'out': loopvar}]
                }
            )
        except FloatingPointComputation:
            # this happens if computations in the loop use floating point; if there
            # is a fixed number of iterations, we can still unroll the loop and possibly
            # do the computations at compile-time
            end = self._eval_expression(loopdecl.end)
            if type(end) is int:       # unroll loop to allow computations
                del self._vardecls[loopvar]
                del self.vars[loopvar]

                for i in range(self._eval_expression(loopdecl.start), end, step):
                    self.params[loopvar] = i
                    for instr in node.block:
                        self.visit(instr, context)
                del self.params[loopvar]
            else:
                raise

        return

    def visit_Identifier(self, node: ast.Identifier, context=None):
        return self.vars[node.name].var_names[0]

    def visit_IndexExpression(self, node: ast.IndexExpression, context=None):
        assert isinstance(node.index[0], ast.IntegerLiteral)
        assert len(node.index) == 1
        expr = self._eval_expression(node)
        if context and context.get("label", "") == "branch":
            # this is an evaluation of the truthiness of the expression; ideally, the
            # comparison would be against != 0, but that is not supported (yet), so
            # instead (since all values are binary), the comparison is == 1
            return 1, 'eq', expr
        return expr

    def visit_IntegerLiteral(self, node: ast.IntegerLiteral, context=None):
        return self._eval_expression(node)

    def visit_QubitDeclaration(self, node: ast.QubitDeclaration, context=None):
        if node.size is not None:
            self.qubits[node.qubit.name] = node.size.value
        else:
            self.qubits[node.qubit.name] = None

    def visit_QuantumGate(self, node: ast.QuantumGate, context=None):
        gatename = node.name.name

        params = list(self._eval_expression(a) for a in node.arguments)
        qubits = self._get_hardware_qubits(node.qubits, context)

        instr = self.gate_map.get_qubic_gateinstr(gatename, qubits, params, self.options)
        if instr:       # some gates are no-ops, e.g. I
            self._cur_block.extend(instr)

    def visit_QuantumGateDefinition(self, node: ast.QuantumGateDefinition, context=None):
        gatename = node.name.name
        labels = [q.name for q in node.qubits]

        instructions = list()
        for stmt in node.body:
            if isinstance(stmt, ast.QuantumGate):
                params = list(self._eval_expression(a) for a in stmt.arguments)
                qubits = [q.name for q in stmt.qubits]
                instr = self.gate_map.get_qubic_gateinstr(stmt.name.name, qubits, self.options)
                instructions.extend(instr)
            else:
                raise RuntimeError("unsupported statement: %s" % str(stmt))

        self.gate_map.add_gatedef(gatename, labels, instructions)

    def visit_QuantumMeasurement(self, node: ast.QuantumMeasurement, context=None):
        qubits = self._get_hardware_qubits([node.qubit], context)
        self._cur_block.append({'name': 'read', 'qubit': qubits[0]})

    def visit_QuantumMeasurementStatement(self, node: ast.QuantumMeasurement, context=None):
        qubits = self._get_hardware_qubits([node.measure.qubit], context)
        if node.target is not None:
            # Note: Qiskit requires a measurement to have a target, but it's
            # not needed per se for QubiC if the result goes unused, so let
            # it pass silently
            output = self._eval_variable(node.target)
            self._measurements[output] = qubits
            self._update_scope(output, set(qubits))
        return self.visit(node.measure, context=context)

    def visit_QuantumReset(self, node: ast.QuantumReset, context=None):
        hw_qubits = self._get_hardware_qubits([node.qubits], context)

        # add a fake instruction for bookkeeping if this is a computational reset
        if not self.program and not self._cur_block:
            self._cur_block.append({'name': '_reset', 'qubit': hw_qubits})

        for qubit in hw_qubits:
            self._bind_phase(qubit)         # pre-emptive; not needed in all cases
            self._cur_block.extend([
                {'name': 'read', 'qubit': qubit},
                {'name': 'branch_fproc', 'cond_lhs': 1, 'alu_cond': 'eq', 'func_id': f'{qubit}.meas', 'scope': [qubit],
                    'true': [
                        {'name': 'X90', 'qubit': [qubit]},
                        {'name': 'X90', 'qubit': [qubit]}],
                    'false': []}])


class OpenPulseQubiCVisitor(QASMQubiCVisitor):
    def __init__(self, externals: dict={}, **kwds):
        if not 'qubit_map' in kwds:
            kwds['qubit_map'] = OpenPulseQubitMap()
        if not 'gate_map' in kwds:
            kwds['gate_map'] = OpenPulseGateMap()
        if not 'options' in kwds:
            kwds['options'] = dict()

        super().__init__(**kwds)

        # classical functions, linkable with this program
        self.externals = externals

        self.qchip = None

    def visit(self, node: ast.QASMNode, context=None, qubits=None, qchip=None):
        if qchip is not None:
            self.qchip = qchip

        try:
            result = super().visit(node, context, qubits=qubits)
        except Exception as e:
            tb = None
            if not isinstance(e, QASMQubiCParserError) or os.getenv('DISTPROC_FULL_TRACEBACKS'):
                tb = sys.exc_info()[2]
            raise e.with_traceback(tb)

        if self.qchip and self.gate_map:    # may have custom gates
            try:
                self.qchip.gates.update(self.gate_map.custom_gates)
            except AttributeError:
                pass

        return result

    def visit_CalibrationDefinition(self, node: ast.CalibrationDefinition, context=None):
        qubits = self._get_hardware_qubits(node.qubits, context)
        name = qubits+node.name.name.upper()

        pulses = list()
        for stmt in node.body:
            expr = stmt.expression
            if isinstance(expr, ast.FunctionCall):
                if expr.name.name == 'play':
                    args = expr.arguments
                    dest = args[0].name
                    env  = args[1].name.name
                    args = tuple(self._eval_expression(a) for a in args[1].arguments)
                    pulse_kwds = self.externals[env](*args)

                    pulses.append(qbqc.GatePulse(dest=dest, freq=42, t0=2, **pulse_kwds))
            # phase, freq, dest, amp, t0=None, twidth=None, env=None, gate=None, chip=None
                else:
                    raise NotImplementedError(expr.name)
            else:
                raise NotImplementedError(str(stmt.expression))

        gate = qbqc.Gate(pulses, self.qchip, name)
        self.gate_map.add_custom_gate(name, gate)

        return node

    def visit_CalibrationGrammarDeclaration(self, node: ast.CalibrationGrammarDeclaration, context=None):
        assert(node.name == 'openpulse')

    def visit_CalibrationStatement(self, node: ast.CalibrationStatement, context=None):
        for node in node.body:
            self.visit(node, context=context)
        return node

    def visit_ClassicalDeclaration(self, node: ast.ClassicalDeclaration, context=None):
        if isinstance(node.type, ast.PortType):
            # TODO: at least verify validity
            return

        elif isinstance(node.type, ast.FrameType):
            # TODO: capture carrier frequency
            return

        elif isinstance(node, ast.ExternDeclaration):
            self.vars[node.name.name] = node
            return

        return super().visit_ClassicalDeclaration(node, context)

    def visit_Identifier(self, node: ast.Identifier, context=None):
        for c in (self.vars, self.qubits, self.externals):
            try:
                return c[node.name]
            except KeyError:
                pass

        raise RuntimeError("undeclared identifier: %s" % node.name)


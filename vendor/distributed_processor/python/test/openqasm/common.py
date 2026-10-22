import io

try:
    import openpulse
    import oqpy
    import qiskit as qk
    import qiskit.qasm3 as qasm3
    have_prerequisites = True
except ImportError:
    have_prerequisites = False

import qubitconfig.qchip as qbqc
import distproc.hwconfig as qbhwc
import distproc.compiler as qbcm
import distproc.assembler as qbam

try:
    import qubic.rfsoc.hwconfig as rfhwc
    from ..test.test_compiler import elementconfig_factory
    have_rfsoc = True
except ImportError:
    have_rfsoc = False

if have_prerequisites:
    import distproc.openqasm.visitor as oqv

import numpy as np


class QubiC_OpenQasmTest:
    def setup_class(cls):
        cls.fpga_config = qbhwc.FPGAConfig()
        cls.channel_config = qbhwc.load_channel_configs('channel_config.json')
        cls.qchip = qbqc.QChip('qubitcfg.json')

        cls.ignored_instr = ('bind_phase',
                             'branch_fproc',
                             'read')

    def _verify(self, original_qiskit, generated_qubic):
        c1 = original_qiskit.copy()
        c1.remove_final_measurements()

        c2 = qk.QuantumCircuit(c1.qubits)
        c2_regs = dict()
        for q in c1.qregs:
            reg = qk.QuantumRegister(q.size, q.name)
            c2_regs[q.name] = reg
            c2.add_register(reg)

        for instr in generated_qubic:
            opname = instr['name']
            if 'qubit' in instr:
                qubit = instr['qubit']
                if isinstance(qubit, str):
                    qubit = [qubit]

                if len(qubit) == 2:
                    control = c2_regs.get(qubit[0].lower(), int(qubit[0][1:]))
                    target  = c2_regs.get(qubit[1].lower(), int(qubit[1][1:]))
                elif len(qubit) != 1:
                    assert not len(qubit) and "no support for more than 2 qubits given"
                qubit = c2_regs.get(qubit[0].lower(), int(qubit[0][1:]))

            if opname == 'declare':
                reg = qk.ClassicalRegister(size=1, name=instr['var'])
                c2.add_register(reg)
                continue

            if opname == 'barrier':
                c2.barrier()
                continue

            if opname == 'delay':
                c2.delay(instr['t'], unit='s')
                continue

            if opname == 'virtual_z':
                c2.rz(instr['phase'], qubit)
                continue

            if opname == 'Y-90':
                c2.ry(-np.pi/2, qubit)
                continue

            if opname == 'X90':
                c2.rx(np.pi/2, qubit)
                continue

            if opname == 'CZ':
                c2.h(target)
                c2.cx(control, target)
                c2.h(target)
                continue

            if opname == 'CNOT':
                c2.cx(control, target)
                continue

            if opname in self.ignored_instr:
                continue

            assert not opname and '%s not implemented' % opname

        op_org = qk.quantum_info.Operator(c1)
        op_qubic = qk.quantum_info.Operator(c2)

        is_equivalent = op_org.equiv(op_qubic)
        assert is_equivalent

        return is_equivalent

    def _verify_reset(self, qubic_prog, options: dict={}):
        # first operation on the qubit should be a delay or a reset on all qubits; the
        # latter isn't an instruction, so check for a read
        for instr in qubic_prog:
            if instr['name'] == 'delay':
                delay = options.get('reset_delay', 500E-6)      # 500E-6 is the default
                assert instr['t'] == delay
                break

            if instr['name'] == 'read':
                break

            if 'qubit' in instr:
                assert not "no delay found in %s" % str(qubic_prog)
                break

    def _prep_program(self, nqubits: int=1):
        prog = oqpy.Program()
        prog.include("stdgates.inc")

        qubits = [oqpy.PhysicalQubits[q] for q in range(nqubits)]

        return prog, qubits

    def _circuit2qasm(self, qc: "qk.QuantumCircuit"):
        oqp = io.StringIO()
        qasm3.dump(qc, oqp)
        oqp.seek(0)

        return oqp.read()

    def _qasm2qubic(self, oqp: "str|oqpy.Program|qiskit.QuantumCircuit",
            externals: dict={}, qubits: list=[], options: dict={}, assemble=True):
        if isinstance(oqp, oqpy.Program):
            oqp = oqp.to_qasm()
        elif isinstance(oqp, qk.QuantumCircuit):
            oqp = self._circuit2qasm(oqp)

        tree = openpulse.parse(oqp)

        if not qubits:
            qubits = list(range(8))

        parser = oqv.OpenPulseQubiCVisitor(externals=externals, options=options)
        parser.visit(tree, qchip=self.qchip, qubits=qubits, context=None)

        if assemble:
            self._assemble_qubic(parser.program)

        # resets are auto-added as needed, so verify their presence
        self._verify_reset(parser.program, options)

        return parser.program

    def _assemble_qubic(self, program: str):
        passes = qbcm.get_passes(self.fpga_config, self.qchip)
        compiler = qbcm.Compiler(program)
        compiler.run_ir_passes(passes)
        compiled = compiler.compile()

        if have_rfsoc:
            asm = qbam.GlobalAssembler(compiled, self.channel_config, elementconfig_factory)
            assembled = asm.get_assembled_program()
        else:
            assembled = dict()

        return assembled

    def _verify2qubic(self, oqp: "str|oqpy.Program|qiskit.QuantumCircuit",
            externals: dict={}, qubits: list=[], options: dict={}, assemble=True):
        if isinstance(oqp, oqpy.Program):
            oqp = oqp.to_qasm()

        program = self._qasm2qubic(oqp, externals, qubits, options, assemble)

        if isinstance(oqp, str):
            oqp = qasm3.loads(oqp)

        self._verify(oqp, program)

        return program


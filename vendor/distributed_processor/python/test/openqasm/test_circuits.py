import copy
import numpy as np
import pytest
import warnings

from common import QubiC_OpenQasmTest, have_prerequisites

if not have_prerequisites:
    pytest.skip("prerequisites not met", allow_module_level=True)
else:
    import oqpy


class TestSTANDARD(QubiC_OpenQasmTest):
    """Test of OpenQASM3 standard gates from stdgates.inc"""

    options = {
        'barrier'     : 'none',
        'entangler'   : 'cz',
        'h_impgate'   : 'X90',
    }

    def test01_u3_operator(self):
        """Single qubit u3 operator"""

        prog, qubits = self._prep_program(1)

        for args in ((-0.28, 2.5, 3.88),):
            prog1 = copy.deepcopy(prog)
            prog1.gate(qubits[0], 'U', *args)

            self._verify2qubic(prog1, options=self.options)

    def test02_single_operators(self):
        """Single qubit operators"""

        prog, qubits = self._prep_program(1)

        for gate in ('id', 'x', 'y', 'z', 'h', 's', 't', 'tdg'):
            prog1 = copy.deepcopy(prog)
            prog1.gate(qubits[0], gate)

            # add a measurement to prevent id() and z() from failing as
            # a complete QubiC circuit in the assembly stage
            if gate in ('id', 'z'):
                creg = oqpy.BitVar()
                prog1.measure(qubits[0], creg)

            self._verify2qubic(prog1, self.options)

        # special case to check both implementations of H
        alt = self.options.copy()
        alt['h_impgate'] = 'Y-90'
        prog1 = copy.deepcopy(prog)
        prog1.gate(qubits[0], gate)

        self._verify2qubic(prog1, options=alt)

    def test03_single_rotations(self):
        """Single qubit rotations"""

        prog, qubits = self._prep_program(1)

        for gate in ('rx', 'ry', 'rz', 'p'):
            for phase in (np.pi, np.pi/2., np.pi/4., 1.234, 2800., -0.):
                prog1 = copy.deepcopy(prog)
                prog1.gate(qubits[0], gate, phase)

                # add a measurement to prevent singular rz from failing as
                # a complete QubiC circuit in the assembly stage
                if gate == 'rz':
                    creg = oqpy.BitVar()
                    prog1.measure(qubits[0], creg)

                self._verify2qubic(prog1, self.options)

    def test04_calibrated(self):
        """Calibrated gates should not be decomposed"""

        prog, qubits = self._prep_program(1)

        # a single X gate should be 2 X90s, with no virtual Zs
        prog.gate(qubits[0], 'x')

        asm = self._verify2qubic(prog, options=self.options)

        x90_count = 0
        for instr in asm:
            assert instr['name'] != 'virtual_z'
            x90_count += instr['name'] == 'X90' and 1 or 0
        assert x90_count == 2

    def test05_initialization(self):
        """Computational basis-state prep"""

        # QASM programs do not necessarily have an explicit reset, so the QubiC program must
        # have one added if not present (note that every generated QubiC program is verified
        # in the tests; the set here is just explicitly covering all cases

        # implicit reset
        prog, qubits = self._prep_program(1)
        prog.measure(qubits[0])

        for delay in (None, 50E-6, 500E-6):
            options = self.options.copy()
            if delay:
                options['reset_delay'] = delay
            else:
                delay = 500E-6    # default

            qprog = self._qasm2qubic(prog, options=options)

        # explicit reset
        prog, qubits = self._prep_program(1)
        prog.reset(qubits[0])
        prog.measure(qubits[0])
        qprog = self._qasm2qubic(prog, options=self.options)

        # partial reset, should warn
        prog, qubits = self._prep_program(2)
        prog.reset(qubits[0])
        prog.gate(qubits[1], 'rx', np.pi)
        prog.measure(qubits[0])
        prog.measure(qubits[1])
        with warnings.catch_warnings(record=True) as w:
            # TODO: assembling will result in warnings, too, so skip that step
            # to make sure we capture the intended warning
            qprog = self._qasm2qubic(prog, options=self.options, assemble=False)
            assert 'qubit Q1 was not reset' in str(w[-1].message)

        # heralding, requires a normal passive reset
        prog, qubits = self._prep_program(1)
        prog.measure(qubits[0])
        prog.gate(qubits[0], 'rx', np.pi)
        prog.measure(qubits[0])
        qprog = self._qasm2qubic(prog, options=self.options)
        assert qprog[0]['name'] == 'delay'

        # mid-circuit reset, requires a delay
        prog, qubits = self._prep_program(1)
        prog.gate(qubits[0], 'rx', np.pi)
        prog.reset(qubits[0])
        prog.measure(qubits[0])
        qprog = self._qasm2qubic(prog, options=self.options)

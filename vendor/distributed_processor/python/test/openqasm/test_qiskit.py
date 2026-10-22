import copy
import numpy as np
import pytest

from common import QubiC_OpenQasmTest, have_prerequisites

if not have_prerequisites:
   pytest.skip("prerequisites not met", allow_module_level=True)
else:
   import qiskit as qk


class TestQISKIT(QubiC_OpenQasmTest):
    """Test circuits from Qiskit tutorials and textbook"""

    # Note: in these tests, non-unitary circuits (with resets or other
    # branches) are only compiled and assembled to check for correctnes, not
    # reinstituted as a Qiskit operator for an equivalence check.

    options = {
        'barrier': 'none',
        'entangler' : 'cz',
        'h_impgate' : 'X90',
    }

    def test01_basic_u3(self):
        """Basic U3 circuit"""

        q = qk.QuantumRegister(1)
        qc = qk.QuantumCircuit(q)
        qc.u(np.pi/2, np.pi/4, np.pi/8, q)

        self._verify2qubic(qc, self.options)

    def test02_basic_sdg(self):
        """Basic sdg circuit"""

        # sdg() is a standard OpenQASM3 gate, but it's not yet supported by
        # the Qiskit QASM3 importer, even as Qiskit circuits support it

        q = qk.QuantumRegister(1)
        qc = qk.QuantumCircuit(q)
        qc.sdg(q)

        self._verify2qubic(qc, self.options)

    def test03_fast_reset(self):
        """Fast reset circuit"""

        q = qk.QuantumRegister(1)
        c = qk.ClassicalRegister(1)

        qc = qk.QuantumCircuit(q, c)
        qc.h(q)
        qc.reset(q[0])
        qc.measure(q, c)

        self._qasm2qubic(qc, self.options)

    def test04_basic_conditional(self):
        """Simple branching"""

        # the following program is the intended; however, Qiskit as of 06/06/24
        # generates incorrect QASM, so the actual QASM is used instead as a string
        q = qk.QuantumRegister(1)
        c = qk.ClassicalRegister(1)

        qc = qk.QuantumCircuit(q, c)
        qc.h(q)
        qc.measure(q,c)
        if qk.__version__[0] == '1':
            qc.x(q[0]).c_if(c, 0)
        else:
            with qc.if_test((c, 0)):
                qc.x(q[0])
        qc.measure(q, c)

        # Qiskit produces:
        from_qiskit = """
        OPENQASM 3.0;
        include "stdgates.inc";
        bit[1] c1;
        qubit[1] q3;
        h q3[0];
        c1[0] = measure q3[0];
        if (c1 == 0) {
          x q3[0];
        }
        c1[0] = measure q3[0];
        """

        # the following has the predicate corrected
        corrected_from_qiskit = """
        OPENQASM 3.0;
        include "stdgates.inc";
        bit[1] c1;
        qubit[1] q3;
        h q3[0];
        c1[0] = measure q3[0];
        if (c1[0] == 0) {
          x q3[0];
        }
        c1[0] = measure q3[0];
        """

        self._qasm2qubic(corrected_from_qiskit, options=self.options)

    def test05_teleportation(self):
        """Teleportation circuit"""

        q0 = qk.QuantumRegister(1, name='Q0')
        q1 = qk.QuantumRegister(1, name='Q1')
        q2 = qk.QuantumRegister(1, name='Q2')

        m0 = qk.ClassicalRegister(1, name='m0')
        m1 = qk.ClassicalRegister(1, name='m1')
        m2 = qk.ClassicalRegister(1, name='m2')

        qc = qk.QuantumCircuit(q0, q1, q2, m0, m1, m2)

        qc.u(0, 1, 2, q0)
        qc.h(q1)
        qc.cx(q1, q2)
        qc.cx(q0, q1)

        qc.measure(q1, m1)
        qc.measure(q0, m0)

        if qk.__version__[0] == '1':
            qc.x(q2).c_if(m1, 1)
            qc.z(q2).c_if(m0, 1)
        else:
            with qc.if_test((m1, 1)):
                qc.x(q2)
            with qc.if_test((m0, 1)):
                qc.z(q2)

        qc.measure(q2, m2)

        self._qasm2qubic(qc, options=self.options)

        # alternative, with arrays
        q = qk.QuantumRegister(3)
        m = qk.ClassicalRegister(3)

        qc = qk.QuantumCircuit(q, m)

        qc.u(0, 1, 2, q[0])
        qc.h(q[1])
        qc.cx(q[1], q[2])
        qc.cx(q[0], q[1])

        for i in [1,0]:
            qc.measure(q[i], m[i])

        if qk.__version__[0] == '1':
            qc.x(q[2]).c_if(m[1], 1)
            qc.z(q[2]).c_if(m[0], 1)
        else:
            with qc.if_test((m[1], 1)):
                qc.x(q[2])
            with qc.if_test((m[0], 1)):
                qc.z(q[2])

        qc.measure(q[2], m[2])

        self._qasm2qubic(qc, options=self.options)

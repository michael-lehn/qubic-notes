import copy
import numpy as np
import pytest

from common import QubiC_OpenQasmTest, have_prerequisites

if not have_prerequisites:
   pytest.skip("prerequisites not met", allow_module_level=True)


class TestDECLARATIONS(QubiC_OpenQasmTest):
    """Test range of declarations of classical and qubits"""

    options = {
        'barrier': 'none',
        'entangler' : 'cz',
        'h_impgate' : 'X90',
    }

    preamble = """
        OPENQASM 3.0;
        include "stdgates.inc";
    """

    def test01_simple_declarations(self):
        """Simple declarations of qubits and classical registers"""

        prog = self.preamble + """
        bit c0;
        qubit q2;
        c0 = measure q2;
        """

        self._verify2qubic(prog, options=self.options)

    def test02_array_of_one_declarations(self):
        """Array of one declarations of qubits and classical registers"""

        template = self.preamble + """
        bit{0};
        qubit{1};
        h {3};
        {2} = measure {3};
        """

        # arrays of 1 are transpiled as regular variables
        for regs in [(' c0',    '[1] q2', 'c0',    'q2[0]'),
                     ('[1] c0', ' q0',    'c0[0]', 'q0'),
                     ('[1] c0', '[1] q2', 'c0[0]', 'q2[0]'),
                    ]:
            self._verify2qubic(template.format(*regs), options=self.options)

    def test03_regular_array_declarations(self):
        """Array declarations of qubits and classical registers"""

        prog = self.preamble + """
        bit[2] c0;
        qubit[2] q2;
        h q2[0];
        h q2[1];
        c0[0] = measure q2[0];
        c0[1] = measure q2[1];
        """

        qubic_prog = self._verify2qubic(prog, options=self.options)

        # q2[0] and q2[1] should by default be translated into q0 and q1
        for instr in qubic_prog:
            try:
                qubits = instr['qubit']
                if isinstance(qubits, str):
                    qubits = [qubits]

                for q in qubits:
                    assert q in ['Q0', 'Q1']
            except KeyError:
                pass

    def test04_arrays_in_conditions(self):
        """Use of array variables in conditions"""

        template = self.preamble + """
        bit{0};
        qubit{1};
        h {3};
        {2} = measure {3};
        if ({2} == 1) {{ h {3}; }}
        if (1 == {2}) {{ h {3}; }}
        {2} = measure {3};
        """

        # arrays of 1 are transpiled as regular variables (note: for the
        # conditional, Qiskit requires the register to be an array, not
        # a single bit, so the latter case is skipped)
        for regs in [('[1] c0', ' q0',    'c0[0]', 'q0'),
                     ('[1] c0', '[1] q2', 'c0[0]', 'q2[0]'),
                    ]:
            # only translate/assemble ... don't know how to check programs
            # with branching against Qiskit yet
            self._qasm2qubic(template.format(*regs), options=self.options)

    def test05_custom_gate_definition(self):
        """Custom gate definition"""

        prog = self.preamble + """
        gate my_custom_gate a, b {
            h a;
            x b;
            cx a, b;
        }

        bit out;
        qubit[2] q;

        my_custom_gate q[1], q[0];
        out = measure q[1];
        """

        self._verify2qubic(prog, options=self.options)

    def _verify_durations(self, prog, verifier, scale=1):
        durations = [("1ns", 1E-9), ("50ns", 50E-9),
                     ("1us", 1E-6), ("50us", 50E-6),
                     ("1ms", 1E-3), ("50ms", 50E-3)]

        for d, td in durations:
            reset_found = False
            qprog = verifier(prog%d, options=self.options)

            for instr in qprog:
                if instr['name'] == 'delay':
                    if not reset_found:          # passive reset delay
                        reset_found = True
                    else:                        # programmatic delay
                        assert round(instr['t']-td*scale, 12) == 0
                        break
            else:
                assert "delay not found" and 0

    def test06_delays(self):
        """Declaration of delays"""

        prog = self.preamble + """
        qubit[1] q;
        bit c0;

        h q[0];
        delay[%s] q[0];
        x q[0];
        c0 = measure q[0];
        """

        self._verify_durations(prog, self._verify2qubic)

    def test07_delays(self):
        """Declarations of delays and durations"""

        prog_template = self.preamble + """
        %squbit[1] q;
        bit c0;

        h q[0];
        %s q[0];
        x q[0];
        c0 = measure q[0];
        """

        prog1 = prog_template % ("const duration d = %s;\n", "delay[d]")
        prog2 = prog_template % ("const duration d = %s;\n", "delay[d*3]")
        prog3 = prog_template % ("const duration d = %s;\nconst int q = 5;\n", "delay[d*q]")

        for prog, scale in ((prog1, 1.), (prog2, 3.), (prog3, 5.)):
            # qiskit doesn't support duration declarations
            self._verify_durations(prog, self._qasm2qubic, scale=scale)

    def test08_t1(self):
        """Use of delays for a T1 experiment"""

        prog = self.preamble + """
        const duration stride = 100ns;
        const int ndata = 10;

        qubit[1] q;
        bit c;

        for int i in [0:ndata] {
            reset q[0];
            x q[0];
            delay[i*stride] q[0];
            c = measure q[0];
        }
        """

        # Qiskit QASM3 does not support durations
        self._qasm2qubic(prog, options=self.options)

import pytest

from common import QubiC_OpenQasmTest, have_prerequisites

if not have_prerequisites:
   pytest.skip("prerequisites not met", allow_module_level=True)
else:
   import distproc.openqasm.visitor as oqv


class TestERRORS(QubiC_OpenQasmTest):
    """Test error handling"""

    options = {
        'barrier': 'none',
        'entangler' : 'cz',
        'h_impgate' : 'X90',
    }

    preamble = """\
        OPENQASM 3.0;
        include "stdgates.inc";
    """

    def test01_missing_declaration(self):
        """Missing declarations of variables and qubits"""

        prog = self.preamble + """
        bit c0;
        qubit q0;
        c0 = measure q0;
        """

        for rem, var, ex in [('qubit q0;\n', 'q0', oqv.UndeclaredQubit),
                             ('bit c0;\n',   'c0', oqv.UndeclaredVariable),]:
            try:
                prog1 = prog.replace(rem, '')
                self._qasm2qubic(prog1, options=self.options, assemble=False)
            except ex as e:
                assert var in str(e)        # missing declaration
                assert '5' in str(e)        # line number (the measurement)


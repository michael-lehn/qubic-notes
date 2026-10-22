import pytest

from common import QubiC_OpenQasmTest, have_prerequisites

if not have_prerequisites:
   pytest.skip("prerequisites not met", allow_module_level=True)


class TestMAPPING(QubiC_OpenQasmTest):
    """Test programmatic qubit to hardware qubit mappings"""

    options = {
        'barrier': 'none',
        'entangler' : 'cz',
        'h_impgate' : 'X90',
    }

    preamble = """
        OPENQASM 3.0;
        include "stdgates.inc";
    """

    def test01_simple_mapping(self):
        """Declaration is named hardware qubit mapping"""

        template = self.preamble + """
        bit c0;
        qubit {0};
        c0 = measure {0};
        """

        for qb in ['q0', 'Q0', 'q2', 'Q2']:
            prog = self._verify2qubic(template.format(qb), options=self.options)
            for line in prog:
                if 'qubit' in line:
                    assert qb.upper() == line['qubit']

    def test02_range_mapping(self):
        """Declaration is indexed into provided qubits"""

        template = self.preamble + """
        bit[3] c0;
        qubit[3] {0};
        c0[0] = measure {0}[0];
        c0[1] = measure {0}[1];
        c0[2] = measure {0}[2];
        """

        for qubits in [(0, 1, 2), (2, 3, 4), (7, 2, 5)]:
            for qb in ['q0', 'q2']:
                _qubits = ['Q%d' % q for q in qubits]
                _qubits.reverse()
                prog = self._verify2qubic(template.format(qb), qubits=qubits, options=self.options)
                for line in prog:
                    if line['name'] == 'read':
                        assert line['qubit'] == _qubits.pop()


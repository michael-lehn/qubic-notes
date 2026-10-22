import openpulse

from . import visitor
from .qubit_map import *
from .gate_map import *


def load_qasm(oqp: str,
              qchip: 'qubitconfig.QChip',
              qubit_map: QubitMap=None,
              gate_map: GateMap=None,
              options: dict=None):
    """Convert an OpenQASM3 program to a QubiC program

        Parameters
        ----------
            oqp: str
                QASM3 program string
            qchip: qubitconfig.QChip
                QubiC quantum chip configuration
            qubit_map: QubitMap
                mapping object from QASM labels to hardware qubits
            gate_map: GateMap
                mapping object from QASM labels to hardware gates
            options: dict
                global configuration to drive QASM generation:
                    'barrier': 'none',       # alts: "none" (default), "native", logical"
                    'entangler' : 'cz',      # atls: "cnot" (default), "cz"
                    'h_impgate' : 'X90'      # alts: "Y-90" (default), "X90"

        Returns
        -------
            Compilable QubiC program
    """

    nqubits = len(qchip.qubits)

    tree = openpulse.parse(oqp)

    kwds = dict()
    if qubit_map is not None:
        kwds['qubit_map'] = qubit_map
    if gate_map is not None:
        kwds['gate_map'] = gate_map
    if options is not None:
        kwds['options'] = options

    parser = visitor.OpenPulseQubiCVisitor(**kwds)
    parser.visit(tree, qchip=qchip, qubits=list(range(nqubits)), context=None)

    return parser.program

from abc import ABC, abstractmethod

__all__ = ['QubitMap',
           'DefaultQubitMap',
           'QASMQubitMap',
           'OpenPulseQubitMap',
          ]


class QubitMap(ABC):

    @abstractmethod
    def get_hardware_qubit(self, qubit_reg: str, index: int):
        pass


class DefaultQubitMap(QubitMap):
    """
    Default qubit map, should work for most programs. Rule:
        q[ind] --> Qind
    """

    def __init__(self):
        super().__init__()

    def get_hardware_qubit(self, qubit_reg: str, index: int = None):
        if index is not None:
            return qubit_reg.upper() + str(index)
        else:
            return qubit_reg.upper()


class QASMQubitMap(QubitMap):
    """
    QASM/OpenPulse qubit map, for implicitly declared qubits. Rule:
        ${q} -> Q{q}
    """

    def __init__(self):
        super().__init__()

    def get_hardware_qubit(self, qubit_reg: str, index: int = None):
        if index is None:
            # assume qubits are individually labeled
            if qubit_reg[0] == '$':    # implicit variable
                return 'Q'+qubit_reg[1:]
            return qubit_reg.upper()
        else:
            # assume there is a single qubit registry that maps linearly
            return 'Q'+str(index)

OpenPulseQubitMap = QASMQubitMap

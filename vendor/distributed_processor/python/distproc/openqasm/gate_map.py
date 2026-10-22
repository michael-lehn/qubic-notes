from abc import ABC, abstractmethod
import numpy as np

__all__ = ['GateMap',
           'DefaultGateMap',
           'QASMGateMap',
           'OpenPulseGateMap',
          ]


class GateMap(ABC):
    """
    Map gate names to QChip gates.
    """

    @abstractmethod
    def get_qubic_gateinstr(self, gatename: str,
            hw_qubits: list, params: list=None, options: dict={}) -> list:
        """
        Parameters
        ----------
            hw_qubits : list
                hardware-actual qubits to which the gate is applied
            params : list
                gate-specific parameters (e.g. a phase)
            options : dict
                gate-specific global configuration

        Returns
        -------
            List of QChip gates

        """

        pass


class DefaultGateMap(GateMap):
    """
    Map rotations and standard gates from OpenQASM3's stdgates.inc to QChip gates.
    """

    barrier = {'name': 'barrier'}

    def __init__(self):
        self.native_gates = ['X90', 'CNOT', 'Y-90', 'Z90', 'CZ']
        self.qasm_supported_gates = ['id', 'x', 'rx', 'y', 'ry', 'z', 'rz',
                                     'h', 'p', 's', 't',
                                     'cx', 'cz']
        self.gatedefs = dict()

    def add_gatedef(self, gatename: str, labels: list, instructions: list):
        """Add a QASM-defined gate.

        Parameters
        ----------
            gatename: str
                Name of the gate
            labels: list
                List of formal arguments (qubit labels)
            instructions: list[dict]
                List of QubiC instructions coded as dictionaries

        Returns
        -------
            None
        """

        if not instructions:
            raise ValueError("gate definition requires intstructions")

        if gatename in self.gatedefs:
            raise RuntimeError("gate definition %s already exists" % gatename)

        self.gatedefs[gatename] = (labels, instructions)

    def get_qubic_gateinstr(self, gatename: str,
            hw_qubits: list, params: list=None, options: dict={}) -> list:

        """Retrieve the QubiC instructions to executed the named gate.

        Parameters
        ----------
            gatename: str
                Name of the gate
            hw_qubits: list
                List of qubit labels to which the gate applies; expects only 1 label
            params: list
                Gate parameters (e.g. an angle for a rotation gate)
            options: dict
                Options such as barrier policy

        Returns
        -------
            list[dict]
                List of high-level QubiC instructions coded as dictionaries
        """

        if gatename == 'id':
            instr = []

        elif gatename == 'x':
            # implemented as 2 consecutive X90s
            instr = [{'name': 'X90', 'qubit': hw_qubits}, {'name': 'X90', 'qubit': hw_qubits}]

            # TODO: presumably, X90 is always available, so an optimization is possible
            # here, but the code should really have a way of checking. If not, then the
            # following decompistion is needed instead:
            #instr = self._decompose_U(hw_qubits, np.pi, -np.pi/2, np.pi/2, options)

        elif gatename == 'rx':
            assert len(params) == 1 and 'rotation angle expected'
            assert len(hw_qubits) == 1
            instr = self._decompose_U(hw_qubits, params[0], -np.pi/2, np.pi/2, options)

        elif gatename == 'y':
            instr = self._decompose_U(hw_qubits, np.pi, 0., 0., options)

        elif gatename == 'ry':
            assert len(params) == 1 and 'rotation angle expected'
            assert len(hw_qubits) == 1
            instr = self._decompose_U(hw_qubits, params[0], 0., 0., options)

        elif gatename == 'z':
            instr = self._decompose_z(hw_qubits, np.pi, options)

        elif gatename == 'rz':
            assert len(params) == 1 and 'rotation angle expected'
            instr = self._decompose_z(hw_qubits, params[0], options)

        elif gatename == 'h':
            instr = self._decompose_h(hw_qubits, options)

        elif gatename == 'p':
            assert len(params) == 1 and 'rotation angle expected'
            instr = self._decompose_U(hw_qubits, 0., 0., params[0], options)

        elif gatename == 's':
            instr = self._decompose_U(hw_qubits, 0., 0.,  np.pi/2, options)

        elif gatename == 'sdg':
            instr = self._decompose_U(hw_qubits, 0., 0., -np.pi/2, options)

        elif gatename == 't':
            instr = self._decompose_U(hw_qubits, 0., 0.,  np.pi/4, options)

        elif gatename == 'tdg':
            instr = self._decompose_U(hw_qubits, 0., 0., -np.pi/4, options)

        elif gatename =='U' or gatename == 'U3':
            assert len(params) == 3 and 'three rotation angles expected'
            instr = self._decompose_U(hw_qubits,
                params[0], params[1], params[2], options)
            # TODO: the strict QASM definition of U3 includes a global phase,
            # but Qiskit's definition does not (?)

        elif gatename =='U2':
            assert len(params) == 2 and 'two rotation angles expected'
            instr = self._decompose_U(hw_qubits,
                np.pi/2, params[0], params[1], options)
            # TODO: like above, strict definition of U2 includes a global phase

        elif gatename == 'U1':
            assert len(params) == 1 and 'rotation angle expected'
            instr = self._decompose_U(hw_qubits, 0., 0., params[0], options)

        elif gatename == 'cx':
            control, target = hw_qubits
            if options.get('entangler', 'cnot').lower() in ('cnot', 'cx'):
                instr = [{'name': 'CNOT', 'qubit': hw_qubits}]
            else:
                # decompose CNOT into CZ using Hadamards
                H = self._decompose_h([target], options)
                instr = H + [{'name': 'CZ', 'qubit': hw_qubits}] + H

                if options.get('barrier', 'none').lower() == 'native':
                    for index in (1, 3, 5, 7):
                        instr.insert(index, self.barrier)
                else:
                    # a local barrier is always required b/c the extra gate on the
                    # target qubit potentially changes the intended flow
                    instr.append({'name': 'barrier', 'qubit': hw_qubits})
        else:
            try:
                labels, instructions = self.gatedefs[gatename]
                qmap = {l:q for l, q in zip(labels, hw_qubits)}
                instr = list()
                for _i in instructions:
                    i = _i.copy()
                    try:
                        i['qubit'] = [qmap[q] for q in i['qubit']]
                    except KeyError:
                        pass
                    instr.append(i)

            except KeyError:
                instr = [{'name': gatename.upper(), 'qubit': hw_qubits}]

        if options.get('barrier', 'none').lower() != 'none':
            instr.append(self.barrier)

        return instr

    def _decompose_h(self, hw_qubits: list, options: dict) -> list:
        assert len(hw_qubits) == 1

        if options.get('h_impgate', 'Y-90').lower() == 'y-90':
            instr = [{'name': 'Y-90', 'qubit': hw_qubits},
                     {'name': 'virtual_z', 'phase': np.pi, 'qubit': hw_qubits}]
        else:      # X90 implementation
            instr = [{'name': 'X90', 'qubit': hw_qubits},
                     {'name': 'virtual_z', 'phase': np.pi/2, 'qubit': hw_qubits},
                     {'name': 'X90', 'qubit': hw_qubits}]

        if options.get('barrier', 'none').lower() == 'native':
            instr.insert(1, self.barrier)

        return instr

    def _decompose_z(self, hw_qubits: list, phase: float, options: dict) -> list:
        return [{'name': 'virtual_z', 'phase': phase, 'qubit': hw_qubits}]

    def _decompose_U(self, hw_qubits: list, t: float, p: float, l: float, options: dict) -> list:
        """Decompose a U3 gate into X90 and virtual Z gates.

        Parameters
        ----------
             hw_qubits: list
                 List of qubit labels to which the gate applies; expects only 1 label
             t: float
                 Euler theta angle in radians
             p: float
                 Euler phi angle in radians
             l: float
                 Euler lambda angle in radians

        Returns
        -------
             list[dict]
                 List of high-level QubiC instructions coded as dictionaries

        Full definition ('U3' is deprecated in favor or 'U'):
            https://docs.quantum.ibm.com/api/qiskit/qiskit.circuit.library.U3Gate

        ZXZXZ decomposition:
            https://arxiv.org/abs/1612.00858
        """

        # special cases of X90 and Y-90 native gates
        if t == np.pi/2 and p == -np.pi/2 and l == np.pi/2:
            return [{'name': 'X90', 'qubit': hw_qubits}]

        elif t == -np.pi/2 and p == 0. and l == 0.:
            return [{'name': 'Y-90', 'qubit': hw_qubits}]

        instr = [{'name': 'virtual_z', 'phase': p,         'qubit': hw_qubits},
                 {'name': 'X90', 'qubit': hw_qubits},
                 {'name': 'virtual_z', 'phase': np.pi - t, 'qubit': hw_qubits},
                 {'name': 'X90', 'qubit': hw_qubits},
                 {'name': 'virtual_z', 'phase': l - np.pi, 'qubit': hw_qubits}]

        instr.reverse()      # operator order to gate order

        if options.get('barrier', 'none').lower() == 'native':
            for index in (1, 3, 5, 7):
                instr.insert(index, self.barrier)

        return instr

QASMGateMap = DefaultGateMap


class OpenPulseGateMap(QASMGateMap):
    """
    Map arbitrary OpenPulse definitions to QChip gates.
    """

    def __init__(self):
        super().__init__()

        self.custom_gates = dict()

    def get_qubic_gateinstr(self, gatename: str,
            hw_qubits: list, params: list=None, options: dict={}) -> list:

        if gatename in self.custom_gates:
            instr = [copy.copy(self.custom_gates[gatename])]

            if options.get('barrier', 'none') != 'none':
                instr.append(self.barrier)

            return instr

        return super().get_qubic_gateinstr(gatename, hw_qubits, params, options)


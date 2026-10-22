Gate instructions are used to represent native quantum gates.

JSON format:

    {'name': 'X90', 'qubit': 'Q0'}

Python format:

    Gate(name='X90', qubit='Q0')

Gate instructions are NOT directly compilable to distributed processor assembly, and must be resolved into a list of Pulse and/or Virtual-Z instructions. Currently, the only supported method for resolving gates is the [ResolveGates](../api/ir_passes.md#distproc.ir.passes.ResolveGates) pass, which uses QubiC's native calibration management system ([qubitconfig](https://gitlab.com/LBL-QubiC/experiments/qubitconfig)) to retrieve calibrated gate parameters and turn these into pulse sequences. However, any user-provided pass that can perform this conversion can be used.

Gate instructions support both single and two-qubit gates (with the latter accepting a list of qubits). A `modi` field is also supported for locally modifying pulse parameters; for example:

    {'name': 'X90', 'qubit': 'Q0', 'modi': {(0, 'amp'): 0.3}}

would change the amplitude of the first pulse in this gate to `0.3`. In general, the `modi` field takes a dictionary keyed by a tuple pointing to the parameter(s) to be modified. These changes are *local* in the sense that they are only applied to that particular instance of the gate.

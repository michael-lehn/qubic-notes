Several instruction types, such as variable declarations, conditional branching, and ALU operations have a `scope` argument. This is used to track which physical channel output(s) that instruction could ultimately affect. That, in turn, will determine which processor core(s) the instruction will ultimately target when it is compiled down to distributed processor assembly. 

For example, consider the following snippet:

    {'name': 'declare', 'var': 'my_phase', 'scope': ['Q0.qdrv', 'Q1.qdrv']},

    {'name': 'set_var', 'var': 'my_phase', 'value': 0, scope: ['Q0.qdrv', 'Q1.qdrv']},

    {'name': 'pulse', 'phase': 'my_phase', 'freq': 4944383311, 'amp': 0.3347, 
     'twidth': 2.4e-08, 
     'env': {'env_func': 'cos_edge_square', 
             'paradict': {'ramp_fraction': 0.25}},
     'dest': 'Q0.qdrv'}, 

    {'name': 'pulse', 'phase': 'my_phase', 'freq': 4944383311, 'amp': 0.3347, 
     'twidth': 2.4e-08, 
     'env': {'env_func': 'cos_edge_square', 
             'paradict': {'ramp_fraction': 0.25}},
     'dest': 'Q1.qdrv'}, 

Here, we have a single variable `'my_phase'` parameterizing the phase of two output pulses on two different output channels, `'Q0.qdrv'` and `'Q1.qdrv'`. The scope of the `declare` and `set_var` instructions needs to include these channels.

## Scoping by Qubit

As a convenient shorthand, instructions can also be scoped to qubits, rather than output channels directly (so in the above example, we could scope the `declare` and `set_var` instructions to `['Q0', 'Q1']` instead). Resolving the provided qubit into a list of channels is handled by the [QubitScoper](../api/ir.md#distproc.ir.ir.QubitScoper) class, which assumes that the qubit --> channel mapping can be provided using a tuple of format strings (for example, `('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')`), or explicitly as a dictionary (`{'Q0': ('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'), ...}`). The actual qubit --> channel resolution is applied to the program during the [ScopeProgram](../api/ir_passes.md#distproc.ir.ir.CoreScoper) pass.

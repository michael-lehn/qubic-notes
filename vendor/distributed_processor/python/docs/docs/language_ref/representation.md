Programs can be represented in one of two ways:

1. JSON strings (or lists/dictionaries in python):

        [
          {'name': 'declare', 'var': 'q2_phase', 'dtype': 'phase', 'scope': ['Q2.qdrv']},
          {'name': 'set_var', 'var': 'q2_phase', 'value': 0},
        
          {'name': 'delay', 't': 500.e-6}, 
          
          {'name': 'pulse', 'phase': 'q2_phase', 'freq': 4944383311, 'amp': 0.3347, 
           'twidth': 2.4e-08, 
           'env': {'env_func': 'cos_edge_square', 
                   'paradict': {'ramp_fraction': 0.25}},
           'dest': 'Q2.qdrv'}, 
        
          {'name': 'alu', 'lhs': 3.1415926, 'op': 'add', 
           'rhs': 'q2_phase', 'out': 'q2_phase'},
        
          {'name': 'pulse', 'phase': 'q2_phase', 'freq': 4944383311, 'amp': 0.3347, 
           'twidth': 2.4e-08, 
           'env': {'env_func': 'cos_edge_square', 
                   'paradict': {'ramp_fraction': 0.25}},
           'dest': 'Q2.qdrv'}
        ]

2. List of python instruction classes (found in `distproc.ir.instructions`):

        [
          Declare(scope=['Q2.qdrv'], var='q2_phase', dtype='phase'),
          SetVar(value=0, var='q2_phase', scope=None),
        
          Delay(t=0.0005, name='delay', qubit=None, scope=None),
        
          Pulse(freq=4944383311, twidth=2.4e-08, phase='q2_phase', 
                env={'env_func': 'cos_edge_square', 
                     'paradict': {'ramp_fraction': 0.25}}, 
                dest='Q2.qdrv', amp=0.3347)
        
          Alu(op='add', lhs=3.1415926, rhs='q2_phase', out='q2_phase', 
              scope=None, name='alu'),
        
          Pulse(freq=4944383311, twidth=2.4e-08, phase='q2_phase', 
                env={'env_func': 'cos_edge_square', 
                     'paradict': {'ramp_fraction': 0.25}}, 
                dest='Q2.qdrv', amp=0.3347)
        ]

When a program is passed to the compiler (thus instantiated into an [IRProgram](../api/ir.md#distproc.ir.ir.IRProgram) object) and transformed by compiler passes, metadata may be generated. To store this metadata together with the transformed program, the following JSON representation is also supported (which in this case was generated using [IRProgram.serialize()](../api/ir.md#distproc.ir.ir.IRProgram.serialize)):
        
    {
        "program": {
            "block_0": [

                {"name": "declare", "var": "q2_phase", "scope": ["Q2.qdrv"], 
                 "dtype": "phase"},

                {"name": "set_var", "var": "q2_phase", "value": 0,
                 "scope": ["Q2.qdrv"]},

                {"name": "delay", "t": 0.0005},

                {"name": "pulse", "freq": 4944383311, "twidth": 2.4e-08, 
                 "dest": "Q2.qdrv", "phase": "q2_phase", "amp": 0.3347,
                 'env': {'env_func': 'cos_edge_square', 
                         'paradict': {'ramp_fraction': 0.25}}},

                {"name": "alu", "lhs": 3.1415926, "rhs": "q2_phase",
                 "op": "add", "out": "q2_phase", "scope": ["Q2.qdrv"]},

                {"name": "pulse", "freq": 4944383311, "twidth": 2.4e-08, 
                 "dest": "Q2.qdrv", "phase": "q2_phase", "amp": 0.3347,
                 'env': {'env_func': 'cos_edge_square', 
                         'paradict': {'ramp_fraction': 0.25}}},
            ]
        },
        "vars": {
            "q2_phase": {
                "scope": [
                    "Q2.qdrv"
                ],
                "dtype": "phase"
            }
        },
        "freqs": {
            "4944383311": 4944383311
        },
        "control_flow_graph": {
            "block_0": []
        }
    }
        

In the above example, the program code is stored in the `program` field and split into basic blocks. In this example, control flow is linear so there is only a single basic block (`block_0`) and the control flow graph has a single node.

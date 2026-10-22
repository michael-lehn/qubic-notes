## High-level Control Flow

### The `BranchVar` Instruction

Conditional execution of code blocks can be performed using the `BranchVar` instruction:

JSON Format:

    {'name': 'branch_var', 'cond_lhs': 10, 'alu_cond': 'eq', 'cond_rhs': 'my_var', 
        'scope': ['Q0'],
        'true': [
                {'name': 'X90', 'qubit': ['Q0']}
            ],
        'false': []
    }

Python Format:

    BranchVar(cond_lhs=10, alu_cond='eq', cond_rhs='my_var', scope=['Q0'],
        true=[{'name': 'X90', 'qubit': ['Q0']}],
        false=[])

This instruction is essentially an "if/else" code block; with the instructions in the `true` (`false`) block being executed if the condition evaluates to True (False).

The fields are as follows:

  - `cond_lhs`: LHS input to ALU; can be either an immediate or a variable
  - `cond_rhs`: RHS input to ALU, must be a variable
  - `alu_cond`: conditional to be evaluated. Supported operations are:
    - `'ge'`: `lhs` > `rhs`
    - `'le'`: `lhs` < `rhs`
    - `'eq'`: `lhs` == `rhs`
  - `true`: code block to execute if the above conditional evaluates to True
  - `false`: code block to execute if the above conditional evaluates to False
  - `scope`: Instruction [scope](scope.md)

Note that the `true` and `false` code blocks are arbitrary and can include nested control flow.

### The `Loop` Instruction

JSON Format:
    
    {'name': 'loop', 'cond_lhs': 10, 'alu_cond': 'ge', 'cond_rhs': 'loop_ind'
        'scope': ['Q0'],
        'body': [
                {'name': 'X90', 'qubit': ['Q0']},
                {'name': 'alu', 'lhs': 1, 'op': 'add', 'loop_ind': 'loop_ind', 'out': 'loop_ind'}
            ]
    }

Python Format:
    
    Loop(cond_lhs=10, alu_cond='ge', cond_rhs='loop_ind', 'scope'=['Q0'],
        body=[
            Gate(name='X90', qubit=['Q0']),
            Alu(lhs=1, op='add', rhs='loop_ind', out='loop_ind')])

This instruction implements a `while` loop -- the code block in `body` is executed while the conditional is True. Note that in the above example, the variable `loop_ind` would need to be declared and initialized prior to the loop.

The fields are as follows:

  - `cond_lhs`: LHS input to ALU; can be either an immediate or a variable
  - `cond_rhs`: RHS input to ALU, must be a variable
  - `alu_cond`: conditional to be evaluated. Supported operations are:
    - `'ge'`: `lhs` > `rhs`
    - `'le'`: `lhs` < `rhs`
    - `'eq'`: `lhs` == `rhs`
  - `body`: code block to execute while the above conditional evaluates to True
  - `scope`: Instruction [scope](scope.md)

## Low-level Control Flow

The above high-level control flow instructions are resolved into more primitive `JumpCond` and `JumpI` type instructions during the [FlattenControlFlow](../api/ir_passes.md#distproc.ir.passes.FlattenProgram) pass. For more details on how the control flow graph (CFG) of a program is generated, and how pulses are scheduled around control flow, see the section on [global scheduling](timing_control.md#global-scheduling).

### The `JumpCond` Instruction

JSON Format:

    {'name': 'jump_cond', 'cond_lhs': 10, 'alu_cond': 'eq', 'cond_rhs': 'my_var', 
        'scope': ['Q0'], 'jump_label': 'my_var_jump_0'}

Python Format:

    JumpCond(cond_lhs=10, alu_cond='eq', cond_rhs='my_var', 
              scope=['Q0'], jump_label='my_var_jump_0')

The fields are as follows:

  - `cond_lhs`: LHS input to ALU; can be either an immediate or a variable
  - `cond_rhs`: RHS input to ALU, must be a variable
  - `alu_cond`: conditional to be evaluated. Supported operations are:
    - `'ge'`: `lhs` > `rhs`
    - `'le'`: `lhs` < `rhs`
    - `'eq'`: `lhs` == `rhs`
  - `jump_label`: string marking the location to jump to if the condition evaluates to True
  - `scope`: Instruction [scope](scope.md)

### The `JumpI` Instruction

This is an unconditional jump.

    {'name': 'jump_i', 'scope': ['Q0'], 'jump_label': 'my_var_jump_0'}

Python Format:

    JumpCond(scope=['Q0'], jump_label='my_var_jump_0')

The fields are as follows:

  - `jump_label`: string marking the location to jump to
  - `scope`: Instruction [scope](scope.md)

### The `JumpLabel` Instruction

The `JumpLabel` instruction is used to mark destination locations of `JumpCond` and `JumpI` instructions.

JSON Format:

    {'name': 'jump_label', 'label': 'my_var_jump_0', 'scope': ['Q0']}

Python Format:

    Python(label='my_var_jump_0', scope=['Q0'])

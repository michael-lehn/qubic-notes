Function processor (FPROC) instructions are used to request/receive measurement results (or other data) over the FPROC interface. A subset of these instructions extend normal ALU and branching instructions, replacing the RHS ALU input with the result from the function processor.

## The `func_id` Field

The `func_id` field is found in all FPROC instructions; it is used to specify the particular result to request from the FPROC module (for example, 'Q0.meas' might request the most recent measurement from qubit 0). The `func_id` can be given directly as an integer, or be a named value that is resolved by the [FPROCChannel](../api/hwconfig.md#distproc.hwconfig.FPROCChannel) config object. The available result types (and resulting mapping to `func_id`) is gateware specific; for the standard QubiC 2.0 gateware, the default `FPROCChannel` configuration object should suffice.

## The `ReadFproc` Instruction

The `ReadFproc` instruction will request a measurement result/data from the function processor interface (given by the `func_id` parameter), and write it to a [variable](variables.md) (given by `var`). This instruction resolves to a special case of the `AluFproc` instruction during conversion to assembly.

JSON Format:
    
    {'name': 'read_fproc', 'func_id': 'Q0.meas', 'var': 'q0_result}

Python Format:
    
    ReadFproc(func_id='Q0.meas', var='q0_result')

## The `AluFproc` Instruction

The `AluFproc` instruction will request a measurement result/data from the function processor interface, and use it to perform an ALU operation (replacing the RHS input). This is an extension of the normal [Alu](variables.md/#alu-operations) instruction.

JSON Format:

    {'name': 'alu_fproc', 'lhs': 'my_var', 'op': 'add', 'func_id': 'Q0.meas', 'out': 'my_var'} //add FPROC result to 'my_var'

Python Format:

    Alu(lhs='my_var', op='add', rhs='func_id', out='my_var')

## Control Flow: `BranchFproc` and `JumpFproc`

These instructions extend the normal [BranchVar](control_flow.md/#the-branchvar-instruction) and [JumpCond](control_flow.md/#the-jumpcond-instruction) instructions.

### `BranchFproc`
    
JSON Format:

    {'name': 'branch_fproc', 'cond_lhs': 10, 'alu_cond': 'eq', 'func_id': 'Q0.meas', 
        'scope': ['Q0'],
        'true': [
                {'name': 'X90', 'qubit': ['Q0']}
            ],
        'false': []
    }

Python Format:

    BranchFproc(cond_lhs=10, alu_cond='eq', func_id='Q0.meas', scope=['Q0'],
        true=[{'name': 'X90', 'qubit': ['Q0']}],
        false=[])

### `JumpFproc`


JSON Format:

    {'name': 'jump_fproc', 'cond_lhs': 10, 'alu_cond': 'eq', 'func_id': 'Q0.meas', 
        'scope': ['Q0'], 'jump_label': 'my_var_jump_0'}

Python Format:

    JumpFproc(cond_lhs=10, alu_cond='eq', func_id='Q0.meas', 
              scope=['Q0'], jump_label='my_var_jump_0')

## Timing Properties

All FPROC instructions halt core execution until the requested result is received over the interface. In the case of measurement results, it is assumed that the most recent previous measurement is the one that should be retrieved. In some cases, this may require delaying the execution of the FPROC instruction; that is, halting the core _before_ executing the FPROC instruction to give the measurement enough time to come in. This is specified in the `FPROCChannel` config using the `hold_after_chans` and `hold_nclks` parameters, which are set for each named FPROC channel. These parameters indicate that any FPROC instruction requesting from that channel must be executed at least `hold_nclks` clock cycles after the most recent pulse on the set of channels given by `hold_after_chans`. 

These timing constraints are resolved during the [Schedule](../api/ir_passes.md/#distproc.ir.passes.Schedule) pass by inserting the appropriate `Idle` instructions.

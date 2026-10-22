# The QubiC Scheduler

Scheduling is the process of assigning timestamps to all timing-controlled instructions, such as control and measurement pulses. Timestamps are provided in units of FPGA clock cycles (which can be found in the [`FPGAConfig`](../api/hwconfig.md/#distproc.hwconfig.FPGAConfig) object) and are referenced to an internal counter, which is reset at the beginning of program execution. Below, we explain the two types of scheduling: 1) local, which assigns timestamps to individual instructions *within* a basic block (region with linear control flow); and 2) global, which schedules basic blocks relative to the initial program start. 

## Basic (Local) Scheduling

Local scheduling assigns timestamps to individual timing-controlled instructions within a basic block (region without control flow). Local scheduling can be performed directly by the user, where pulse timestamps are provided in the input program (and specified relative to the start of each basic block), or can be performed by the QubiC scheduler, and modified according to timing control instructions. 

By default, the QubiC scheduler plays pulses on each channel as soon as that channel becomes available. For example, a list of pulses on the same channel are played *sequentially*, while pulses on separate channels are played *in parallel*. Consider the program below:

    circuit = [
        # play two pulses on the Q0 drive channel
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.3, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv'}, 
        
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv'},
        
        # add a single pulse on Q1 drive -
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q1.qdrv'}
        
    ]

The local scheduling pass will assign the following timestamps (assuming a 2 ns FPGA clock period): 

    circuit = [
        # play two pulses on the Q0 drive channel
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.3, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv', 'start_time': 0}, 
        
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv', 'start_time': 12},
        
        # add a single pulse on Q1 drive -- this will be scheduled immediately, and played in parallel with the first Q0 pulse
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q1.qdrv', 'start_time': 0}
        
    ]

The QubiC scheduler will also consider the execution time of non-timed instructions (such as `Alu` and `JumpI`) when scheduling, delaying subsequent pulses if necessary. If a programmer is providing timestamps directly, it is their responsibility to ensure that pulses aren't scheduled during the execution of another instruction, as doing so will cause the processor core to halt. Instruction execution times can be found in the [`FPGAConfig`](../api/hwconfig.md/#distproc.hwconfig.FPGAConfig) object; a [linter](../api/ir_passes.md#distproc.ir.passes.LintSchedule) pass is also provided to ensure that your scheduled program meets timing constraints (it is turned on by default if the `schedule` compiler flag is set to `False`).

The behavior of the scheduler can be modified by timing control instructions:

### The `Delay` Instruction

This instruction will delay all pulses on the specified channel(s) (or globally if no channels are specified) by the provided time (in seconds).

JSON Format:
    
    {'name': 'delay', 't': 20.e-9, 'scope': ['Q0.qdrv']}

Python Format:

    Delay(t=20.e-9, scope=['Q0.qdrv'])

Fields:

   - `t`: delay time in seconds
   - `scope`: list of channels to apply delay to (optional)
   - `qubit`: alternative to scope; can be used to specify channel set according to [qubit](scope.md#scoping-by-qubit)

### The `Barrier` Instruction

This instruction will place a scheduling barrier; all pulses after the barrier instruction will play *after* all pulses before the barrier have completed. As with the `Delay` instruction, `Barrier` can be scoped to specific channels or applied globally.

JSON Format:
    
    {'name': 'barrier', 'scope': ['Q0.qdrv', 'Q1.qdrv']}

Python Format:

    Barrier(scope=['Q0.qdrv'])

Fields:

  - `scope`: list of channels to apply barrier to (optional)
  - `qubit`: alternative to scope; can be used to specify channel set according to [qubit](scope.md#scoping-by-qubit)

Going back to our previous example, adding a barrier after the second instruction:

    circuit = [
        # play two pulses on the Q0 drive channel
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.3, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv'}, 
        
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv'},

        {'name': 'barrier'},
        
        # add a single pulse on Q1 drive -
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q1.qdrv'}
        
    ]

will result in the following scheduling output, where the pulse on `Q1.qdrv` plays *after* both pulses on `Q0.qdrv`:

    circuit = [
        # play two pulses on the Q0 drive channel
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.3, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv', 'start_time': 0}, 
        
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q0.qdrv', 'start_time': 12},
        
        # add a single pulse on Q1 drive -- this will be scheduled immediately, and played in parallel with the first Q0 pulse
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.6, 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}},
         'dest': 'Q1.qdrv', 'start_time': 24}
        
    ]

### The `Idle` Instruction

This instruction will halt the core execution until the specified timestamp. While the previous two instructions are only used by the scheduler in software (and are removed before final compilation), the `Idle` instruction executes directly on hardware. Its primary use is to halt the core before a `ReadFproc` or `JumpFproc` instruction in order to make sure the FFPROC result is read only after it is ready.

JSON Format:
    
    {'name': 'idle', 'end_time': 500, 'scope': ['Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo']}

Python Format:

    Idle(end_time=500, scope=['Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'])

## Global Scheduling

Global scheduling schedules basic blocks relative to the start of the program by analyzing their sequential dependencies according to the control flow graph (CFG) of the program.

### Basic Blocks

A basic block is a region of the program with linear control flow (e.g. it contains no segments with branching, jumping, or looping). Basic blocks are inferred by the compiler, but they can also be declared explicitly using the `Block` instruction. This can be useful for scheduling purposes. Consider the following program:

    [
        {'name': 'X90', 'qubit': 'Q1'},
        {'name': 'read', 'qubit': 'Q0'}, 
        {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas', 'scope': ['Q0', 'Q2'], 
         'true': [
             {'name': 'X90', 'qubit':'Q0'}
             ], 
         'false': [
             {'name': 'X90', 'qubit':'Q2'}
             ]},
        {'name': 'X90', 'qubit': 'Q2'},
        {'name': 'X90', 'qubit': 'Q1'}

    ]

This will get split up into the following basic blocks: 

    block_0:
        {'name': 'X90', 'qubit': 'Q1'},
        {'name': 'read', 'qubit': 'Q0'}, 
        
    block_0_ctrl:
        {'name': 'jump_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas', 'scope': ['Q0', 'Q2'], 'jump_label': 'true_0'}

    true_0:
        {'name': 'X90', 'qubit':'Q0'},
        {'name': 'jump_i', 'jump_label': 'end_0', 'scope': ['Q0', 'Q2']}

    false_0:
        {'name': 'X90', 'qubit':'Q2'},
        {'name': 'jump_i', 'jump_label': 'end_0', 'scope': ['Q0', 'Q2']}

    end_0:
        {'name': 'X90', 'qubit': 'Q2'},
        {'name': 'X90', 'qubit': 'Q1'}

Note that the `BranchFproc` instruction has been converted into a `JumpFproc`. The corresponding control flow graph is:
    
        block_0
           |
           v
      block_0_ctrl
          / \
         /   \
        /     \
       |       |
       v       v
    true_0   false_0
        \     /
         \   /
          \ /
           |
           v
         end_0

Assuming 10 clock-cycle `X90` gates, 500 clock-cycle reads, and 5 clock-cycle jumps, we might assign the following start timestamps to our basic blocks:

          block_0: 0
             |
             v
        block_0_ctrl: 510
            / \
           /   \
          /     \
         /       \
        |         |
        v         v
    true_0: 515   false_0: 515
         \       /
          \     /
           \   /
            \ /
             |
             v
           end_0: 530

### The `Hold` Instruction

As explained in the [function processor](function_processor.md#timing-properties) page, sometimes core execution needs to be halted before `Fproc` type instructions to ensure that the FPROC result is only read after it is available. These timing constraints are specified using the `Hold` instruction:

JSON Format:

    {'name': 'hold', 'n_clks': 64, 'ref_chans': ['Q0.rdlo'], 'scope': ['Q1.qdrv']}

Python Format

    Hold(n_clks=64, ref_chans=['Q0.rdlo'], scope=['Q1.qdrv'])


Fields:

  - `nclks`: number of clock cycles after the last pulse on any channel in `ref_chans` for which execution will be halted
  - `ref_chans`: list of channels to reference when halting execution
  - `scope`: list of channels to apply delay to 
  - `qubit`: alternative to scope; can be used to specify channel set according to [qubit](scope.md#scoping-by-qubit)

The example instruction above indicates that the core scoped to `Q1.qdrv` should halt its execution for 64 clock cycles after the most recent pulse on `Q0.rdlo`.

In most circumstances, users do not have to worry about applying or resolving this instruction. If it's necessary for a particular named FPROC channel, the [entry](../api/hwconfig.md#distproc.hwconfig.md.FPROCChannel) for that channel in the [`FPGAConfig`](../api/hwconfig.md/#distproc.hwconfig.FPGAConfig) should specify a `hold_nclks` and `ref_chans` attribute, which will tell the compiler to add a `Hold` instruction before that FPROC read. `Hold` instructions are resolved into `Idle` during scheduling.

NOTE: For programs with user-provided local schedules, the compiler will handle appropriate resolution of `Hold` instructions and scheduling of `Idle`. However, if there is a `ReadFproc` instruction within a basic block, care must be taken to ensure that the pulse schedule provides enough time for the `Hold` timing constraint to be satisfied. The [linter](../api/ir_passes.md#distproc.ir.passes.LintSchedule) pass should catch this.

### The `Block` Instruction: User-defined Basic Blocks

Users can explicitly define basic blocks to modify the scheduling behavior of the program using the `Block` instruction.

JSON Format:

    {'name': 'block', 'body': [<instructions here>], 'scope': ['Q0.qdrv']}

Python Format:

    Block(body=[<instructions>], scope=['Q0.qdrv'])

For programs without control flow, blocks follow the same global scheduling rule as pulses, depending on the channel(s) they are scoped to. Consider the following program:

    [
        Block(body=[
                Gate(name='X90', qubit='Q0'),
                Gate(name='X90', qubit='Q1')
            ], 
            scope=['Q0', 'Q1'])
        Block(body=[
                Gate(name='X90', qubit='Q2')
            ], 
            scope=['Q2'])
            
    ]

Here, the scheduler will start both blocks at `t = 0`, since they have disjoint scope. Pulse scheduling within each block will follow the usual local scheduling rules as outlined above.

However, if we add a gate on `Q0` to the second block:

    [
        Block(body=[
                Gate(name='X90', qubit='Q0'),
                Gate(name='X90', qubit='Q1')
            ], 
            scope=['Q0', 'Q1'])
        Block(body=[
                Gate(name='X90', qubit='Q2')
                Gate(name='X90', qubit='Q0')
            ], 
            scope=['Q0', 'Q2'])
            
    ]

The scheduler will schedule these blocks *sequentially*, since they have overlapping scope. Effectively, this is the same as putting a barrier after the first two instructions. 

Using the control flow example from earlier, we can use the `Block` instruction to modify the scheduling behavior in interesting ways:

    [
        {'name': 'X90', 'qubit': 'Q1'},
        {'name': 'read', 'qubit': 'Q0'}, 

        {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas', 'scope': ['Q0', 'Q2'], 
         'true': [
             {'name': 'X90', 'qubit':'Q0'}
             ], 
         'false': [
             {'name': 'X90', 'qubit':'Q2'}
             ]},

        {'name': 'X90', 'qubit': 'Q2'},

        {'name': 'block', 'body': [
                {'name': 'X90', 'qubit': 'Q1'}
            ]}

    ]

We now have an extra basic block:

    block_0:
        {'name': 'X90', 'qubit': 'Q1'},
        {'name': 'read', 'qubit': 'Q0'}, 
        
    block_0_ctrl:
        {'name': 'jump_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas', 'scope': ['Q0', 'Q2'], 'jump_label': 'true_0'}

    true_0:
        {'name': 'X90', 'qubit':'Q0'},
        {'name': 'jump_i', 'jump_label': 'end_0', 'scope': ['Q0', 'Q2']}

    false_0:
        {'name': 'X90', 'qubit':'Q2'},
        {'name': 'jump_i', 'jump_label': 'end_0', 'scope': ['Q0', 'Q2']}

    end_0:
        {'name': 'X90', 'qubit': 'Q2'},

    block_1:
        {'name': 'X90', 'qubit': 'Q1'}


And the control flow graph now looks like this:

               block_0: 0
                /    \
               /      \
              /        |
             |         v
             |      block_1: 510
             v
        block_0_ctrl: 510
            / \
           /   \
          /     \
         /       \
        |         |
        v         v
    true_0: 515   false_0: 515
         \       /
          \     /
           \   /
            \ /
             |
             v
           end_0: 530

`block_1` is only scoped to `Q1`, so it has no dependencies on any blocks except `block_0`. So, the instruction it contains can be scheduled earlier than it was in the previous version of the program, where it was in `end_0` with the `X90` gate on `Q2`.

Note that `Block` instructions *can* contain control flow structures (i.e. the `body` field can contain any valid QubiC-IR code); this simply results in the block being subdivided during the [FlattenControlFlow](../api/ir_passes.md#distproc.ir.passes.FlattenProgram) pass. This can lead to unintuitive behavior so handle with care.

## Loops

Loop instructions are handled separately from branch-type instructions, even though these both resolve into conditional jumps. For instance, the loop:

    Loop(cond_lhs=10, alu_cond='lt', cond_rhs='loop_ind', 'scope'=['Q0'],
        body=[
            Gate(name='X90', qubit=['Q0']),
            Alu(lhs=1, op='add', rhs='loop_ind', out='loop_ind')
        ])

will get flattened into:

    JumpLabel(label='loop_0', 'scope'=['Q0'])
    Gate(name='X90', qubit=['Q0']),
    Alu(lhs=1, op='add', rhs='loop_ind', out='loop_ind')
    LoopEnd(loop_label='loop_0', 'scope'=['Q0'])

The scheduler will register the loop as `loop_0` and track the duration of its `body`. When the program is lowered to assembly, the compiler will replace the `LoopEnd` instruction with an `inc_qclk` assembly instruction to decrement the pulse timing reference by the duration of the loop. So, for the purposes of global scheduling, the loop can be though of as having a duration of 0 (since the internal time reference is turned back every iteration). Our above example snippet will get resolved into the following assembly:

    {'op': 'jump_label', 'dest_label': 'loop_0'},
    <some pulses for the X90 gate>...,
    {'op': 'reg_alu', 'in0': 1, 'in1_reg': 'loop_ind', 'out_reg': 'loop_ind'},
    {'op': 'inc_qclk', 'in0' -<duration>},
    {'op': 'jump_cond', 'in0': 10, 'alu_cond': 'lt', 'in1_reg': 'loop_ind', 'jump_label': 'loop_0'}

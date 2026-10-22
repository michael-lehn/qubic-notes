## The Virtual-Z Instruction

The `VirtualZ` instruction is used to perform single-qubit Z-gates with arbitrary rotation angles. This is done by applying phase offsets to subsequent qubit drive pulses on the specified qubit frequency.

JSON format: 

    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': 3.1415926}
or

    {'name': 'virtual_z', 'freq': 'Q0.qdrv', 'phase': 3.1415926}
or

    {'name': 'virtual_z', 'freq': 4.5729e9, 'phase': 3.1415926} 

Python format:

    VirtualZ(qubit='Q0', freq=None, phase=np.pi)

## Phase Tracking

In QubiC, temporal phase tracking is performed in hardware; that is, the initial phase of any pulse is given by $freq \times t_{start}$. This maintains the phase coherence of any pulse sequence. Virtual-Z instructions apply a phase offset *on top* of this initial temporal phase.

### Qubit Frequency Name Resolution

The `qubit` and `freq` fields are used to specify the pulse frequency to apply phase offsets to. Frequencies can be anonymous (i.e. given by a value in Hz), or named (declared using a [DeclareFreq](frequency_declaration.md) instruction or specified in the gate configuration object ([qubitconfig.QChip](https://gitlab.com/LBL-QubiC/experiments/qubitconfig/-/blob/main/qubitconfig/qchip.py?ref_type=heads), see [Gate Resolution Pass](../api/ir_passes.md/#distproc.ir.passes.ResolveGates) for details). Frequencies are resolved as follows:

  - If `qubit` and `freq` are both provided: frequency is assumed to be named, given by `f'{qubit}.{freq}'`
  - If only `freq` is provided: can be named or anonymous, resolved directly into provided value
  - If only `qubit` is provided: assumed to be named, resolves into `f'{qubit}.freq'`

Note that named and anonymous frequencies are treated separately; for instance, if we have a program snippet:

    DeclareFreq(freqname='my_freq', freq=4.376e9),
    
    VirtualZ(freq='my_freq', phase=np.pi/2),

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347),

    Pulse(freq='my_freq', twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347),

The VirtualZ phase offset **only** gets applied to the second pulse, not the first, even though they have the same numerical frequency.

### Compile Time Phase Tracking

By default, virtual-z phase offsets are applied to pulses at compile time. For example:

    
    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    VirtualZ(freq=4.376e9, phase=np.pi/2),

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

Becomes:

    
    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=np.pi/2, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=np.pi/2, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

### Run Time Phase Tracking and the `BindPhase` Instruction

Compile-time phase tracking is not always desirable, such as in the case of a virtual-z gate being applied conditionally based on a measurement outcome. In this case, the `'bind_phase'` instruction can be used:

    Declare(var='my_phase', dtype='phase')
    BindPhase(freq=4.376, qubit=None, var='my_phase')

This "binds" the phase of the specified frequency to a variable. So, all virtual-z gates being applied to that frequency are implemented in hardware as ALU operations, and all `'phase'` arguments of pulses at the provided frequency are parameterized by the provided variable. 

So, adding a `BindPhase` instruction to our above snippet:

    Declare(var='my_phase', dtype='phase', scope=['Q2']),
    BindPhase(freq=4.376, qubit=None, var='my_phase'),

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    VirtualZ(freq=4.376e9, phase=np.pi/2),

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    Pulse(freq=4.376e9, twidth=2.4e-08, phase=0, 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

Becomes:

    
    Declare(var='my_phase', dtype='phase', scope=['Q2']),
    SetVar(var='my_phase', value=0),

    Pulse(freq=4.376e9, twidth=2.4e-08, phase='my_phase', 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    Alu(lhs=np.pi/2, op='add', rhs='my_phase', out='my_phase')

    Pulse(freq=4.376e9, twidth=2.4e-08, phase='my_phase', 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

    Pulse(freq=4.376e9, twidth=2.4e-08, phase='my_phase', 
          env={'env_func': 'cos_edge_square', 
               'paradict': {'ramp_fraction': 0.25}}, 
          dest='Q2.qdrv', amp=0.3347)

### Deriving Phase Trackers

For some applications, it is useful to bind a particular tracking frame to a function of other tracking frames; the `DerivePhaseTracker` instruction can be used for this:

JSON:

    {'name': 'derive_phase_tracker', 'freq': 'Q2.freq', 'components': [('Q0.freq', 1), ('Q1.freq', -2)]

Python:

    DerivePhaseTracker(freq='Q2.freq', components: [('Q0.freq', 1), ('Q1.freq', -2)])

The instruction has the following fields:

  - `freq` or `qubit`: phase tracking frequency to bind; this has the same semantics as the `freq` or `qubit` in the `VirtualZ` instruction
  - `components`: list of tuples indicating the primitive frequencies to bind `freq` to. The first element of each tuple is the frequency name, and the second element is the coefficient (default 1 if not provided). These frequencies themselves must NOT be derived, and should be frequency names, not qubits.

In the above example, `'Q2.freq'` becomes a *derived* phase tracking frame. All `VirtualZ` gates on the frequencies `'Q0.freq'` and `'Q1.freq'` are propagated to `'Q2.freq'`, according to the coefficients indicated in the `components` tuple. For example, a `VirtualZ` gate with phase $\frac{\pi}{2}$ applied to `'Q1.freq'` will result in a $-\pi$ phase update on `'Q2.freq'`. `VirtualZ` gates on '`Q2.freq'` are also propagated back to `'Q0.freq'` and `'Q1.freq'` in a manner that satisfies $\Delta\phi_2 = \Delta\phi_0 - 2 \times \Delta\phi_1$, where $\Delta\phi_i$ gives the phase update for `'Qi.freq'`.


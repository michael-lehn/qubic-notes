## The DeclareFreq Instruction

JSON format:

    {'name': 'declare_freq', 'scope': ['Q0'], 'freqname': 'q0_drive', 'freq': 4.798e9 Hz} 

Python format:

    DeclareFreq(scope=['Q0'], freqname='q0_drive', freq=4.798e9)

The `declare_freq` instruction is used to register a frequency into the program. Using this instruction is *optional*; anonymous frequencies can be used in pulses (and `virtual_z` instructions), and named (and anonymous) frequences can be registered by the [qubitconfig.QChip](https://gitlab.com/LBL-QubiC/experiments/qubitconfig/-/blob/main/qubitconfig/qchip.py?ref_type=heads) object during [Gate Resolution](../api/ir_passes.md#distproc.ir.passes.ResolveGates). 

This instruction has two primary purposes:

1. Declaring a named frequency without [qubitconfig.QChip](https://gitlab.com/LBL-QubiC/experiments/qubitconfig/-/blob/main/qubitconfig/qchip.py?ref_type=heads)
2. Parameterizing pulse frequencies using a variable/register

This instruction has the following fields:

  - `freq`: frequency in Hz
  - `scope`: [scope](scope.md) (list of qubits or output channels) targeted by this frequency
  - `freqname`: name of the frequency (optional; default is `None`)
  - `index`: index of this frequency in the frequency buffer; useful for register parameterization (optional, default is `None`)

## A note about frequency parameterization

In QubiC, frequencies (unlike amplitude or phase) are not passed directly to the signal gen block. They are instead stored in a buffer (see [qubic.rfsoc.hwconfig](https://lbl-qubic.gitlab.io/software/hwconfig/#qubic.rfsoc.hwconfig.RFSoCElementCfg.get_freq_buffer) for details); and the *address* of the frequency within this buffer is ultimately what is stored in the compiled pulse instruction (and thus passed from the disscope.mdtributed processor core to the sig gen block). The address of a declared frequency can be set using the `index` field, which can then be parameterized by a variable. 

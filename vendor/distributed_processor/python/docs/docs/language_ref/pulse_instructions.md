## The Pulse Instruction

`Pulse` instructions are used to trigger and parameterize qubit drive, readout, and demodulation pulses. All quantum gates and measurement operations must eventually be resolved into pulse instructions.

Examples:

  - JSON:

          {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 0.3347, 
           'twidth': 2.4e-08, 
           'env': {'env_func': 'cos_edge_square', 
                   'paradict': {'ramp_fraction': 0.25}},
           'dest': 'Q2.qdrv'}, 

  - Python:

          Pulse(freq=4944383311, twidth=2.4e-08, phase=0, 
                env={'env_func': 'cos_edge_square', 
                     'paradict': {'ramp_fraction': 0.25}}, 
                dest='Q2.qdrv', amp=0.3347)

The instruction has the following fields:

 - `name`: `'pulse'`
 - `phase`: pulse initial phase in radians, or variable of type `'phase'`
 - `freq`: pulse frequency in Hz, named frequency, or variable of type `'int'`
 - `amp`: pulse amplitude (as a fraction of DAC full scale, normalized to 1), or variable of type `'amp'`
 - `env`: dictionary specifying envelope function to use (resolved during assemble stage by `ElementConfig`), or numpy array of samples
 - `twidth`: pulse duration in seconds
 - `start_time`: (**optional**; can be determined by a scheduling pass. Default is `None`) pulse start time in FPGA clock cycles
 - `dest`: named firmware output channel. Resolved during assemble stage by `ChannelConfig` object; see [Understanding Channel Configuration](https://gitlab.com/LBL-QubiC/software/-/wikis/Understanding-Channel-Configuration) for details


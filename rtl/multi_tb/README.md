# Multi-core RTL simulation

`multicore_top.sv` = 3 qubit cores (`qcore`: processor, instruction memory,
qdrv, rdrv and rdlo signal generators with their waveform memories and the
generator's glue), one shared `fproc_meas`, and the shot state machine of
`vendor/gateware/dsp/dsp.sv` (all cores done, all signal generators idle, reset,
rerun `nshot` times). Widths and glue follow the ZCU216 build.

```sh
source env.sh
# all checks below, with assertions
python rtl/multi_tb/run_multi.py
# one program: event log (strobes, FPROC requests, measurements, shot starts)
python -m qdsl qdsl/examples/mc_feedback.qd --emit-bin rtl/multi_tb/build/fb.json
(cd rtl/multi_tb && make QD_BIN=build/fb.json QD_NSHOT=3 QD_ADC="1,1;-1,1;1,1")
```

`QD_ADC` sets each core's constant ADC sample per shot (shots separated by `;`,
cores by `,`); its sign sets the measured bit. `QD_MEAS="0:1,1,0;1:0"` instead
forces the measured bits of core 0 to 1, 1, 0 (then 0) and of core 1 to 0, in the
order of measurement: a testbench override of the demodulated sign, used to run
a measurement-dependent loop a chosen number of times. The log ends with
`SLACK min ...`: over all timed instructions (`pulse_write_trig`, `idle`), the
smallest difference between timestamp and `qclk` when the core reaches it. A
negative value is a late trigger, which never fires.

`run_seq.py` checks QD's sequencing guarantee on this RTL: for each program it
turns strobes into pulse intervals and checks that every pulse of the earlier
statement ends before the later one starts, with no late trigger. It covers
runtime loops followed by another qubit (two cores, one core, measurement-
dependent with 1 and 3 iterations, fixed count) and `parallel` blocks (three
cores, one core, two qubits sharing a core, unequal branches, nested blocks,
runtime loops inside branches). It uses the fixtures in `qdsl/tests/configs`
whose channels fit the 3 modelled cores.

```sh
python rtl/multi_tb/run_seq.py                  # all cases
python rtl/multi_tb/run_seq.py loop_meas_two_cores
```

| Program | Result |
| --- | --- |
| `mc_align.qd` | parallel X90s on cores 1 and 2 in the same clock; `parallel` readouts in the same clock (a property of the schedule on distinct cores, not promised by `parallel`) |
| `mc_feedback.qd`, 3 shots, Q0 = 1, 0, 1 | X90s on Q1 (core 1) in shots 0 and 2 only; both cores request in the same clock (qclk 1372); join at qclk 1406; every shot 2781 clocks; Q1's bit from shot 0 still latched in shot 1 |
| `mc_t1_runtime.qd` | readouts on both cores in the same clock every iteration; pi to readout 16, 5016, 10016 clocks |
| `mc_feedback.qd`, hold 62 | X90s played in the wrong shots: each shot acts on the previous shot's bit |
| `mc_t1_runtime.qd`, shift on Q0 only | readout skew 0, 5000, 15000 clocks: cores drift apart silently |

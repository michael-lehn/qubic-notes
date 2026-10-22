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
cores by `,`); its sign sets the measured bit.

| Program | Result |
| --- | --- |
| `mc_align.qd` | parallel X90s on cores 1 and 2 in the same clock; `par` readout in the same clock |
| `mc_feedback.qd`, 3 shots, Q0 = 1, 0, 1 | X90s on Q1 (core 1) in shots 0 and 2 only; both cores request in the same clock (qclk 1372); join at qclk 1406; every shot 2781 clocks; Q1's bit from shot 0 still latched in shot 1 |
| `mc_t1_runtime.qd` | readouts on both cores in the same clock every iteration; pi to readout 16, 5016, 10016 clocks |
| `mc_feedback.qd`, hold 62 | X90s played in the wrong shots: each shot acts on the previous shot's bit |
| `mc_t1_runtime.qd`, shift on Q0 only | readout skew 0, 5000, 15000 clocks: cores drift apart silently |

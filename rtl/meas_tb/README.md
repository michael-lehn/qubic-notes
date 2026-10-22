# Measurement-feedback timing on RTL

`core_meas_top.sv` = processor + `fproc_meas` + the `rdlo` element, mixer and
accumulator (`gateware/dsp/element.sv`, `ammod.v`, `phtime.v`, and
`reg_delay1`/`cordicg3`/`cmultiplier2` from `vendor/common-hdl`, the commit the
gateware pins), wired with the glue the gateware generator emits. The `rdlo`
envelope and frequency memories hold the assembler's real buffers.

```sh
source env.sh
python -m qdsl qdsl/examples/ex6_active_reset.qd \
    --emit-bin rtl/meas_tb/build/ex6.json
# event timeline in the log
(cd rtl/meas_tb && make QD_BIN=build/ex6.json QD_ADC=1)
# margins: vary hold / jump_fproc budget
python rtl/meas_tb/run_checks.py
```

Result for `ex6_active_reset.qd` (qclk):

| Event | qclk |
|---|---|
| rdlo strobe (scheduled 305) | 307 |
| integration gate | 354 .. 1353 |
| accvalid | 1369 |
| meas_reg holds the new bit | 1372 |
| FPROC request / data sampled | 1372 / 1373 |
| first X90 enters DECODE (trigger 1380) | 1380 |

Margins: result 1 clock early (hold 63 still works, 62 reads a stale bit and
silently takes the wrong branch); conditional pulse 0 clocks (a `jump_fproc`
budget of 7 hangs the core).

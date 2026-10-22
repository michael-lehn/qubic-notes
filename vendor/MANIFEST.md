# Vendored QubiC sources

Unmodified copies of the QubiC sources this project builds on, simulates, or
cites. Everything in `qubic-notes` uses these copies; nothing refers to a QubiC
checkout or fetches anything. Our only change to QubiC is
`../patches/distproc-runtime-delay.patch`, which `setup.sh` applies to a build
copy, never to these files.

Paths in the reference doc (e.g. `distproc/ir/passes.py:110`,
`distributed_processor/hdl/ctrl.v`, `gateware/dsp/element.sv`) resolve inside
this directory.

| Directory | Origin | Commit | Date | Contents |
|---|---|---|---|---|
| `distributed_processor/` | gitlab.com/LBL-QubiC/distributed_processor | `c22cce81db5f84a607e46646e9f3441709aef9dd` | 2025-10-22 | complete repository (compiler, assembler, RTL, sim wrappers, cocotb tests, docs) |
| `qubitconfig/` | gitlab.com/LBL-QubiC/experiments/qubitconfig | `c766ddbcae76e08ff7dbd770fa1203b4aee224b9` | 2025-05-22 | the `qubitconfig` package |
| `software/` | gitlab.com/LBL-QubiC/software | `c05087528d1c6fbb1f1ddf61ddffc7a3676192d6` | 2026-09-01 | `qubic/{__init__,pulse_factory,toolchain,job_manager}.py`, `qubic/rfsoc/{__init__,hwconfig,pl_interface}.py`, `examples/{qubitcfg,channel_config}.json` |
| `gateware/` | gitlab.com/LBL-QubiC/gateware | `2713290d04a8b8944bb474e381b29d2cfb5d2d7b` | 2026-08-07 | `dsp/{element.sv,ammod.v,phtime.v,dsp.sv}`, `top/src/{dsp_build.py,dsp_coregen.py,zcu216/plps.d}`, `top/zcu216_14_2.yaml`, `top/zcu216_14_2/{dsp_config.yaml,cocotb/dsp.d}` |
| `common-hdl/` | gitlab.com/lbl-bids/common-hdl (gateware submodule) | `fd73b16224cfebeea0159c1fe52e04f9eb048d74` | 2024-11-18 | `reg_delay1.v`, `cordicg3.sv`, `cmultiplier2.v` (the variants listed in `gateware/top/src/zcu216/plps.d`) |

All source repositories were clean (no local changes) when copied. Each
directory keeps its upstream license file (`LICENSE`, or `license.txt` for
common-hdl).

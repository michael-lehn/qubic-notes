# QubiC compiler & ISA notes

Scripts and testbenches behind the reference document `docs/reference.md`.
Everything runs without FPGA hardware. All QubiC sources are vendored in
`vendor/` (origins and commits in `vendor/MANIFEST.md`); nothing refers to a
QubiC checkout or fetches sources.

## Layout

| Path | What |
|---|---|
| `docs/` | `reference.md` (QubiC compiler & ISA reference) and `architecture.svg` |
| `compiler/` | scripts that drive the QubiC compiler directly (Parts C-D of the reference) |
| `rtl/isa_tb`, `rtl/fproc_tb` | RTL checks of the ISA and of FPROC |
| `qdsl/` | QD language prototype |
| `rtl/qd_tb/` | runs QD-compiled machine code on the RTL (`run_demo.sh`) |
| `rtl/meas_tb/` | measurement-feedback timing: processor + FPROC + rdlo element on RTL |
| `patches/` | our extension to the QubiC compiler (runtime delay), applied to `.build/` by `setup.sh` |
| `vendor/` | unmodified QubiC sources used and cited, with `MANIFEST.md` (origins, commits) |

## Setup

Needs Homebrew `python@3.12` (cocotb does not build on 3.15) and `verilator`
(5.052 tested).

```sh
# creates .venv and .build/ (copies of qubitconfig, distproc, qubic.rfsoc)
./setup.sh
# venv + copied 'qubic' package on PATH/PYTHONPATH
source env.sh
```

Re-run `./setup.sh` after changing anything in `vendor/`: it installs from build
copies, never from `vendor/` directly.

## Compiler (`compiler/`)

Uses `software/examples/qubitcfg.json` and `channel_config.json` (ZCU216).

| Command | What it does |
|---|---|
| `python run_examples.py [0 1 2 3 4 5 6 7 7b]` | IR after all passes, per-core assembly, 128-bit machine words with decoding |
| `python trace_passes.py <example>` | IR after every compiler pass |
| `python hand_asm.py` | Hand-written assembly the compiler never emits (register `inc_qclk`, split pulses, `sync`) |
| `python probe.py` | Negative amplitude immediate; 17th register error |

Examples: 0 amplitude sweep (original IR) · 1 `x = 42` · 2 `c = a + b` · 3
counter loop · 4 shaped pulse · 5 measurement · 6 branch on measurement · 7 two
qubits + CNOT · 7b "sequential" raw pulses. Add your own to the `EX` dict in
`run_examples.py`.

The instruction decoder in `run_examples.py` is mine, written from the bit
layout in `distproc/command_gen.py`; it is not part of QubiC.

## RTL (`rtl/`)

cocotb 2.x testbenches on Verilator, compiled from
`vendor/distributed_processor/hdl`.

```sh
# 8 tests: cycle costs, timed trigger, late-trigger hang, inc_qclk,
# strict compares, amp truncation, sync hang, all-zero word = done
cd rtl/isa_tb && make
# fproc_meas: 2-clock latency, stale result, cross-core read
cd rtl/fproc_tb && make
```

Grep the log for `RESULT` lines. Workarounds: `-Wno-HIERPARAM` for Verilator
5.052, and `fproc_meas_sim_fixed.sv` adds the `()` missing from the
interface-array instantiation in the repo's `sim_modules/fproc_meas_sim.sv`. The
repo's own cocotb tests target cocotb 1.x and are not used.

## Outputs (`outputs/`)

Logs from the runs the reference doc quotes: `out_a/b/c.txt` (compiler examples
0–7b), `sim_isa.log`, `sim_fproc.log`.

## QD language prototype (`qdsl/`)

An Odin-flavoured front end that compiles `.qd` files to QubiC-IR and on to
machine code, with strict `;` sequencing, explicit `par`, and hardware-aware
static checks. See `qdsl/README.md`.

```sh
python -m qdsl qdsl/examples/ex7_two_qubits.qd   # static schedule
python -m qdsl.run_tests                          # 13 examples, 16 errors
rtl/qd_tb/run_demo.sh                             # QD -> machine code -> RTL
```

`setup.sh` installs a **patched** copy of `distproc` (see `patches/README.md`);
the vendored sources themselves are never modified.

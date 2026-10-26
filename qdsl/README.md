# QD: an Odin-flavoured front end for QubiC (v0 prototype)

QD compiles to QubiC-IR, then runs the unmodified QubiC compiler and assembler
down to 128-bit machine words. It adds two things the IR does not have:
**explicit time semantics** and **static checks that know the hardware**.

```sh
source env.sh
python -m qdsl qdsl/examples/ex6_active_reset.qd  # static schedule (default)
python -m qdsl FILE --ir | --asm | --bin | --check | --emit-ir out.json
python -m qdsl.run_tests                          # examples, error cases, core, sequencing, placement tests
python rtl/multi_tb/run_seq.py                    # physical pulse order on the RTL
```

## Language at a glance

A complete program that uses every construct (it compiles as is):

```odin
qubit Q0, Q1, Q2;                   // calibrated qubits (from qubitcfg.json)
place Q0 on board0.core0,           // where their channels are wired (checked
      Q1 on board0.core1,           // against the channel configuration)
      Q2 on board0.core2;

WAIT : time : 500 us;               // constant   name : type : value
STEP :: 0.1;                        // constant, inferred
a : amp = 0.1;                      // register   name : type = value
n := 0;                             // register, inferred int

// procs are always inlined
ramsey :: proc(q: qubit, t: time) { X90(q); delay(t); X90(q); }

do {                                // the hardware loop: post-test
    pulse(Q0.qdrv, freq = Q0.freq, amp = a, phase = pi / 2,
          width = 24 ns, env = cos_edge_square(0.25));
    measure(Q0);
    delay(WAIT);
    a += STEP;
} while a < 1.0;

for n < 3 { X90(Q0); n += 1; }      // pre-test (guarded do-while)
for i in 0..<5 { X90(Q1); }         // counter loop on an int register
#unroll for t in 0 us ..< 50 us step 10 us {   // compile-time loop
    ramsey(Q0, t);
    measure(Q0);
}
if measure(Q0) == 1 { X90(Q0); } else { X90(Q1); }   // feedback
m := measure(Q1);                   // measurement into a register
parallel { X90(Q0); | X90(Q1); }    // independent branches; the end is a join
delay(10 us);
barrier(Q0, Q1);
gate("Y-90", Q0);                   // gate name that is not an identifier
CNOT(Q2, Q1);
tau : time = 0 us;                  // runtime delay (patched compiler)
delay(tau);
tau += 10 us;
```

## Semantics

| Construct | Meaning | Lowering |
|---|---|---|
| `place Q0 on board0.core0;` | a declaration: Q0's channels are wired to that processor core; checked against the channel configuration at compile time | nothing (see "Placement") |
| `X90(Q0); X90(Q1);` | every quantum operation of the first statement has completed before any of the second begins, on every processor core | `barrier(Q0, Q1)`: the union of both statements' qubits; after a runtime loop, see "Execution model" |
| `parallel { X90(Q0); \| X90(Q1); }` | independent branches that may overlap; no common start is promised; the end is a join | barrier before, branches one after another in the IR, barrier via the next `;` |
| `delay(10 us);`, `delay(10 us, Q0);` | idle the enclosing qubits (or the listed ones) | `delay` scoped to those qubits |
| `tau : time = 0 us;` then `delay(tau);` | runtime delay; applies to every qubit of the program | `alu sub` into a scratch register + `inc_qclk` on every core (patched IR op, `patches/`) |
| constants | folded at compile time, with units | immediates, envelope buffers |
| registers | replicated on every core that needs them | `declare` with an inferred scope |
| `do/while`, `for`, `if` | conditions normalized to the hardware's `<`, `>`, `==` with a register on the right | `loop`, `branch_var`, `branch_fproc` |

Register scopes are inferred by a fixed point over pulses, conditions and ALU
operations (see the header of `lower.py`).

## Execution model

**Sequential.** `S1; S2` guarantees that every quantum operation (pulse, gate,
measurement, runtime delay) of `S1` has completed before any of `S2` begins,
however the qubits map to processor cores.

**Parallel.** `parallel { A | B | ... }` declares independent branches. They
may overlap, but nothing promises that they start together. The closing brace
is a join: the next statement starts after every branch has completed. Branches
must use disjoint qubits, and a register written in one branch must not be used
in another. A nested `parallel` is a statement like any other.

**How it is compiled** (existing QubiC ISA, no runtime synchronization):

| Situation | Strategy |
|---|---|
| straight-line code, `if`, `parallel` on distinct cores | static scheduling: barriers become timestamps; on distinct cores the branches of a `parallel` block start at the same barrier |
| `parallel` branches that share a core | the core issues one branch after the other (QubiC's per-core scheduling, pulses ≥ 3 clocks apart); the join still waits for every branch |
| a runtime loop (`do/while`, `for`) followed by an operation on another core | control-flow replication: every core with a quantum operation after the loop runs the loop's control flow, with the same registers and FPROC reads, so it leaves the loop when the loop ends (`lower.py`, `later`) |
| fixed-count loops | replicated like any runtime loop; `#unroll for` gives straight-line, statically scheduled code |

Why replication is needed: QubiC rewinds `qclk` at the end of every loop
iteration and schedules what follows a loop from the loop's start time. A core
that did not run the loop would fire its next pulse while the loop is still
running. Before this was fixed, `do { X90(Q0); m = measure(Q0); } while m == 1;
X90(Q1);` with Q0 and Q1 on different cores fired `X90(Q1)` at cycle 22, while
the loop ran until cycle 4122 (three iterations, RTL). It now fires at 4213, as
on a shared core.

**Rejected** rather than compiled with a weaker order:

| Program | Diagnostic |
|---|---|
| a core must follow two runtime loops that run at the same time in different `parallel` branches, e.g. `parallel { do {…Q0…} while c0; \| do {…Q1…} while c1; } X90(Q2);` | `cannot guarantee the order of the loop: processor cores … both take part, but only … has run the runtime loop at line … before` |
| a core must follow a loop whose condition it cannot read (another board's FPROC) | `measurement feedback on Q0 could read the wrong result`, with the reason |
| `parallel` branches that share a qubit, or a register one of them writes | `parallel branches 1 and 2 both use …` |
| a runtime delay inside a `parallel` branch | it would shift every core, including the other branches |
| `par { ... }` | `par was replaced by parallel { A; \| B; }` |

The same check accepts programs where one core can follow both loops in turn.
Examples are two loops on one shared core, or `parallel { loop on Q0 | loop on
Q1 } measure(Q1);`: core 1 follows Q0's loop, then runs its own, so the
branches run one after the other.

**Timing limits.** The guarantee rests on QubiC's static cycle model. On this
RTL the model is exact: the RTL runs show trigger slack (timestamp minus `qclk`
when a timed instruction is reached) of 0 to 3 clocks and never negative, so
there is no margin. A timed instruction reached late never fires, and the core
hangs (RTL test t3). The hardware does not detect this, and QD cannot rule it
out for costs the model does not count, such as the extra `pulse_write` word of
a pulse with two register parameters (QD warns). Two cores agree on time only
through timestamps and a common reset at the shot start.

## Processor cores

QD maps every object to physical processor cores from the channel configuration
(`cores.py`). A core is `CoreId(board_name, core_name, core_ind)`: the assembler
programs it through instruction memory `{core_name}_command{core_ind}` (or
`command{core_ind}`) on `board_name`. `core_name` is a core type shared by many
cores; `null` and `""` denote the same core.

```python
t = Target(channels_path=...)
t.cores.cores_of('Q0')               # C(Q0): cores of all of Q0's channels
t.cores.cores_of('Q0.qdrv', 'Q1')    # union over objects
t.cores.channels_of_core(core)       # channels of one physical core
t.cores.qubits_of_core(core)
t.cores.proc_grouping()              # QubiC proc_grouping, one tuple per CoreId
t.cores.qubit_scoper()               # QubiC qubit -> channels, from the config
```

The backend hands QubiC the configuration-derived grouping and qubit mapping
instead of QubiC's name patterns. The configuration is validated when `Target`
is created (`ConfigError`); `t.cores.notes` lists non-fatal findings.

## Placement

A `place` declaration states which processor core each channel of a qubit is
wired to:

```odin
qubit Q0, Q1;
place Q0 on board0.core0;           // all of Q0's channels: qdrv, rdrv, rdlo
place Q1.qdrv on board0.core1,      // one channel at a time, comma-separated,
      Q1.rdrv on board0.core1,      // one statement
      Q1.rdlo on board0.core1;
X90(Q0);
X90(Q1);
```

`place Q0 on C;` is short for placing every channel that the channel
configuration gives Q0 (normally `Q0.qdrv`, `Q0.rdrv`, `Q0.rdlo`) on `C`.

**Core names.** `BOARD.coreN` is the core with `core_ind` N on board `BOARD`.
`BOARD` is the configuration's `board_name`; channels without one (the vendored
configuration and most fixtures) are on the unnamed board, written `board0`.
When several core types (`core_name`) on a board have the same `core_ind`,
name the type as well: `board0.aux.core0` (`qdsl/tests/configs/core_types.json`).
`CoreModel.resolve_core` and `CoreModel.core_label` implement this on top of
`CoreId`; placement diagnostics use the same names (other diagnostics still print
the `CoreId` form, e.g. `qubit/2`).

**Semantics (implemented).** The channel configuration (`--channels`, default
`vendor/software/examples/channel_config.json`) fixes the wiring:
`core_ind`, `core_name` and `board_name` of every channel. `qubitcfg.json`
(`--qchip`) holds calibrations only and says nothing about cores. A placement
is therefore a requirement that the compiler checks against the channel
configuration; it never moves a channel. A program compiles to the same
machine code with or without its placements (`test_placement.py` checks this
for every example). The rules:

- `place` is a top-level declaration. It is not an operation and emits no
  code. Its qubits must be declared before it.
- Every placement must agree with the channel configuration. Otherwise the
  compiler reports the actual wiring and the declaration that would match it.
- A channel may be placed more than once only on the same core.
- Placements are optional and may be partial: an unplaced channel is where the
  configuration puts it.
- Scope inference, scheduling, register allocation and lowering map qubits to
  cores through `CoreModel`. That is the same mapping as the accepted
  placements, which `Lowering` asserts.

Diagnostics:

| Program | Diagnostic |
|---|---|
| `place Q5 on board0.core0;` with no `qubit Q5;` | `unknown qubit 'Q5'` |
| `place Q0.drive on board0.core0;` | `'Q0.drive' is not a channel`, with Q0's channels |
| `place Q1.rdrv on ...` when the configuration has no `Q1.rdrv` | `'Q1.rdrv' is not in the channel configuration` |
| `place Q0 on board1.core0;` | `no board 'board1' in the channel configuration`, with the boards |
| `place Q0 on board0.core8;` | `no core board0.core8 in the channel configuration`, with the cores |
| `board0.core0` where two core types have `core_ind` 0 | `board0.core0 is ambiguous`, with the qualified names |
| `place Q0 on board0.core0;` then `place Q0.rdlo on board0.core1;` | `conflicting placement of 'Q0.rdlo'` |
| `place Q0 on board0.core1;` when Q0 is wired to core 0 | `cannot place Q0 on board0.core1: the channel configuration (...) wires Q0.qdrv to board0.core0, ...`, hint: the matching `place`, or another `--channels` |

**Examples for other configurations.** An example written for another channel
configuration says so in a comment, `// compile with --channels PATH`. The
test runner and `tools/check_doc_dsl.py` compile it with that configuration;
`python -m qdsl` needs the option given explicitly. `place_shared_core.qd`
(`shared_core.json`: Q0 and Q1's drive on one core) and
`place_spread_qubit.qd` (`spread_qubit.json`: Q1's drive on core 1, its
readout channels on core 2) are such examples.

## Checks

| Check | Why |
|---|---|
| unknown gate / qubit / frequency, with suggestions | IR: `KeyError` deep in a pass |
| delay and pulse width must be constants | IR: `TypeError` in the scheduler |
| ordering compares on `amp` registers that may hold a negative step | hardware compares the wrapped 16-bit word (RTL test t6) |
| negative `amp` constant in a comparison | same encoding problem |
| ordering compares on `phase` | phase wraps modulo 2π |
| `<=`, `>=`, `!=` in loop conditions | hardware has `<`, `>`, `==` only and loops cannot negate (int + constant is rewritten) |
| `parallel` branches sharing a qubit, or a register that one of them writes | the order between the branches would be undefined |
| more than 16 registers on a physical core (counted per `CoreId`, including registers replicated to follow a loop) | assembler error far from the source |
| an order after a runtime loop that the cores cannot keep (see "Execution model") | silent: a later pulse fires while the loop is still running |
| runtime delay inside a `parallel` branch | it shifts every core |
| channel not in the channel configuration | late QubiC error |
| `place` that names an unknown qubit, channel, board or core, contradicts another `place`, or disagrees with the channel configuration | the program would silently run with a different wiring than the source states |
| measurement feedback where FPROC cannot identify the result (no `Qn.meas`, or several measuring cores share a `core_ind`) | wrong or no result |
| malformed or ambiguous channel configuration (missing or ill-typed fields, duplicate `elem_ind` per core, `elem_ind` outside 0..3, one core spelled with `null` and `""`, memory written by two channels) | late assembler exceptions or silent misgrouping |
| one `+`/`-` per runtime statement | single ALU op per instruction |
| instruction memory > 8192 words per core | gateware limit |
| runtime delay register that may decrease | a negative delay puts the next trigger in the past; the core hangs (RTL test t3) |
| virtual-Z gates (`Z90`, `Y-90`, `CNOT`) inside loops: warning | QubiC tracks frame phases statically |

## Verified on the processor RTL

`rtl/qd_tb/run_demo.sh` compiles two examples and runs their machine code on the
RTL:

- `ex6_active_reset.qd`: with measurement 1 the X90s fire at qclk 1382/1394,
  with 0 they are skipped; the final readout fires at qclk 1406 either way.
- `t1_runtime.qd`: pi-pulse to readout = 16, 5016, 10016, 15016, 20016 clocks (0
  to 40 us in 10 us steps) from one loop; qclk is identical in every iteration.

`rtl/multi_tb/run_seq.py` runs 14 sequencing programs on the 3-core RTL, with
forced measurement bits where a loop depends on them. It checks that every pulse
of the earlier statement ends before the later one starts, that no trigger is
late, and that every core finishes. The programs cover a loop followed by
another qubit (two cores, one core, measurement-dependent and fixed count),
`parallel` on three cores, on one core and on two cores sharing one, unequal
branch lengths, nested blocks, and runtime loops inside branches. The
measurement-dependent loop runs 1 or 3 iterations from the same binary.
`qdsl/test_sequencing.py` covers the same cases at the instruction level, plus a
qubit that spans two cores and boards.

## Not yet

- `place` cannot choose a wiring: QubiC's channel configuration fixes it, so a
  placement can only be checked. Choosing among alternative wirings, or
  requiring every used channel to be placed, would be new features
- board names that are not QD identifiers cannot be written in `place`; nor can
  the type of a core with an empty `core_name` when it is ambiguous

- runtime synchronization between cores (no hardware support: `sync` is never
  released in the build), synchronized physical-time counters, `now()`: design
  proposals only (top-level README)
- automatic static bounds for loops with a provable trip count (today: control-
  flow replication, or `#unroll for`)
- timing expressions (`duration(...)`), deadlines
- frequency-index registers, register `bind_phase` frames
- collecting several errors per run

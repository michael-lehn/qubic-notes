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
| `rtl/multi_tb/` | 3 cores + FPROC + shot sequencer on RTL (`run_multi.py`) |
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
python -m qdsl.run_tests                          # 17 examples, 16 errors
rtl/qd_tb/run_demo.sh                             # QD -> machine code -> RTL
python rtl/multi_tb/run_multi.py                  # multi-core + shots on RTL
# every QD snippet in the docs parses; programs compile to the listed words
python tools/check_doc_dsl.py docs/reference.md qdsl/README.md
```

`setup.sh` installs a **patched** copy of `distproc` (see `patches/README.md`);
the vendored sources themselves are never modified.

## Status

QD is a v0 prototype. **Implemented** is exactly what `qdsl/README.md`
describes: declarations, procs, `do`/`for`/`#unroll`/`if`, measurement
feedback, strictly sequential `;` (lowered to barriers over the qubits
involved), explicit `par`, runtime delays via the patched compiler, mapping to
physical processor cores from the channel configuration, and the listed static
checks. The tests cover these (`python -m qdsl.run_tests`,
`python -m qdsl.test_cores`, and the RTL runs above).

**Not implemented** (planned or open): the items under "Not yet" in
`qdsl/README.md` (timing expressions such as `duration(...)`, deadlines,
frequency-index registers, register `bind_phase` frames, reporting several
errors per run). Any revision of the execution and timing model (e.g. a
different notion of sequential vs. parallel blocks, synchronized time counters
across cores, or a `now()` expression) is an open design question, not part
of the language; the next section describes the current proposal.

**Known gap:** a runtime loop followed by a statement on a qubit whose core
does not run the loop is not ordered correctly today. QD neither replicates
the loop nor rejects the program, and the later statement can fire while the
loop is still running (Example 2, Case B below).

## Execution model: sequential and parallel programs (design proposal)

> **Proposed semantics, not yet implemented.** This section describes where
> the QD execution model is meant to go. It does not change what QD accepts or
> emits today. Proposed syntax appears in `text` blocks and does not parse.
> Programs in `odin` blocks are current QD and compile
> (`python tools/check_doc_dsl.py README.md`).

Every listing below is tagged:

- **[compiler output]**: produced today by `python -m qdsl FILE --bin` (QD
  front end + the QubiC compiler and assembler as installed by `setup.sh`).
  The decoded column comes from this repo's decoder (`qdsl/backend.py`).
- **[QubiC output, edited IR]**: QD's IR edited by hand, then compiled by the
  same QubiC toolchain. It shows what existing hardware can do with a
  different lowering; QD does not emit it.
- **[conceptual]**: hand-written with existing instructions, or pseudocode.
  It is labelled as such.
- **[proposed ISA]**: needs hardware or toolchain support that does not exist.

Timing numbers marked *RTL* come from one-off runs of these programs on the
3-core simulation in `rtl/multi_tb` (`make QD_BIN=...`, see its README). They
are not part of the test suite.

### The machine in one paragraph

A qubit is controlled by analog pulses: short microwave bursts, here 12 clocks
= 24 ns for an `X90` gate. It is read out by a measurement: a 1000-clock (2 µs)
readout pulse plus demodulation that yields one bit. Each qubit has signal
generators (`Q0.qdrv` drive, `Q0.rdrv` readout drive, `Q0.rdlo` readout
demodulator) attached to a **processor core**. A core is a small in-order
machine with 16 registers, one ALU and a 32-bit time counter `qclk` that
advances once per 2 ns clock. There is no "play now" instruction. Each pulse
instruction carries a timestamp `t`, and the core stalls on it until
`qclk == t` (`ctrl.v:41`, `proc.sv:138`). Cores share no memory and send no
messages. The only shared state is the measurement-result unit FPROC
(`fproc_meas.sv`), which any core can read. All cores leave reset together at
the start of a **shot** (one execution of the program). A shot ends when every
core is done (`gateware/dsp/dsp.sv:199-232`). Within a shot, operations on
different cores are ordered **only by their timestamps**. (Paths under `hdl/`,
`distproc/` and `gateware/` are in `vendor/`; details in `docs/reference.md`,
"Instruction set".)

### Proposed rules

1. **Sequential source means sequential execution.** In `A; B;`, `B` starts
   only after `A` has completed: all of `A`'s pulses have ended and all of its
   runtime decisions are taken. This holds on every physical core, including
   when `A` and `B` run on different cores.
2. **`parallel { A | B }` declares independence.** The branches may overlap,
   but nothing promises that they start together. A schedule may start them
   together, stagger them, or serialize them.
3. **The end of a `parallel` block is a join.** The next sequential statement
   starts only after every branch has completed.
4. **A join is a guarantee, not an instruction.** It constrains when later
   operations may happen. It does not require a runtime barrier.
5. **The compiler chooses the mechanism:** static scheduling, control-flow
   replication, or explicit hardware synchronization (all three are described
   below).
6. **If the compiler cannot guarantee the ordering, compilation fails.** It
   never silently weakens the semantics.
7. **`parallel` is intended to replace today's `par`.** Today's `par` requires
   disjoint qubits and starts its branches in the same clock (`qdsl/README.md`).
   That "start together" rule is current behaviour, not part of the proposal.
   How a program would request a simultaneous start (e.g. for an aligned
   readout) is open.

### Example 1: `parallel`, then a sequential statement

Proposed syntax:

```text
// proposed syntax: does not parse today
qubit Q0, Q1, Q2;

parallel {
    X90(Q0);
|
    X90(Q1);
}

X90(Q2);    // starts after both branches have finished
```

Physical mapping, from the vendored `software/examples/channel_config.json` as
derived by `qdsl/cores.py`:

| Qubit | Channels (`elem_ind`) | Physical core | Instruction memory |
|---|---|---|---|
| Q0 | `Q0.qdrv` (0), `Q0.rdrv` (1), `Q0.rdlo` (2) | `qubit/0` | `qubit_command0` |
| Q1 | `Q1.qdrv` (0), `Q1.rdrv` (1), `Q1.rdlo` (2) | `qubit/1` | `qubit_command1` |
| Q2 | `Q2.qdrv` (0), `Q2.rdrv` (1), `Q2.rdlo` (2) | `qubit/2` | `qubit_command2` |

The nearest current QD program uses `par`. Its common start is stricter than
`parallel` requires, but it is one valid schedule of it:

```odin
qubit Q0, Q1, Q2;
par { { X90(Q0); } { X90(Q1); } }
X90(Q2);
```

**[compiler output]**:

```
qubit_command0  @0  pulse_reset
                @1  pulse_write_trig t=5   cfg=0 amp=3677    X90(Q0)
                @2  done
qubit_command1  @0  pulse_reset
                @1  pulse_write_trig t=5   cfg=0 amp=15777   X90(Q1)
                @2  done
qubit_command2  @0  pulse_reset
                @1  pulse_write_trig t=17  cfg=0 amp=10967   X90(Q2)
                @2  done
```

Timing (clocks of 2 ns since the shot start; `qclk` equals physical time here
because nothing shifts it):

```
clock        0    5          17         29
             :    :           :          :
Q0.qdrv      .....[ X90(Q0)  ]...........
Q1.qdrv      .....[ X90(Q1)  ]...........
Q2.qdrv      .................[ X90(Q2)  ]
                              ^ join = max(5+12, 5+12) = 17
```

All durations are known at compile time, so the join becomes a number: core
`qubit/2` simply waits for `t=17`. The three cores never communicate. *RTL:* Q0
and Q1 strobe in the same clock, and Q2 strobes 12 clocks later.

### Example 2: a runtime loop, then another qubit

This program is valid current QD. `condition` is the last measurement of Q0, so
the trip count is decided at runtime (1, 2, …, or unbounded):

```odin
qubit Q0, Q1;
m := 1;                  // int register
do {
    X90(Q0);
    m = measure(Q0);     // runtime value: 0 or 1
} while m == 1;          // condition depends on the measurement
X90(Q1);                 // must start after the loop has finished
```

QubiC compiles a loop body once. At the end of every iteration it emits
`inc_qclk −Δ` (here Δ = 1397 clocks), so the next iteration reuses the same
timestamps (t = 9, 21, 321, …). Code after the loop is scheduled relative to
the loop's start time (`distproc/ir/passes.py:1020-1026`). That is correct on
a core whose `qclk` was rewound in every iteration, and only there.

#### Case A: Q0 and Q1 share one core

With `qdsl/tests/configs/shared_core.json`, `Q1.qdrv` is element 3 of core
`qubit/0`. **[compiler output]** (`--channels qdsl/tests/configs/shared_core.json`):

```
qubit_command0
  @0  pulse_reset
  @1  reg_alu_i        alu=id0 in0=#1 out=r0            m := 1
  @2  pulse_write_trig t=9    cfg=0 amp=3677            loop: X90(Q0)
  @3  pulse_write_trig t=21   cfg=1 amp=644             readout drive (Q0.rdrv)
  @4  pulse_write_trig t=321  cfg=6 amp=32767           readout window (Q0.rdlo, save_result)
  @5  idle             until t=1385                     wait until the bit is latched
  @6  alu_fproc_i      alu=id1 in0=#0 out=r0 func_id=0  m = measurement bit
  @7  inc_qclk_i       alu=add in0=#-1397               rewind qclk by one body
  @8  jump_cond_i      alu=eq in0=#1 in1=r0 ->@2        while m == 1
  @9  pulse_write_trig t=15   cfg=3 amp=15777           X90(Q1)
  @10 done
```

Word `@9` is fetched only after `jump_cond_i` falls through, so program order
alone guarantees the source order. `t=15` is in the frame that follows the last
rewind, which is physically after the loop.

```
physical time ->
qubit/0  [X90 Q0][rdrv][rdlo ......] idle  fproc rew jmp | [X90 Q0][rdrv] ... jmp | [X90 Q1]
         |<---------- iteration 1: m = 1 -------------->| |<- iteration k: m = 0 ->|
```

#### Case B: Q0 and Q1 on different cores (the naive lowering)

With the vendored mapping (Q0 → `qubit/0`, Q1 → `qubit/1`), **this is what QD
emits today**. **[compiler output]**:

```
qubit_command0                                     qubit_command1
  @0  pulse_reset                                    @0  pulse_reset
  @1  reg_alu_i        id0 #1 -> r0                  @1  pulse_write_trig t=15  X90(Q1)
  @2  pulse_write_trig t=9    X90(Q0)                @2  done
  @3  pulse_write_trig t=21   Q0.rdrv
  @4  pulse_write_trig t=321  Q0.rdlo
  @5  idle             until t=1385
  @6  alu_fproc_i      id1 -> r0  (func_id=0)
  @7  inc_qclk_i       #-1397
  @8  jump_cond_i      eq #1, r0 ->@2
  @9  done
```

The loop and `m` are scoped to Q0's core only, because QD scopes a loop to the
cores whose registers or pulses it uses (`qdsl/lower.py`, header). The `;`
before `X90(Q1)` becomes a barrier, and QubiC resolves it to the timestamp
`t=15`. On core 0, `t=15` means "15 clocks after the last rewind". Core 1 never
runs the loop and never rewinds, so for core 1 it means 15 clocks after the
shot start:

```
clock (since shot start)
              0    9   21                321                 1385    1397
qubit/0       :    [X90 Q0]                                    :   rewind, jump
                        [rdrv ............................]   :   -> iteration 2 if m = 1
                                          [rdlo ............] fproc
qubit/1       :      [X90 Q1]     <- fires during iteration 1, whatever m turns out to be
                     ^ t = 15
```

*RTL:* core 0 strobes `X90(Q0)` in cycle 2063 and core 1 strobes `X90(Q1)` in
cycle 2069. That is 6 clocks later, while Q0's pulse is still playing and long
before the measurement (cycle 3439). With a fixed 5-iteration counter loop,
core 0 strobes in cycles 58, 75, 92, 109 and 126, and core 1 in cycle 64.

Each per-core program is in perfect textual order, and the result still
violates the source order. Program order constrains only the core that holds
it. Across cores only timestamps order events, and a timestamp written after a
data-dependent loop means nothing to a core that did not run the loop. **The
source-level execution model therefore cannot be read off the textual order of
independently running per-core programs.** The compiler has to establish
cross-core ordering explicitly. Under rule 6, it must reject the program when
it cannot. Today it does neither (see "Known gap" above).

### Correct cross-core sequencing

#### A. Static scheduling

If the loop's duration is known, or a safe upper bound can be proven, core 1
schedules `X90(Q1)` after that bound. Example with a counter loop of exactly
five iterations:

```odin
qubit Q0, Q1;
n := 0;
do {
    X90(Q0);
    n += 1;
} while n < 5;           // trip count 5, provable at compile time
X90(Q1);
```

QD today lowers this like Case B: core 1 gets `t=15` and fires during the
first iteration (*RTL* numbers above). A static-bound lowering needs only a
different timestamp on core 1. The body is Δ = 17 clocks and the first
`X90(Q0)` is at t = 9, so the fifth starts at 9 + 4·17 = 77 and ends at 89:

```
qubit_command1   [conceptual: existing ISA, not emitted by QD]
  @0  pulse_reset
  @1  pulse_write_trig t=89  cfg=0 amp=15777   X90(Q1)   (QD emits t=15)
  @2  done
```

```
clock      9    26   43   60   77   89
qubit/0    [X]  [X]  [X]  [X]  [X]           X = X90(Q0), 12 clocks; body = 17 clocks
qubit/1                             [X90 Q1]
                                    ^ bound = 9 + 4*17 + 12
```

*RTL:* this is QD's binary with only the `cmd_time` field of core 1's word
(bits [36:5]) changed to 89. Core 0 strobes in cycles 58 to 126, and its last
pulse ends at 138. Core 1 strobes in cycle 138.

Current QD can already express the fixed-count case correctly by unrolling:
`#unroll for k in 0..<5 { X90(Q0); }` gives straight-line pulses at t = 5, 17,
29, 41, 53 and `X90(Q1)` at t = 65 **[compiler output]**. The cost is code size
(8192 words per core).

Limits: a bound must exist. Example 2's measurement loop has none, so static
scheduling alone would have to reject it. When a loop exits before its bound,
the next statement still waits for the bound: ordering is preserved, but the
gap varies. The bound must also cover the instruction costs (cycle table in
`docs/reference.md`).

#### B. Control-flow replication

Core 1 runs a copy of the loop's control flow without Q0's pulses. It reads the
same measurement bit, takes the same branches, and applies the same
`inc_qclk −Δ`, so both cores end the loop in the same `qclk` frame. Existing
hardware supports this. QubiC already replicates loops whose scope spans
several cores; QD just does not choose that scope for this program.

**[QubiC output, edited IR]**: Example 2 with the scope of `m` and of the loop
widened to {Q0, Q1}:

```
qubit_command0                                     qubit_command1
  @1  reg_alu_i        id0 #1 -> r0                  @1  reg_alu_i        id0 #1 -> r0
  @2  pulse_write_trig t=9    X90(Q0)
  @3  pulse_write_trig t=21   Q0.rdrv
  @4  pulse_write_trig t=321  Q0.rdlo
  @5  idle             until t=1385                  @2  idle             until t=1385
  @6  alu_fproc_i      id1 -> r0  (func_id=0)        @3  alu_fproc_i      id1 -> r0  (func_id=0)
  @7  inc_qclk_i       #-1397                        @4  inc_qclk_i       #-1397
  @8  jump_cond_i      eq #1, r0 ->@2                @5  jump_cond_i      eq #1, r0 ->@2
  @9  done                                           @6  pulse_write_trig t=15  X90(Q1)
                                                     @7  done
```

```
qubit/0  [X90][rdrv][rdlo .....] fproc rew jmp | [X90][rdrv][rdlo ...] fproc rew jmp |
qubit/1  ........ idle ......... fproc rew jmp | ........ idle ....... fproc rew jmp | [X90 Q1]
                                 ^ same bit, same clock                               ^ after exit
```

*RTL:* both cores make the FPROC request in the same clock (qclk 1388), and
`X90(Q1)` strobes in cycle 3471, after Q0's readout window and measurement. The
measurement here was 0, so the loop ran once. With the 5-iteration counter loop
replicated the same way, `X90(Q1)` strobes in cycle 153, after Q0's fifth pulse
in cycle 130.

Assumptions and limits:

- **Shared measurement availability.** Every replica must be able to read the
  bit that decides the loop. `fproc_meas` serves any measurement to any core
  (RTL check f5), but only on the same board (QD rejects cross-board feedback,
  `qdsl/test_cores.py`). It also returns the latched value **without waiting**
  for a new one, so each replica's read must be scheduled after the result is
  latched. The margin is 1 clock ("Measurement feedback timing" in
  `docs/reference.md`). Replicas read in the same clock, so they see the same
  value.
- **Timing alignment.** All replicas must use the same Δ and the same
  timestamps. QubiC computes one `delta_t` per loop (`passes.py:1024`). Each
  core's control instructions must fit inside the body.
- **Register state.** Every register the condition depends on must exist on
  every replica core and be updated identically there. This costs registers
  (16 per core, counted per core by QD) and instruction memory. A decision based
  on data that some replica cannot read cannot be replicated.

#### C. Runtime synchronization

Core 1 waits for a completion signal or rendezvous with core 0. This handles
unbounded loops, at the cost of stalling.

```
[proposed ISA: needs gateware and toolchain support]
qubit_command0                           qubit_command1
  loop: ...                                sync barrier=0        ; wait for core 0
        jump_cond ... -> loop              pulse_write_trig t=T  ; X90(Q1), qclk restarted at 0
  sync barrier=0                           done
  done
```

```
qubit/0  [iteration 1][iteration 2] ... [iteration k] sync |wait| qclk:=0 ...
qubit/1  sync |waiting .......................................| qclk:=0 ...[X90 Q1]
                                                             ^ ready raised for both in one clock
```

What exists, and what does not:

- **Exists in the ISA and core RTL:** opcode `sync` (`01110`, barrier id in
  bits [119:112], `distproc/command_gen.py:28, 341`). The control FSM goes
  DECODE → SYNC\_WAIT, waits for `sync_ready`, then QCLK\_RST zeroes `qclk`
  (`hdl/ctrl.v:347-349, 510-534`).
- **Missing:** the generated core instantiates `sync_iface`, but nothing drives
  `ready` (`gateware/top/src/dsp_coregen.py:349-355`). A core that executes
  `sync` stays in SYNC\_WAIT forever (RTL test `t7_sync_without_ready`,
  `rtl/isa_tb`). `proc.sv` never drives `sync.barrier`. The QubiC assembler
  rejects `sync` (`compiler/hand_asm.py`, case D), and the IR has no
  instruction for it.
- **Needed (proposed, not implemented):** a sync controller in the gateware
  that raises `ready` on all participants of a barrier in the same clock,
  barrier-id wiring, and assembler, IR and scheduler support. Because QCLK\_RST
  zeroes `qclk` on every participant, timestamps after a rendezvous would share
  an origin again, as long as the release reaches every core in the same clock.
  A one-sided completion flag (core 0 signals and never stalls; core 1 waits)
  has no counterpart in the ISA and would need new instructions.

The only runtime join across cores that exists today is the end of a shot:
`dsp.sv` waits for every core's `done` before the next shot.

### Physical time, `qclk`, and instruction time

- **Physical experiment time** is wall-clock time since the shot start. It is
  the only time the qubits care about. Each signal generator keeps its own
  free-running counter for the carrier phase, zeroed by `pulse_reset`
  (`gateware/dsp/element.sv`), so phase follows physical time.
- **Per-core `qclk`** is a *schedule coordinate*. It is 32 bits, +1 per clock,
  and reset at the shot start (`hdl/qclk.v`). A pulse fires when
  `qclk == t`. `inc_qclk` shifts it: loops rewind it by Δ in every iteration,
  and a runtime delay shifts it by a register value (patched compiler). After
  a data-dependent loop, `qclk` no longer equals physical time. Cores that
  rewound identically still agree with each other; cores that did not, disagree
  (Case B).
- **Instruction execution time** is the clocks the core spends executing:
  `reg_alu` 4, `jump_cond` 6, `alu_fproc` 6, `pulse_write_trig` ≥ 3 (table in
  `docs/reference.md`). Instructions run ahead of the pulses and stall on the
  next timed pulse. A core that reaches a timestamp late never fires it and
  hangs (RTL test t3), so the scheduler must leave room for every instruction.

**Under consideration (not in hardware, ISA or QD):** a *synchronized,
monotonically increasing* counter per core. It would be reset together on all
cores at the shot start, never rewound or shifted, and readable by the program
(e.g. a QD `now()`, also only proposed). It would give every core a common
reference to physical time that survives loops and runtime delays. Absolute
timestamps would then be possible, a core could measure how far it lags, and
traces from different cores would be directly comparable.

**A common time reference does not by itself guarantee completion.** It tells
core 1 what time it is, not whether core 0's loop has finished. When the loop's
duration depends on a measurement, its end time is a runtime value, known only
where the decisions are made. Core 1 still needs a bound (A), the same decisions
(B), or a signal (C). A shared counter would make re-aligning after B or C
easier, but it does not replace them.

### Summary: current, possible with existing hardware, needs extensions

| Ordering problem | Current QD compiler | Existing QubiC hardware, different lowering | Needs ISA / RTL extension |
|---|---|---|---|
| Straight-line code across cores (Example 1) | correct, static timestamps | — | — |
| Branches that overlap without a common start (`parallel`) | not expressible (`par` forces a common start) | yes, it is only a schedule | — |
| Fixed-count loop, then another core | correct only with `#unroll`; a runtime loop is lowered naively | static bound (A), replication (B) | — |
| Measurement-dependent loop, then another core | naive lowering, ordering violated | replication (B), if every replica can read the bit | rendezvous (C): gateware sync controller + toolchain |
| Monotonic synchronized counter, `now()` | no | no (`qclk` is rewound) | yes |

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
machine code, with strict `;` sequencing across processor cores, explicit
`parallel` blocks, and hardware-aware static checks. See `qdsl/README.md`.

```sh
python -m qdsl qdsl/examples/ex7_two_qubits.qd   # static schedule
python -m qdsl.run_tests                          # 17 examples, 19 errors, core + sequencing tests
rtl/qd_tb/run_demo.sh                             # QD -> machine code -> RTL
python rtl/multi_tb/run_multi.py                  # multi-core + shots on RTL
python rtl/multi_tb/run_seq.py                    # source order vs physical pulse order on RTL
# every QD snippet in the docs parses; programs compile to the listed words
python tools/check_doc_dsl.py README.md docs/reference.md qdsl/README.md
```

`setup.sh` installs a **patched** copy of `distproc` (see `patches/README.md`);
the vendored sources themselves are never modified.

## Status

QD is a v0 prototype. **Implemented** is what `qdsl/README.md` describes:
- declarations, procs, `do`/`for`/`#unroll`/`if`, and measurement feedback;
- the execution model below: strictly sequential `;` on every processor core,
  and `parallel { A | B }` with a join;
- runtime delays via the patched compiler;
- mapping to physical processor cores from the channel configuration;
- the listed static checks.

The tests cover these: `python -m qdsl.run_tests` (examples, error cases, core
and sequencing tests) and the RTL runs above.

**Not implemented** (planned or open):
- the items under "Not yet" in `qdsl/README.md`;
- runtime synchronization between cores;
- synchronized physical-time counters and a `now()` expression;
- automatic static bounds for loops.

These are design proposals, marked as such below.

## Execution model: sequential and parallel programs

> **Status.** The rules below are **implemented** (static scheduling and
> control-flow replication, on the existing QubiC ISA). Runtime
> synchronization (approach C), synchronized physical-time counters and
> `now()` remain **proposals**: no hardware, ISA or compiler support exists.
> Programs in `odin` blocks compile with the current compiler
> (`python tools/check_doc_dsl.py README.md`).

Every listing below is tagged:

- **[compiler output]**: produced by the current compiler, `python -m qdsl
  FILE --bin` (QD front end + the QubiC compiler and assembler as installed by
  `setup.sh`). The decoded column comes from this repo's decoder
  (`qdsl/backend.py`).
- **[before the fix]**: what QD emitted until the sequencing fix (commit
  `1825b18`), kept to show the failure.
- **[conceptual]**: hand-written with existing instructions, not emitted by QD.
- **[proposed ISA]**: needs hardware or toolchain support that does not exist.

Timing numbers marked *RTL* come from `python rtl/multi_tb/run_seq.py` (in the
test suite) or, where stated, from one-off runs on the same 3-core simulation.

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

### Rules (implemented)

1. **Sequential source means sequential execution.** In `A; B;`, every quantum
   operation of `A` has completed before any of `B` begins: all of `A`'s pulses
   have ended and all of its runtime decisions are taken. This holds on every
   physical core, including when `A` and `B` run on different cores.
2. **`parallel { A | B }` declares independence.** The branches may overlap,
   but nothing promises that they start together. The schedule may start them
   together (distinct cores), issue them in turn (shared core), or serialize
   them (see "Runtime loops in parallel branches"). Branches must use disjoint
   qubits, and a register written in one branch must not be used in another.
3. **The end of a `parallel` block is a join.** The next sequential statement
   starts only after every branch has completed.
4. **A join is a guarantee, not an instruction.** It constrains when later
   operations may happen. No runtime barrier is emitted.
5. **The compiler chooses the mechanism**: static scheduling, or control-flow
   replication. Runtime synchronization (C) is not available on the current
   hardware.
6. **If the compiler cannot guarantee the ordering, compilation fails.** It
   never silently weakens the semantics.
7. **`parallel` replaces `par`.** `par { ... }` is a syntax error that points
   to `parallel`. Its "start together" rule is gone. How a program would
   request a simultaneous start (e.g. for an aligned readout) is an open
   question.

### Example 1: `parallel`, then a sequential statement

```odin
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
`qubit/2` simply waits for `t=17`. The three cores never communicate. On
distinct cores both branches start at the barrier before the block; that is a
property of the schedule, not a promise of `parallel`.

When the qubits share a core (`qdsl/tests/configs/one_core.json`, all three on
`qubit/0`), the core issues the branches in turn: `X90(Q0)` at t = 5,
`X90(Q1)` at t = 8 (pulses on one core are ≥ 3 clocks apart), and `X90(Q2)` at
t = 20, after both have ended. *RTL* (`run_seq.py`): `par_three_cores`,
`par_one_core`, and `par_pair_core` (Q0 and Q1 share a core, Q2 has its own).
All of them start Q2's pulse exactly when the later branch ends.

### Example 2: a runtime loop, then another qubit

`condition` is the last measurement of Q0, so the trip count is decided at
runtime (1, 2, …, or unbounded):

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

#### Case B: Q0 and Q1 on different cores

**[before the fix]** With the vendored mapping (Q0 → `qubit/0`, Q1 →
`qubit/1`), QD used to scope the loop to Q0's core only:

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

On core 0, `t=15` means "15 clocks after the last rewind". Core 1 never runs
the loop and never rewinds, so for core 1 it meant 15 clocks after the shot
start:

```
clock (since shot start)
              0    9   21                321                 1385    1397
qubit/0       :    [X90 Q0]                                    :   rewind, jump
                        [rdrv ............................]   :   -> iteration 2 if m = 1
                                          [rdlo ............] fproc
qubit/1       :      [X90 Q1]     <- fired during iteration 1, whatever m turned out to be
                     ^ t = 15
```

Each per-core program is in perfect textual order, and the result still
violates the source order. Program order constrains only the core that holds
it. Across cores only timestamps order events, and a timestamp written after a
data-dependent loop means nothing to a core that did not run the loop. **The
source-level execution model therefore cannot be read off the textual order of
independently running per-core programs.** The compiler has to establish
cross-core ordering explicitly, or reject the program.

**[compiler output]** now: control-flow replication (approach B below). Core
1 runs the loop's control flow, reads the same measurement bit in the same
clock, and rewinds with core 0:

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

*RTL* (`run_seq.py`, measurement bits forced to 1, 1, 0, so 3 iterations; pulse
intervals in clocks since the shot start):

| | Q0's loop ends | `X90(Q1)` starts |
|---|---|---|
| before the fix, two cores | 4122 | **22** (during iteration 1) |
| after the fix, two cores | 4122 | 4213 |
| one shared core (Case A) | 4122 | 4213 |
| after the fix, bit forced to 0 (1 iteration, same binary) | 1328 | 1419 |
| 5-iteration counter loop, before / after | 96 | **22** / 107 |

### Correct cross-core sequencing

#### A. Static scheduling (not automatic)

If the loop's duration is known, or a safe upper bound can be proven, core 1
could schedule `X90(Q1)` after that bound without running the loop. QD does not
compute such bounds; it replicates every runtime loop (B), including counter
loops with a fixed trip count. For the 5-iteration counter loop, the body is
Δ = 17 clocks and the first `X90(Q0)` is at t = 9. The fifth starts at
9 + 4·17 = 77 and ends at 89:

```
qubit_command1   [conceptual: existing ISA, not emitted by QD]
  @0  pulse_reset
  @1  pulse_write_trig t=89  cfg=0 amp=15777   X90(Q1)
  @2  done
```

```
clock      9    26   43   60   77   89
qubit/0    [X]  [X]  [X]  [X]  [X]           X = X90(Q0), 12 clocks; body = 17 clocks
qubit/1                             [X90 Q1]
                                    ^ bound = 9 + 4*17 + 12
```

*RTL* (one-off): the old binary with only the `cmd_time` field of core 1's word
(bits [36:5]) changed to 89. Core 0's last pulse ends at cycle 138, and core 1
strobes in cycle 138.

A program can get static scheduling today by unrolling: `#unroll for k in
0..<5 { X90(Q0); }` gives straight-line pulses at t = 5, 17, 29, 41, 53 and
`X90(Q1)` at t = 65 **[compiler output]**. The cost is code size (8192 words
per core). A measurement-dependent loop has no bound.

#### B. Control-flow replication (implemented)

Every core with a quantum operation after a runtime loop runs a copy of the
loop's control flow, without the other cores' pulses (`qdsl/lower.py`,
`later`). It reads the same registers and measurement bits, takes the same
branches, and applies the same `inc_qclk −Δ`. So all participating cores end
the loop in the same `qclk` frame. "After" includes the rest of every enclosing
statement sequence and, inside an enclosing loop, that loop's whole body (its
next iteration). It does not include other branches of a `parallel` block.
Cores with nothing after the loop do not run it. Machine words of all existing
examples are unchanged by this rule.

Assumptions and limits, each enforced or checked:

- **Shared measurement availability.** Every replica must be able to read the
  bit that decides the loop. `fproc_meas` serves any measurement to any core
  (RTL check f5), but only on the same board. A replica on another board is
  rejected with the FPROC diagnostic and the reason it takes part. The read
  returns the latched value **without waiting** for a new one, so it relies on
  the `hold` before it (1 clock of margin, "Measurement feedback timing" in
  `docs/reference.md`). Replicas read in the same clock (*RTL*: qclk 1388 on
  both cores), so they see the same value.
- **Timing alignment.** QubiC computes one `delta_t` per loop
  (`passes.py:1024`), so all replicas rewind by the same amount. QD checks that
  every core that runs a loop has run the same runtime loops and delays before
  it, so its `qclk` maps to the same physical time (`_check_frames`).
- **Register state.** The registers a condition depends on are replicated to
  every core of the loop and updated there by the same instructions. They count
  against the 16 registers per core (checked), and the copy costs instruction
  memory.

#### Runtime loops in parallel branches

```odin
qubit Q0, Q1, Q2;
m0 := 1;
m1 := 1;
parallel {
    do { X90(Q0); m0 = measure(Q0); } while m0 == 1;
|
    do { X90(Q1); m1 = measure(Q1); } while m1 == 1;
}
```

Without a following statement this compiles: each core runs its own loop, and
the join is the end of the shot. Add `X90(Q2);` after the block and core 2 would
have to follow both loops at the same time. A core runs its control flow in
program order, so it would evaluate the second loop's condition only after the
first loop, at the wrong time. **Rejected**:

```
error: cannot guarantee the order of the loop: processor cores qubit/2 and qubit/1 both
take part, but only qubit/2 has run the runtime loop at line 8 before; qubit/2 takes part
because Q2 must wait for it
```

(`qdsl/errors/e18_parallel_runtime_loops.qd`.) The same check accepts
programs where one core can follow both loops in turn. With `measure(Q1);`
after the block, core 1 follows Q0's loop and then runs its own, so the
branches run one after the other. *RTL* `par_loops_serialized`: Q1's loop starts
at cycle 2820, after Q0's loop ends at 2729. Two loops on one shared core are
also accepted. A loop in one branch and straight-line code in the other overlap
(*RTL* `par_loop_and_static_then_join`: `X90(Q1)` at cycle 22 during the loop,
and `X90(Q2)` at 4225, after it). Joining two concurrent runtime loops would
need approach C.

#### C. Runtime synchronization (proposal, not implemented)

Core 1 waits for a completion signal or rendezvous with core 0. This would
handle a core that follows concurrent loops, at the cost of stalling.

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
  (Case B before the fix). QD's static schedule (`python -m qdsl FILE`) prints
  times in this coordinate. After a loop they are in the rewound frame: each
  iteration the loop runs moves them later by the body length.
- **Instruction execution time** is the clocks the core spends executing:
  `reg_alu` 4, `jump_cond` 6, `alu_fproc` 6, `pulse_write_trig` ≥ 3 (table in
  `docs/reference.md`). Instructions run ahead of the pulses and stall on the
  next timed pulse. A core that reaches a timestamp late never fires it and
  hangs (RTL test t3), so the scheduler must leave room for every instruction.

**Trigger slack, measured.** The testbench records, for every timed
instruction, its timestamp minus `qclk` when the core reaches it. Across all
`run_seq.py` and `run_multi.py` programs the minimum is 0 to 3 clocks and never
negative. QubiC's cycle model is exact on this RTL, so there is no margin. The
guarantee is only as good as that model. A cost it does not count would make a
trigger late, and a late trigger hangs the core silently. One such cost is the
extra `pulse_write` word of a pulse with two register parameters: QD warns
about it, although it did not cause a late trigger in the cases tried.

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

### Summary

| Ordering problem | Current QD compiler | Remaining options | Needs ISA / RTL extension |
|---|---|---|---|
| Straight-line code across cores (Example 1) | static timestamps | — | — |
| `parallel` branches on distinct or shared cores | static scheduling; a shared core issues the branches in turn | — | — |
| Runtime loop (fixed count or measurement-dependent), then another core | control-flow replication (B) | static bound (A) would save the copy for provable trip counts | — |
| A core that must follow two concurrent runtime loops (parallel branches) | **rejected** | sequential loops, `#unroll` | rendezvous (C): gateware sync controller + toolchain |
| A replica that cannot read the loop's measurement (other board) | **rejected** | — | cross-board result sharing |
| Monotonic synchronized counter, `now()` | no | — | yes |

# QD on QubiC: what works, what is proposed

QD is an exploratory front end for QubiC, the open-source quantum control
system from Lawrence Berkeley National Laboratory. It compiles a small
Odin-flavoured language (QD) to the QubiC intermediate representation (IR), then
runs the unmodified QubiC compiler and assembler down to 128-bit machine
words. Everything below runs without field-programmable gate array (FPGA)
hardware: on the compiler, and on cycle-accurate simulations of QubiC's register-transfer-level (RTL) hardware
description.

The document has two parts, kept strictly apart:

- **Part I: Implemented and verified.** Every QD program in it compiles with
  the stated channel configuration (`python tools/check_doc_dsl.py
  docs/interview-overview.md`). Every listing tagged **[compiler output]** is
  verbatim output of the current compiler. **[RTL]** marks results of RTL
  simulation in this repository.
- **Part II: Proposed extensions.** Design ideas. Nothing in Part II exists in
  QD, the QubiC instruction set architecture (ISA) or the gateware unless it
  says so. Proposed syntax and instructions are tagged **[hypothetical]**.

Reading time is about 15 minutes; Appendix A lists the verification runs.

---

## Five-Minute Interview Walkthrough

1. **Why QD.** QubiC programs are lists of IR dictionaries. The IR has no
   notion of "this statement, then that one": pulses on different channels
   start together unless a `barrier` says otherwise, and the meaning of a
   program depends on how qubits map to processor cores. I wanted a language
   whose sequencing does not depend on that mapping, and checks that know the
   hardware (16 registers per core, 3-clock pulse spacing, the measurement
   latency), so that errors appear at the source line instead of deep in a
   compiler pass or as a hang on hardware.
2. **How it maps onto QubiC.** A qubit has three channels: drive (`qdrv`),
   readout drive (`rdrv`) and readout local oscillator (`rdlo`). Each channel
   is an element of a *processor core*. A core is a small in-order processor
   with its own instruction stream; it triggers its elements at timestamps of
   its own clock `qclk`. Cores share no memory and exchange no messages. They
   agree on time only because they leave reset together and follow a static
   schedule. QD reads the channel-to-core wiring from QubiC's channel
   configuration, and `place` declarations state that wiring in the source.
3. **What works.** Declarations, gates, raw pulses, measurement, loops,
   branches on measurements, runtime delays, `parallel` blocks with a join,
   and `place`. All of it compiles to QubiC machine code; the sequencing
   programs run on a 3-core RTL simulation with the measurement-result unit
   and the shot sequencer.
4. **One interesting limitation, shown on RTL.** QubiC compiles a loop body
   once and rewinds `qclk` at the end of every iteration. Code after the loop
   is scheduled from the loop's start time. That is right on the core that ran
   the loop and wrong on every other core: with the earlier QD, `X90(Q1)` after
   a measurement-dependent loop on Q0 fired at cycle 22 while the loop ran
   until cycle 4122. QD now fixes this in the compiler (the other core runs a
   copy of the loop's control flow). What it cannot fix without hardware:
   one core following two *concurrent* runtime loops. QD rejects that program.
5. **The design questions.** How far can the compiler go alone (static
   scheduling, bounds, replication), and where does the hardware have to
   help? QubiC's ISA already has a `sync` opcode, but the gateware never
   releases it. A missed timestamp is not detected: the trigger compares for
   equality, so a late pulse waits for the 32-bit counter to wrap. And the
   whole guarantee rests on QubiC's cycle model being exact, which on this RTL
   it is, with zero clocks of margin.

---

## 1. Architecture

```text
source file (.qd)
  │  parser            Lark LALR(1) grammar (qdsl/grammar.lark) -> abstract syntax tree (qdsl/syntax.py)
  ▼
semantic analysis      names, types, constants, inlining, place checks (qdsl/sema.py)
  │                    -> QD's mid-level IR: timed ops, classical ops, structured control flow
  ▼
core mapping           channel configuration -> CoreModel: channel -> CoreId (qdsl/cores.py)
  │
  ▼
scheduling / lowering  scope inference, barriers, loop replication, checks (qdsl/lower.py)
  │                    -> QubiC IR (list of dicts)
  ▼
QubiC compiler         14 IR passes incl. as-soon-as-possible scheduling (vendor/.../distproc, patched copy)
  ▼
QubiC assembler        per-core assembly -> 128-bit words, one instruction memory per core
  ▼
processor cores        each core runs its own word stream and triggers its elements;
                       elements drive DACs and read ADCs through the gateware's wiring
```

### The objects involved

| Object | What it is | Defined by |
|---|---|---|
| **Logical qubit** (`Q0`) | a name in the program; owns calibrated gates and frequencies | `qubitcfg.json` (calibration, `--qchip`) |
| **Channel** (`Q0.qdrv`, `Q0.rdrv`, `Q0.rdlo`) | one signal generator ("element") of a processor core | channel configuration (`--channels`) |
| **Processor core** | in-order processor: 16 × 32-bit registers, one arithmetic logic unit (ALU), a 32-bit clock `qclk`, its own instruction memory; up to 4 elements | gateware build; addressed by `CoreId(board_name, core_name, core_ind)` |
| **Digital-to-analog converter (DAC)**, **analog-to-digital converter (ADC)** | the converters of the radio-frequency (RF) board | gateware build (`gateware/top/zcu216_14_2/dsp_config.yaml`) |

The three channels of a qubit:

| Channel | Name | Element type | Role |
|---|---|---|---|
| `qdrv` | Qubit Drive | `rf` | control pulses that rotate the qubit, e.g. the 24 ns pulse of `X90` |
| `rdrv` | Readout Drive | `rf` | the pulse that excites the qubit's readout resonator |
| `rdlo` | Readout Local Oscillator | `rf_mix` | the digital reference that demodulates and integrates the returning ADC signal into one result bit |

**Three configuration layers, three owners.**

- *Calibration data* (`qubitcfg.json`): what `X90(Q0)` or `read` means as
  pulses, frequencies, amplitudes, durations. It says nothing about cores.
- *Channel configuration* (`channel_config.json`): which core and which
  element each channel is (`core_ind`, `core_name`, `board_name`,
  `elem_ind`), and the names of its memories. This is the wiring the compiler
  sees. In the vendored file, Q*n*'s channels are elements 0, 1, 2 of core *n*.
- *FPGA gateware*: which element feeds which converter. In the vendored
  ZCU216 build every core has one `qdrv`, `rdrv` and `rdlo`; `qdrv` of core *i*
  drives DAC *i*; the `rdrv` elements of cores 0-6 are **summed** onto DAC 14
  and those of cores 7-13 onto DAC 15; the `rdlo` elements of cores 0-6 mix
  ADC input 0, cores 7-13 ADC input 1 (`dsp_config.yaml:16-46`). A processor
  core is therefore not an analog channel: several cores share one DAC or ADC.

**Two notions of time.**

- `qclk` is per core and a *schedule coordinate*. It counts clocks (2 ns at
  the 500 MHz FPGA clock), starts at 0 when the shot starts (`hdl/qclk.v`),
  and is moved by `inc_qclk`. A timed instruction fires when `qclk == t`
  (`hdl/proc.sv:138`).
- *Physical time* is wall-clock time since the shot start; it is what the
  qubits see. Within one shot, events on different cores are ordered only by
  their timestamps, and `qclk` equals physical time only until something
  shifts it (loops, runtime delays).

The ISA, in the instructions this document uses (full table in
`docs/reference.md`, "Instruction set"):

| Instruction | Effect | Cost on RTL [RTL, `rtl/isa_tb` t1] |
|---|---|---|
| `pulse_write_trig t=…` | write pulse parameters, wait until `qclk == t`, strobe the element | ≥ 3 clocks |
| `reg_alu`, `reg_alu_i` | register ALU operation | 4 |
| `inc_qclk_i` | `qclk += imm` | 4 |
| `jump_i`, `jump_cond_i` | jump, conditional jump on a register compare | 4, 6 |
| `idle until t` | wait until `qclk == t` | — |
| `alu_fproc_i`, `jump_fproc_i` | read a measurement result from FPROC, use it / branch on it | 6, 8 |
| `pulse_reset`, `done` | zero the elements' phase counters; stop | — |
| `sync` | exists in the ISA (opcode `01110`), unusable: see Part II-C | — |

FPROC is QubiC's function processor; in this build it is the
measurement-result unit `fproc_meas.sv`, shared by all cores of a board.

---

# Part I: Implemented and verified

## 2. The language in one program

```odin
qubit Q0, Q1;                       // calibrated qubits
place Q0 on board0.core0;           // wiring, checked against --channels
place Q1 on board0.core1;

N :: 5;                             // compile-time constant
a : amp = 0.1;                      // register (int, amp, phase, time)
n := 0;                             // register, inferred int

pi2 :: proc(q: qubit) { X90(q); X90(q); }    // always inlined

do {                                // hardware loop (post-test)
    pulse(Q0.qdrv, freq = Q0.freq, amp = a, width = 24 ns,
          env = cos_edge_square(0.25));
    measure(Q0);
    a += 0.1;
    n += 1;
} while n < N;

if measure(Q0) == 1 { pi2(Q0); }    // feedback on a measurement
parallel { X90(Q0); | X90(Q1); }    // independent branches, then a join
delay(10 us);
```

Also implemented: `for` (pre-test and counter loops), `#unroll for`
(compile-time loops), `m := measure(Q0);`, `barrier(...)`, `gate("name",
...)` for calibration names that are not identifiers, two-qubit gates such as
`CNOT(Q1, Q0)`, and runtime delays `delay(tau)` with a `time` register (via a
patch to the QubiC compiler, `patches/`). The full list of constructs and
checks is in `qdsl/README.md`.

**Limitations.** No frequency registers, no timing expressions such as
`duration(...)`, one error per compiler run, at most one `+` or `-` per
runtime statement (one ALU operation per instruction).

## 3. A gate followed by a measurement (example 1)

```odin
qubit Q0;
place Q0 on board0.core0;

X90(Q0);            // a gate: one pulse on Q0.qdrv
m := measure(Q0);   // a measurement: Q0.rdrv and Q0.rdlo, result into m
```

**[compiler output]** (`python -m qdsl FILE --bin`, then without options for the schedule):

```text
qubit_command0  (7 words)
  @0    b0000000000000000000000000000000  pulse_reset
  @1    900803000200004008397600000000a0  pulse_write_trig t=5 cfg=0 amp=3677 freq=0 phase=0 env_word=49152
  @2    9008fa0002000040080a122000000220  pulse_write_trig t=17 cfg=1 amp=644 freq=0 phase=0 env_word=4096000
  @3    9008fa00023c53c009fffec0000027a0  pulse_write_trig t=317 cfg=6 amp=32767 freq=0 phase=30887 env_word=4096000
  @4    c000000000000000000000000000aca0  idle             until t=1381
  @5    46000000000000000000000000000000  alu_fproc_i      alu=id1 in0=#0 out=r0 func_id=0
  @6    a0000000000000000000000000000000  done

   start      [us]  channel     len  source     block
       5     0.010  Q0.qdrv      12  Q0X90      block_0
      17     0.034  Q0.rdrv    1000  Q0read     block_0
     317     0.634  Q0.rdlo    1000  Q0read     block_0
    1381     2.762  idle          0  wait for measurement block_0
```

**Physical execution.** `cfg` selects the element (`cfg[1:0]`: 0 = `qdrv`,
1 = `rdrv`, 2 = `rdlo`); `cfg=6` is element 2 with the save-result bit. The
X90 is one 12-clock (24 ns) pulse. The readout drive excites the resonator for
1000 clocks (2 µs), and the demodulation window on `rdlo` opens 300 clocks
later, as the calibration specifies. The result reaches FPROC some time after
the window closes; the compiler waits a fixed hold of 64 clocks after the
window end (1317 + 64 = 1381) and then reads it (`alu_fproc_i`, `func_id` =
`core_ind` of `Q0.rdlo`). Amplitudes, frequencies and envelopes come from
`qubitcfg.json`; the envelope samples live in element memories written at
load time.

**Evidence.** Same instruction sequence as the active-reset example
`ex6_active_reset.qd`, which `rtl/qd_tb/run_demo.sh` runs on the processor
RTL: with measurement 1 the X90s fire at `qclk` 1382/1394, with 0 they are
skipped, and the final readout fires at 1406 either way **[RTL]**.

**Limitations.** The 64-clock hold is a constant of QubiC's `FPGAConfig`. On
the RTL, 63 clocks still read the fresh bit and 62 read the previous one
(**[RTL]**, `rtl/meas_tb/run_checks.py`): one clock of margin. FPROC has no
"fresh" flag (§9).

## 4. Placement: channels, cores, `place`

```odin
qubit Q0, Q1;
place Q0 on board0.core0;           // all of Q0's channels
place Q1.qdrv on board0.core1,      // channel by channel, one statement
      Q1.rdrv on board0.core1,
      Q1.rdlo on board0.core1;
X90(Q0);
X90(Q1);
```

**Naming.** `BOARD.coreN` is the core with `core_ind` N on `BOARD`, the
configuration's `board_name`; the unnamed board is `board0`. If several core
types (`core_name`) on a board share an index, the type is named too:
`board0.aux.core0`. Resolution is built on the existing `CoreId`
(`CoreModel.resolve_core`, `qdsl/cores.py`).

**Semantics.** The channel configuration fixes the wiring, so `place` is a
requirement **checked at compile time**. It emits no code and cannot rewire.
Unknown qubits, channels, boards or cores, ambiguous core names, conflicting
placements, and placements the configuration does not have are rejected:

**[compiler output]** (`python -m qdsl qdsl/errors/e22_place_wiring.qd`):

```text
qdsl/errors/e22_place_wiring.qd:5:27: error: cannot place Q1 on board0.core0: the channel configuration (vendor/software/examples/channel_config.json) wires Q1.qdrv to board0.core1, Q1.rdrv to board0.core1, Q1.rdlo to board0.core1
    place Q0 on board0.core0, Q1 on board0.core0;
                              ^
  hint: place states where a channel is wired; it cannot rewire it. Write
          place Q1 on board0.core1;
        or compile with a channel configuration that has the wiring you want (--channels)
```

**Evidence.** `qdsl/test_placement.py` (25 tests); all 17 pre-existing
examples compile to identical machine words with and without their
placements, and identical to the compiler before `place` existed.

**Limitations.** `place` cannot *choose* a wiring; partial placement is
allowed (unplaced channels follow the configuration); only placement
diagnostics use the `board0.coreN` names (others print `qubit/0`).

## 5. One qubit across cores (example 2)

`qdsl/tests/configs/spread_qubit.json` puts Q1's drive on core 1 and its
readout channels on core 2:

```odin
// compile with --channels qdsl/tests/configs/spread_qubit.json
qubit Q0, Q1;
place Q0 on board0.core0;
place Q1.qdrv on board0.core1,
      Q1.rdrv on board0.core2,
      Q1.rdlo on board0.core2;

X90(Q1);
measure(Q1);
X90(Q0);
```

**[compiler output]**, excerpt (pulse words only, fields after `amp` cut):

```text
qubit_command0  (3 words)
  @1    9008030002000040083976000000a4a0  pulse_write_trig t=1317 cfg=0 amp=3677 ...       X90(Q0)
qubit_command1  (3 words)
  @1    900803000200004008f68600000000a0  pulse_write_trig t=5 cfg=0 amp=15777 ...         X90(Q1)
qubit_command2  (4 words)
  @1    9008fa00020000400809b60000000220  pulse_write_trig t=17 cfg=0 amp=621 ...          Q1.rdrv
  @2    9008fa000200004009fffea0000027a0  pulse_write_trig t=317 cfg=5 amp=32767 ...       Q1.rdlo
```

(`@0 pulse_reset` and the final `done` of each core omitted; the trailing
labels are mine.) One logical gate sequence becomes three independent
instruction streams. The order "X90, then readout, then X90 on Q0" exists only
in the timestamps: 5 + 12 = 17 and 317 + 1000 = 1317.

**Evidence [RTL].** Run through the 3-core sequencing harness (scratch driver
around `rtl/multi_tb/run_seq.py`, Appendix A): pulses at cycles
Q1.qdrv [12, 24), Q1.rdrv [24, 1024), Q1.rdlo [324, 1324), Q0.qdrv
[1324, 1336), trigger slack ≥ 3 clocks. RTL cycles are the compiled
timestamps + 7 (shot-start and strobe latency).
**Limitation of that evidence:** the testbench models element 2 of each core
as the demodulator, but this configuration puts `Q1.rdlo` on element 1; the
run verifies the cores' strobe timing, not the demodulated result.

## 6. Qubits sharing a core vs. independent cores (examples 3 and 4)

The same program, compiled for two wirings:

```odin
qubit Q0, Q1, Q2;
place Q0 on board0.core0, Q1 on board0.core1, Q2 on board0.core2;

parallel {
    X90(Q0);
|
    X90(Q1);
}
X90(Q2);
```

```odin
// compile with --channels qdsl/tests/configs/one_core.json
qubit Q0, Q1, Q2;
place Q0 on board0.core0, Q1 on board0.core0, Q2 on board0.core0;

parallel {
    X90(Q0);
|
    X90(Q1);
}
X90(Q2);
```

**[compiler output]**, pulse words only, reformatted side by side:

```text
three cores                                   one core (elements 0, 1, 2 of core 0)
qubit_command0 @1 t=5  cfg=0  X90(Q0)         qubit_command0 @1 t=5   cfg=0  X90(Q0)
qubit_command1 @1 t=5  cfg=0  X90(Q1)                        @2 t=8   cfg=1  X90(Q1)
qubit_command2 @1 t=17 cfg=0  X90(Q2)                        @3 t=20  cfg=2  X90(Q2)
```

**[RTL]** (`run_seq.py`, cycles since shot start):

```text
three cores (par_three_cores)          one core (par_one_core)
Q0.qdrv  [12, 24)                      Q0.qdrv  [12, 24)
Q1.qdrv  [12, 24)                      Q1.qdrv  [15, 27)   3 clocks later: one pulse word per 3 clocks
Q2.qdrv  [24, 36)  = max end           Q2.qdrv  [27, 39)   = max end
```

**Why the shared core is easy.** One core executes one instruction stream in
program order, and its timestamps are in one `qclk` frame. Anything that
follows in the stream is also later in time, as long as its timestamp is.
**Why independent cores are harder.** Each core sees only its own stream.
The join "after both branches" exists only because the compiler computed the
number 17 and wrote it into core 2's program. This is static scheduling; it
works because every duration is known at compile time.

## 7. A runtime loop followed by another core (example 5)

This is the problem that motivated most of the sequencing work.

```odin
qubit Q0, Q1;
place Q0 on board0.core0, Q1 on board0.core1;
m := 1;
do {
    X90(Q0);
    m = measure(Q0);        // runtime value
} while m == 1;             // trip count decided at runtime
X90(Q1);                    // intended: after the loop has ended
```

### 7.1 The known problem, reproduced on RTL

QubiC compiles a loop body once. At the end of every iteration it emits
`inc_qclk −Δ` (Δ = 1397 clocks here), so every iteration reuses the same
timestamps; code after the loop is scheduled relative to the loop's *start*
(`distproc/ir/passes.py:1020-1026`). That is correct on a core whose `qclk`
was rewound in every iteration, and only there.

**[compiler output] of the earlier QD** (commit `b06698c`, before the fix;
source without the `place` line, which did not exist yet; reformatted side by
side, pulse fields after `amp` cut):

```text
qubit_command0  (10 words)                               qubit_command1  (3 words)
  @0  pulse_reset                                          @0  pulse_reset
  @1  reg_alu_i        alu=id0 in0=#1 in1=r0 out=r0        @1  pulse_write_trig t=15 cfg=0 amp=15777   X90(Q1)
  @2  pulse_write_trig t=9 cfg=0 amp=3677                  @2  done
  @3  pulse_write_trig t=21 cfg=1 amp=644
  @4  pulse_write_trig t=321 cfg=6 amp=32767
  @5  idle             until t=1385
  @6  alu_fproc_i      alu=id1 in0=#0 out=r0 func_id=0
  @7  inc_qclk_i       alu=add in0=#-1397
  @8  jump_cond_i      alu=eq in0=#1 in1=r0 ->@2
  @9  done
```

**[RTL]**, reproduced for this document: that compiler (`qdsl/` of `b06698c`)
in a scratch worktree, driven by `rtl/multi_tb/run_seq.py` of commit
`1825b18`, measurement bits forced to 1, 1, 0 (three iterations). The diagram is drawn from the measured pulse
intervals; the harness output follows it verbatim:

```text
cycle:      0   16 22    1028 1328 1413        2810                4122
            :   :  :        :    :    :           :                   :
core 0      [X90][rdrv ....][rdlo ...]  [X90][rdrv][rdlo] [X90][rdrv][rdlo]   loop ends at 4122
core 1         [X90(Q1)]   <- fires at cycle 22, during iteration 1

  FAIL loop_meas_two_cores
         ORDER VIOLATED: Q1.qdrv starts at 22, before Q0.qdrv/Q0.rdrv/Q0.rdlo ends at 4122
  FAIL loop_count_two_cores           (5-iteration counter loop)
         ORDER VIOLATED: Q1.qdrv starts at 22, before Q0.qdrv ends at 96
  ok   loop_meas_one_core             (Q1.qdrv on core 0: shared_core.json)
         Q1.qdrv starts at 4213 >= end of Q0.qdrv/Q0.rdrv/Q0.rdlo at 4122
```

Each per-core program is in perfect textual order, and the result still
violates the source order. `t=15` on core 1 means "15 clocks after the shot
start", because core 1 never ran the loop and never rewound. Program order
constrains only the core that holds the program; across cores, only
timestamps order events, and a timestamp written after a data-dependent loop
means nothing to a core that did not run the loop. The shared-core case is
correct because word `@9` is fetched only after `jump_cond_i` falls through.

### 7.2 What the current compiler does (implemented, compiler-only)

**Control-flow replication.** Every core with a quantum operation after a
runtime loop runs the loop's control flow: the same register updates, the
same FPROC reads in the same clock, the same `inc_qclk`. It leaves the loop
when core 0 does.

**[compiler output]** (current QD, core 1; core 0 is unchanged):

```text
qubit_command1  (8 words)
  @0    b0000000000000000000000000000000  pulse_reset
  @1    10000000010000000000000000000000  reg_alu_i        alu=id0 in0=#1 in1=r0 out=r0
  @2    c000000000000000000000000000ad20  idle             until t=1385
  @3    46000000000000000000000000000000  alu_fproc_i      alu=id1 in0=#0 out=r0 func_id=0
  @4    61fffffa8b0000000000000000000000  inc_qclk_i       alu=add in0=#-1397
  @5    33000000010000200000000000000000  jump_cond_i      alu=eq in0=#1 in1=r0 ->@2
  @6    900803000200004008f68600000001e0  pulse_write_trig t=15 cfg=0 amp=15777 freq=0 phase=0 env_word=49152
  @7    a0000000000000000000000000000000  done
```

**[RTL]** (`run_seq.py`, current): `Q1.qdrv starts at 4213 >= end of ... at
4122`, the same as on a shared core; with the bit forced to 0 (one
iteration, same binary) the loop ends at 1328 and X90(Q1) starts at 1419.

**Remaining limitations (current).**

- Replication costs instructions and registers on every following core
  (registers are counted per core; > 16 is a compile error).
- It requires every following core to have the same `qclk` history: a core
  cannot follow two *concurrent* runtime loops. QD rejects
  `parallel { loop on Q0 | loop on Q1 } X90(Q2);`
  (`qdsl/errors/e18_parallel_runtime_loops.qd`). Where one core can follow
  both loops in turn, QD accepts the program but the loops then run one after
  the other (**[RTL]** `par_loops_serialized`: Q1's loop starts at 2820, after
  Q0's loop ends at 2729).
- A core on another board cannot read the measurement (each board has its own
  FPROC): rejected.
- The guarantee assumes QubiC's static cycle model is exact (§10).

## 8. `parallel` with a join (implemented)

`parallel { A | B }` is implemented with exactly the semantics proposed in
the interview brief: the branches may overlap, a common start is not
promised, and the statement after the block starts only after every branch
has completed. Branches must use disjoint qubits and must not share a register
that one of them writes.

How it is compiled: a barrier over all branches before the block, the
branches one after another in the IR (each scheduled from that barrier), and
the next statement's barrier is the join. On distinct cores the branches
start at the same barrier (§6); on a shared core they are issued in turn.
Branches with different durations: the join is the maximum end
(**[RTL]** `par_durations`: three X90s on Q0, one on Q1, Q2 at 48).

What is **not** implemented is a join after concurrent runtime-dependent
branches on different cores (§7.2): that needs a runtime mechanism (Part II).

## 9. Measurement feedback (implemented)

```odin
qubit Q0, Q1;
place Q0 on board0.core0, Q1 on board0.core1;
if measure(Q0) == 1 { X90(Q1); X90(Q1); }
measure(Q1);
```

(`qdsl/examples/mc_feedback.qd`.) The measurement result travels from the
`rdlo` element to FPROC, which holds one bit per measurement channel. Any core
on the board can read any bit: a read returns 2 clocks after the request
(**[RTL]** `rtl/fproc_tb`). Here both cores branch: core 1 reads core 0's
result. **[RTL]** (`rtl/multi_tb/run_multi.py`, 3 shots, Q0 measures
1, 0, 1): the X90s on Q1 play in shots 0 and 2 only; both cores request the
result in the same clock (`qclk` 1372); the following readout starts at a
fixed `qclk` (1406) in every shot, and every shot takes 2781 clocks.

**Limitations.**

- **No freshness.** FPROC returns whatever bit it holds, without waiting
  (**[RTL]** `rtl/fproc_tb` f3). Correctness depends on the compile-time hold.
  With the hold at 62 clocks, the run reads the *previous shot's* bit
  (**[RTL]** `run_multi.py` negative test).
- Across boards: not possible (one FPROC per board); rejected by QD.
- A loop condition cannot read a measurement directly (`do {...} while
  measure(Q0) == 1;` is rejected); the result goes into a register first.

## 10. Timing guarantees and their limits

The order guarantee rests on QubiC's static cycle model: the scheduler places
every timed instruction late enough for the core to reach it. If the core
reaches it late, it never fires on time:

- **[RTL]** `rtl/isa_tb` t3: a trigger whose time is already past produces no
  strobe; after 3000 clocks the core is still in DECODE, `done = 0`.
- The trigger compares for equality: `qclk_trig <= (qclk_out ==
  pulse_cmd_time)` (`hdl/proc.sv:138`, with the upstream comment "todo: this
  could cause issues"). `qclk` is a 32-bit counter that increments every clock
  (`hdl/qclk.v`). **From the source** (not simulated): a late trigger
  therefore fires only when `qclk` wraps around and matches again, 2³² clocks
  ≈ 8.6 s later. The shot sequencer has no timeout; it waits for every core's
  `done` (`gateware/dsp/dsp.sv:209, 233`).
- **[RTL]** measured margins: across all `run_seq.py` and `run_multi.py`
  programs the minimum trigger slack (timestamp minus `qclk` on arrival) is 0
  to 3 clocks, never negative. The model is exact on this RTL, with no
  margin. QubiC's own comment says `jump_fproc` "can be 7 in some cases"; with
  that budget set to 7, the X90 after the branch is late by one clock and the
  core never finishes (**[RTL]** `rtl/meas_tb/run_checks.py`: slack −1,
  `done = False`).

## 11. Tests run for this document

All on 2026-10-26, current `main` (details in Appendix A):

| Suite | What it exercises | Result |
|---|---|---|
| `python -m qdsl.run_tests` | 19 examples compiled and assembled, 23 error cases, core-model, sequencing and placement tests | PASS |
| `python tools/check_doc_dsl.py ...` | every QD snippet in the docs, including this one, compiled; listed words matched | 0 invalid |
| `rtl/isa_tb` (cocotb, Verilator) | single core: instruction costs, timed trigger, late trigger, `inc_qclk`, compares, `sync` | 8/8 |
| `rtl/fproc_tb` | FPROC latency, stale reads, cross-core reads | pass |
| `rtl/qd_tb/run_demo.sh` | QD machine code on the processor RTL (active reset, runtime-delay T1) | PASS |
| `rtl/multi_tb/run_multi.py` | 3 cores + FPROC + shot sequencer, multi-shot | PASS |
| `rtl/multi_tb/run_seq.py` | 14 sequencing programs, order checked from pulse intervals | PASS |
| `rtl/meas_tb/run_checks.py` | measurement-feedback timing margins | table, as above |

"Compiles" means QD → QubiC IR → QubiC compiler → assembler. "RTL" means the
machine words ran on the vendored processor (and, in `multi_tb`, element and
FPROC) RTL in simulation. Nothing here has run on an FPGA.

---

# Part II: Proposed extensions (design proposals, not existing capabilities)

## A. Global sequential semantics

`A; B;` should mean: every operation of `A` has completed before any
operation of `B` begins, wherever the qubits are placed. This is QD's
definition today, and QD meets it with the techniques marked *implemented*;
the others are proposals.

| Technique | Feasible when | Fails when | Status |
|---|---|---|---|
| Static scheduling | every duration is known at compile time | a duration depends on a runtime value | implemented |
| Loop unrolling | the trip count is a compile-time constant and the code fits (8192 words per core) | trip count unknown, or too large | implemented as `#unroll for` (explicit) |
| Padding to a proven maximum | a runtime loop has a provable bound; the waiting core schedules after the bound | no bound (a repeat-until-success loop); or the bound is far above the typical duration, wasting coherence time | proposed |
| Control-flow replication | the following core can run the same decisions in the same clocks (same FPROC, same `qclk` history) | it must follow two concurrent loops; or the result is on another board | implemented |
| Runtime synchronization | hardware can release waiting cores together | the hardware path does not exist today (C) | proposed |

The trade-off: replication and padding keep the hardware unchanged and
deterministic, but cost instructions and time; synchronization is general but
needs gateware and adds runtime stalls.

## B. Parallel execution with a full join

Implemented for statically schedulable branches (§8). Open cases, which are
proposals:

- **Independent runtime loops in branches, followed by a statement on a third
  core.** The join time is the later of two runtime values that are known on
  two different cores. Today: rejected or serialized. Options: a bound (A),
  or a rendezvous of the cores involved (C).
- **Branches on a shared core with runtime loops.** One instruction stream can
  only execute them in turn; true overlap would need two sequencers per core.
- **Requested simultaneous start** (e.g. aligned readout of two qubits) is
  not expressible: `parallel` deliberately does not promise it. A separate
  construct would be needed; on independent cores it is achievable statically
  (the current schedule does it), after runtime loops it needs C.

## C. Runtime synchronization

A conceptual operation, **[hypothetical]** syntax:

```text
now(Q0, Q1);     // proposed rendezvous: the cores of Q0 and Q1 wait for each other,
                 // then continue from a common release time
```

(The name collides with the separately proposed `now()` for reading physical
time, D; a name such as `sync(Q0, Q1)` would be clearer.)

**What exists in QubiC [source + RTL]:**

- Opcode `sync` (`01110`), barrier id in bits [119:112]
  (`distproc/command_gen.py`).
- In the control state machine: DECODE → SYNC_WAIT, wait for `sync_ready`,
  then QCLK_RST, which zeroes `qclk` (`hdl/ctrl.v:347-349, 510-534`).
- An interface `sync_iface` with `barrier`, `enable`, `ready`.

**What is incomplete:**

- The generated gateware instantiates `sync_iface` per core, but nothing
  drives `ready` (`gateware/top/src/dsp_coregen.py:349-355`). A core that
  executes `sync` waits forever (**[RTL]** `rtl/isa_tb` t7: still in
  SYNC_WAIT after 500 clocks, `done = 0`).
- `proc.sv` does not drive `sync.barrier`, so the barrier id is lost.
- The QubiC assembler rejects `sync`, and the IR has no instruction for it.

**What would need to change:**

1. Gateware: a sync controller that knows each barrier's participants,
   collects `enable` and raises `ready` on all of them **in the same clock**.
   Because QCLK_RST zeroes `qclk`, all participants then share a time origin
   again, which is exactly what is lost after a data-dependent loop.
2. ISA wiring: `barrier` from `proc.sv`; possibly a participant mask instead
   of an 8-bit id.
3. Toolchain: an IR instruction, assembler support, and a scheduler that
   restarts its time base after a rendezvous (timestamps after `sync` are
   relative to the release).

**Hypothetical timeline** (not observed; no such hardware exists):

```text
core 0  [loop iteration 1][iteration 2]...[iteration k] sync |release| qclk:=0 ...
core 1  sync |waiting ......................................|release| qclk:=0 [X90(Q1)]
                                                             ^ ready to both cores in one clock
```

**Hazards.**

- *Deadlock.* A participant that never reaches its `sync` (a branch not
  taken, a hang after a late trigger) blocks the others forever, and the shot
  sequencer has no timeout. The compiler must make every `sync` reachable on
  every participant along every path (it already replicates control flow for
  this reason), and the hardware should have a timeout with an error flag.
- *Barrier ids.* Nested or concurrent barriers on overlapping core sets need
  distinct ids or a per-core sequence number.
- *Cost.* A rendezvous costs the waiting core idle time and the release
  latency; within one FPGA that is a few clocks of fixed, known latency.
  Across boards the release must be distributed with a known, fixed delay,
  which needs a shared trigger line or clock distribution.

A one-sided "completion flag" (core 0 signals and continues; core 1 waits)
has no counterpart in the ISA and would need new instructions.

## D. Global physical time

Four different times:

| Time | What it is | Today |
|---|---|---|
| Physical time | wall-clock time since the shot start | not visible to the program |
| `qclk` | per-core schedule coordinate: reset at shot start, +1 per clock, shifted by `inc_qclk` (loop rewinds, runtime delays) | exists |
| Instruction issue time | when the core actually reaches an instruction; runs ahead of `qclk` and stalls on the next timed pulse | not visible; measured in simulation as trigger slack |
| Pulse output time | `qclk == t` plus a fixed pipeline latency (strobe 2 clocks after the match, **[RTL]** t2: `cmd_time=100` strobed at `qclk=102`), plus element and DAC latency | fixed per path |

Loops break the link between `qclk` and physical time: after a data-dependent
loop, `qclk` on a core that rewound is "time since the loop started in the
current frame", and the other cores' `qclk` means something else. Phase
coherence is not affected: each element keeps its own free-running counter,
zeroed by `pulse_reset`, so carrier phase follows physical time.

**[hypothetical]** additions:

```text
rdtime  rN          ; rN := low 32 bits of a per-core counter that is reset at shot
                    ; start on all cores together and never shifted or rewound
trig_abs t=rN       ; trigger at an absolute physical time
```

A synchronized counter gives every core a common reference that survives
loops, makes traces comparable, and lets a core measure its lag. It does
**not** tell core 1 whether core 0's loop has finished: the loop's end is a
runtime value known on core 0. It complements A-C; it does not replace them.
On one FPGA the counters share a clock and reset. Across boards they need a
common reference clock and a synchronized reset, i.e. a timing-distribution
system.

## E. Missed timing deadlines

Facts (§10): a late trigger does not fire; the comparison is an equality on
a wrapping 32-bit counter; the shot never ends while the core waits; nothing
reports the condition.

Compile time vs. runtime:

- **Compile-time guarantee (today):** the static schedule plus QubiC's cycle
  model. Exact on this RTL, zero margin, silent when wrong.
- **Compile-time improvement (compiler-only, proposed):** schedule with an
  explicit safety margin, and add the cases the model does not count (QD
  already warns about the extra `pulse_write` word of a pulse with two
  register parameters).
- **Runtime detection (needs RTL):** compare `qclk >= t` within a window
  instead of `==`, and set a sticky "missed deadline" flag with the core id
  and address, readable by the host after the shot.

**[hypothetical]** policies for a late trigger, as a per-program or
per-instruction mode:

| Policy | Effect | Suitable for |
|---|---|---|
| abort | stop the shot, report the core and address | default: the experiment's timing is invalid |
| skip | drop the pulse, flag it | diagnostics only |
| fire now | fire late, flag it | non-critical outputs (triggers to instruments) |

For qubit pulses only *abort* keeps results trustworthy: a late pulse
changes the physics, a skipped one changes the circuit.

## F. Measurement-dependent control flow

**Demonstrated:** a result reaches FPROC after the demodulation window; a
core reads it with `alu_fproc` / `jump_fproc` after a compile-time hold;
several cores on one board can read the same bit in the same clock and take
the same decision (§9, **[RTL]**).

**Proposed:**

- *Freshness.* A valid bit or sequence number per result, and a read that
  blocks until a result newer than the request is available. That removes
  the dependence on an exact hold constant (one clock of margin today) at the
  cost of a data-dependent stall, which the static schedule must then absorb
  (a rendezvous-like problem, C).
- *Cross-board distribution.* Results of one board's FPROC delivered to
  another board's cores with a fixed latency.
- *Compiler:* schedule the feedback latency as a first-class cost (today it is
  `FPGAConfig.fproc_meas_clks` and `jump_fproc_clks`).

## G. ISA and hardware assessment

| Feature | Compiler-only solution? | ISA changes? | RTL changes? | Main difficulty |
|---|---|---|---|---|
| Sequential `;` across cores, static durations | **yes, implemented** | no | no | exactness of the cycle model |
| Sequential `;` after a runtime loop | **yes, implemented** (replication) | no | no | register and instruction cost; one `qclk` history per following core |
| `parallel` with a join, static branches | **yes, implemented** | no | no | — |
| Join after concurrent runtime loops on different cores | only by serializing or by a proven bound | `sync` exists; usable form needs barrier/participant encoding | sync controller; `barrier` wiring | same-clock release; deadlock freedom |
| Runtime rendezvous (`now(Q0, Q1)`, hypothetical) | no | opcode exists; IR and assembler support missing | yes: nothing drives `sync.ready` | release latency across boards; timeouts |
| Global physical time | no (a program cannot read time) | yes: read/trigger-at-absolute-time instructions | yes: unshifted counter per core | multi-board clock and reset distribution |
| Missed-deadline detection | partly: margins and better cost models | optional (policy bits) | yes: `>=` window compare, sticky error flag | defining policy; wraparound of the equality compare |
| Fresh measurement reads | no (only a hold constant) | possibly (blocking read) | yes: valid/sequence bit in FPROC | data-dependent stall vs. static schedule |
| Cross-board feedback | no | possibly | yes: result distribution | fixed latency across boards |

The general position: keep everything that has a correct compiler-only
solution in the compiler (it is deterministic, testable, and costs no
gateware), and ask the hardware for exactly what the compiler cannot know:
when a runtime-dependent event has happened on another core, what the
physical time is, and whether a deadline was missed.

## H. Hypothetical: a full join after independent runtime loops (examples 6 and 7)

The static version of example 6 (a `parallel` block with a join) is
implemented and runs on RTL (§6, §8). The proposal is the case it cannot
handle today.

```text
// [hypothetical] what QD would like to compile, given a working sync controller
qubit Q0, Q1, Q2;
m0 := 1; m1 := 1;
parallel {
    do { X90(Q0); m0 = measure(Q0); } while m0 == 1;
|
    do { X90(Q1); m1 = measure(Q1); } while m1 == 1;
}
X90(Q2);
```

Today this is rejected (`e18`). With a rendezvous it could compile to
(**[hypothetical]** pseudocode, not QubiC assembly):

```text
core 0: loop0 ...; sync b=1          core 1: loop1 ...; sync b=1          core 2: sync b=1
                                                                                  pulse t=T  X90(Q2)
```

```text
core 0  [loop 0: k0 iterations] sync |wait.........|
core 1  [loop 1: k1 iterations ............] sync |   release: qclk := 0 on cores 0, 1, 2
core 2  sync |waiting ..............................|   [X90(Q2) at t = T]
```

The loops overlap (they do not today), and the join is exact. The cost is one
barrier controller in the gateware and the scheduler change in C.

---

## Likely Interview Questions

**1. Why not just synchronize the cores at every statement?**
Because the hardware cannot today (`sync` never releases), and because it
would serialize everything through a barrier, costing time on every
statement. Static scheduling gives the same order for free when durations are
known, and replication covers runtime loops on one board. Synchronization is
only needed for the residue: concurrent runtime-dependent work that a third
core must follow.

**2. How do you know the static schedule is correct on hardware?**
On the RTL I measure trigger slack for every timed instruction: 0 to 3
clocks, never negative, across all multi-core programs. That proves the cycle
model is exact *for these programs on this RTL*. It is not a proof for all
programs, and it says nothing about an FPGA build with different memory
latencies. A one-clock underestimate (`jump_fproc` budget 7 instead of 8)
hangs the core.

**3. What happens if a pulse is scheduled too late?**
It does not fire. The trigger compares `qclk == t`, so the core waits until
the 32-bit counter wraps (about 8.6 s, from the source; simulated: no strobe
and no `done` after 3000 clocks). Nothing reports it. The fix is a `>=`
comparison with an error flag; the policy question is abort vs. skip.

**4. Replication duplicates control flow. What does that cost?**
Instructions on every following core, and registers: a replicated loop
condition's registers count against the 16 per core, checked at compile time.
It also requires the following cores to have the same `qclk` history, so one
core cannot follow two concurrent loops. And all of them must read FPROC at
the same clock, which they do because they share the schedule.

**5. Why is `place` only a check?**
In QubiC the wiring is data, not something the program can choose: the
channel configuration names which core and element each channel is, and the
gateware fixes which element drives which converter. A compiler that
"placed" channels would have to emit a channel configuration, and the
gateware would have to support that layout. The useful thing a compiler can
do today is make the program's assumption explicit and fail when it is
compiled for different hardware.

**6. Can you guarantee that two pulses on different cores start in the same
clock?**
On one board, after no runtime-dependent control flow: yes, by timestamp, and
the RTL shows it (`mc_align`: both X90s and both readouts in the same cycle).
After a data-dependent loop only if both cores ran the same loop (replication)
or after a rendezvous (proposed). Across boards it needs clock and trigger
distribution that this repository does not model.

**7. How does a measurement result get to another core?**
Through FPROC, which any core on the board can read; the read returns the
latest bit 2 clocks after the request. The compiler waits a fixed hold after
the demodulation window. There is no freshness check: one clock less hold and
the previous shot's bit is read (shown on RTL).

**8. What is the difference between `qclk` and time?**
`qclk` is a schedule coordinate. It starts with physical time, and loops and
runtime delays shift it. Physical time is what the qubit sees. Carrier phase
follows physical time because each element has its own counter. A shared,
unshifted counter would help debugging and absolute timing, but it does not
tell a core whether another core's loop has finished.

**9. Where would you draw the compiler/hardware line?**
Compiler: everything decidable from the program and a cycle model, i.e.
scheduling, bounds, replication, resource checks. Hardware: what is only
known at runtime on another core (a rendezvous), what time it is (a counter),
and whether a deadline was missed (detection). Each could be added as a new instruction or status
register next to the existing ISA.

**10. What would you test first on real hardware?**
That the static schedule holds with the real memory and pipeline latencies:
trigger slack, feedback hold (the one-clock margin), and alignment of pulses
on two cores measured at the DACs, before relying on any cross-core order.

---

## Appendix A: Verification performed for this document

Commands run from `~/git/qubic-notes` after `source env.sh`, 2026-10-26:

- `python -m qdsl.run_tests`: PASS.
- `python tools/check_doc_dsl.py README.md docs/reference.md qdsl/README.md
  docs/interview-overview.md`: all snippets valid; the `odin` blocks of this
  document are compiled with the configuration named in their
  `// compile with --channels` comment.
- `rtl/isa_tb`, `rtl/fproc_tb` (`make`): 8/8 and 1/1 tests pass; the RESULT
  lines quoted above (t1, t2, t3, t7, f1-f5) are from this run.
- `rtl/qd_tb/run_demo.sh`, `python rtl/multi_tb/run_multi.py`,
  `python rtl/multi_tb/run_seq.py`: PASS; `python rtl/meas_tb/run_checks.py`:
  table as quoted.
- **§7.1 reproduction:** scratch `git worktree` at `1825b18` with `qdsl/`
  checked out from `b06698c` (the compiler before the fix), `run_seq.py
  loop_meas_two_cores loop_count_two_cores loop_meas_one_core`: two FAIL with
  the quoted ORDER VIOLATED lines, one ok. No file in the repository changed.
- **§5 RTL run:** a scratch script that imports `rtl/multi_tb/run_seq.py` and
  runs its `check()` on the §5 program with `spread_qubit.json`: ok, intervals
  as quoted. A second scratch case (a measurement-dependent loop on the
  spread qubit) did not iterate, because the testbench models only element 2
  as the demodulator; that case is therefore not claimed.

## Appendix B: Where to look in the code

| Topic | File |
|---|---|
| Grammar, AST | `qdsl/grammar.lark`, `qdsl/syntax.py` |
| Semantic analysis, `place` | `qdsl/sema.py` (`_PlaceDecl`) |
| Cores, naming, configuration validation | `qdsl/cores.py` |
| Scope inference, barriers, replication, frame checks | `qdsl/lower.py` |
| Backend, decoder, schedule printer | `qdsl/backend.py` |
| QubiC scheduling of loops | `vendor/distributed_processor/python/distproc/ir/passes.py:962-1235` |
| Trigger compare, `qclk`, `sync` | `vendor/distributed_processor/hdl/proc.sv:138`, `qclk.v`, `ctrl.v` |
| FPROC | `vendor/distributed_processor/hdl/fproc_meas.sv` |
| Shot sequencer | `vendor/gateware/dsp/dsp.sv` |
| DAC/ADC wiring of the build | `vendor/gateware/top/zcu216_14_2/dsp_config.yaml` |
| Longer reference | `docs/reference.md`, top-level `README.md` |

# QD: an Odin-flavoured front end for QubiC (v0 prototype)

QD compiles to QubiC-IR, then runs the unmodified QubiC compiler and assembler
down to 128-bit machine words. It adds two things the IR does not have:
**explicit time semantics** and **static checks that know the hardware**.

```sh
source env.sh
python -m qdsl qdsl/examples/ex6_active_reset.qd  # static schedule (default)
python -m qdsl FILE --ir | --asm | --bin | --check | --emit-ir out.json
python -m qdsl.run_tests                          # examples + error cases
```

## Language at a glance

A complete program that uses every construct (it compiles as is):

```odin
qubit Q0, Q1, Q2;                   // calibrated qubits (from qubitcfg.json)

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
par { { X90(Q0); } { X90(Q1); } }   // explicit parallelism
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
| `X90(Q0); X90(Q1);` | the second statement starts when everything the first used is idle | `barrier(Q0, Q1)`: the union of both statements' qubits |
| `par { { X90(Q0); } { X90(Q1); } }` | branches start together; next statement waits for the longest | barrier before, branches, barrier via the next `;` |
| `delay(10 us);`, `delay(10 us, Q0);` | idle the enclosing qubits (or the listed ones) | `delay` scoped to those qubits |
| `tau : time = 0 us;` then `delay(tau);` | runtime delay; applies to every qubit of the program | `alu sub` into a scratch register + `inc_qclk` on every core (patched IR op, `patches/`) |
| constants | folded at compile time, with units | immediates, envelope buffers |
| registers | replicated on every core that needs them | `declare` with an inferred scope |
| `do/while`, `for`, `if` | conditions normalized to the hardware's `<`, `>`, `==` with a register on the right | `loop`, `branch_var`, `branch_fproc` |

Register scopes are inferred by a fixed point over pulses, conditions and ALU
operations (see the header of `lower.py`).

## Checks

| Check | Why |
|---|---|
| unknown gate / qubit / frequency, with suggestions | IR: `KeyError` deep in a pass |
| delay and pulse width must be constants | IR: `TypeError` in the scheduler |
| ordering compares on `amp` registers that may hold a negative step | hardware compares the wrapped 16-bit word (RTL test t6) |
| negative `amp` constant in a comparison | same encoding problem |
| ordering compares on `phase` | phase wraps modulo 2π |
| `<=`, `>=`, `!=` in loop conditions | hardware has `<`, `>`, `==` only and loops cannot negate (int + constant is rewritten) |
| `par` branches sharing a qubit, including via a shared register | IR silently serializes or skews them |
| more than 16 registers on a core | assembler error far from the source |
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

## Not yet

- timing expressions (`duration(...)`), deadlines
- frequency-index registers, register `bind_phase` frames
- collecting several errors per run

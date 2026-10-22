# Patches to QubiC

Applied by `setup.sh` to the `.build` copies, never to `vendor/`.

## distproc-runtime-delay.patch

Adds IR instruction `inc_qclk` (`IncQclk(var, scope)`): add a register's value
(clocks) to qclk on every core in scope. With a negative value, all later
timestamps on those cores fire that many clocks later, giving a runtime delay.
The hardware op (register-sourced `inc_qclk`, opcode 01101) and the assembler
path already exist; only the IR, the scheduler and code generation were missing.

| File | Change |
|---|---|
| `ir/instructions.py` | new `IncQclk` class |
| `ir/passes.py` | `Schedule`: barrier over scope + one ALU instruction; hold resolution and `LintSchedule`: ALU cost |
| `compiler.py` | emits asm `{'op': 'inc_qclk', 'in0': <register>}` on every core in scope |

Why it is sound: every core in scope shifts its qclk by the same amount before
its next timestamped instruction, so the static schedule stays consistent among
those cores. Loops also stay consistent: the loop's own `inc_qclk(-body)`
rewinds relative to the shifted clock. Cores outside the scope are not shifted,
so the QD front end always scopes a runtime delay to every core of the program.
A negative delay would put the next trigger in the past and hang the core (RTL
test t3), so QD rejects registers that may decrease.

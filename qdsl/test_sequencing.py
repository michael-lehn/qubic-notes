"""Tests of QD's sequencing guarantee across physical processor cores.

    python -m qdsl.test_sequencing      (from ~/git/qubic-notes, after `source env.sh`)

`S1; S2` means every quantum operation of S1 has completed before any of S2 begins, however
qubits map to cores. Cores agree on time only through timestamps, so a core that issues a
pulse after a runtime loop must itself run the loop's control flow (or the compiler must
reject the program). These tests inspect the assembled instruction memories; the physical
timing of the same programs is checked on RTL by rtl/multi_tb/run_seq.py.
"""
from __future__ import annotations

import sys

from . import backend
from .cli import front_end
from .test_cores import compile_qd, expect_qd_error, target

LOOP_MEAS = 'qubit Q0, Q1; m := 1; do { X90(Q0); m = measure(Q0); } while m == 1; X90(Q1);'
LOOP_COUNT = 'qubit Q0, Q1; n := 0; do { X90(Q0); n += 1; } while n < 5; X90(Q1);'


def runs_loop_before_last_pulse(words: list[str]) -> bool:
    """The core executes a loop's backward jump before its last pulse."""
    last = max(i for i, w in enumerate(words) if w.startswith('pulse_write_trig'))
    return any(w.startswith('jump_cond') for w in words[:last])


def has_loop(words: list[str]) -> bool:
    return any(w.startswith('jump_cond') for w in words)


def schedule(src: str, t) -> list[tuple[int, int, str]]:
    """QubiC's static schedule: (start, end, channel) per pulse, in clocks. Physical time for
    programs without runtime loops; the RTL check of the same programs is run_seq.py."""
    ir, _ = front_end(src, 'test.qd', t)
    b = backend.build(ir, t)
    prog, clk = b.compiler.ir_prog, t.fpga.fpga_clk_period
    return sorted((i.start_time, i.start_time + round(i.twidth / clk), i.dest) for blk in prog.blocknames_by_ind
                  for i in prog.blocks[blk]['instructions'] if i.name == 'pulse')


def starts_after(sched, later: str, earlier: set, nth: int = 0) -> bool:
    """The nth pulse on channel `later` starts after every pulse on the `earlier` channels that
    precedes it in the schedule has ended."""
    s = [p for p in sched if p[2] == later][nth][0]
    return all(e <= s for st, e, d in sched if d in earlier and st < s)


PAR3 = 'qubit Q0, Q1, Q2; parallel { X90(Q0); | X90(Q1); } X90(Q2);'


# ---------------------------------------------------------------- a runtime loop, then another qubit

def test_loop_meas_two_cores():
    mems = compile_qd(LOOP_MEAS, target())
    assert runs_loop_before_last_pulse(mems['qubit_command1']), mems['qubit_command1']
    assert any(w.startswith('alu_fproc') for w in mems['qubit_command1']), 'core 1 must read the same result'


def test_loop_count_two_cores():
    mems = compile_qd(LOOP_COUNT, target())
    assert runs_loop_before_last_pulse(mems['qubit_command1']), mems['qubit_command1']


def test_loop_meas_one_core():
    mems = compile_qd(LOOP_MEAS, target('shared_core'))
    assert list(mems) == ['qubit_command0']
    assert runs_loop_before_last_pulse(mems['qubit_command0'])


def test_loop_count_one_core():
    mems = compile_qd(LOOP_COUNT, target('shared_core'))
    assert list(mems) == ['qubit_command0'] and runs_loop_before_last_pulse(mems['qubit_command0'])


def test_loop_split_qubit_then_other_core():
    """Q0 spans qubit/0 (qdrv, rdrv) and qubit/1 (rdlo); Q1 is on qubit/2."""
    mems = compile_qd(LOOP_MEAS, target('split_plus'))
    for core in ('qubit_command0', 'qubit_command1', 'qubit_command2'):
        assert has_loop(mems[core]), (core, mems[core])
    assert runs_loop_before_last_pulse(mems['qubit_command2'])


def test_loop_then_split_qubit():
    mems = compile_qd('qubit Q0, Q1; n := 0; do { X90(Q1); n += 1; } while n < 5; measure(Q0);',
                      target('split_plus'))
    for core in ('qubit_command0', 'qubit_command1'):
        assert runs_loop_before_last_pulse(mems[core]), (core, mems[core])


def test_inner_loop_followed_by_next_iteration():
    """The next iteration's X90(Q1) comes after the inner loop on Q0."""
    mems = compile_qd('qubit Q0, Q1; n := 0; k := 0;\n'
                      'do { X90(Q1); do { X90(Q0); n += 1; } while n < 3; k += 1; } while k < 2;', target())
    assert sum(w.startswith('jump_cond') for w in mems['qubit_command1']) == 2, mems['qubit_command1']


def test_loop_inside_branch_then_other_core():
    mems = compile_qd('qubit Q0, Q1, Q2; n := 0;\n'
                      'if measure(Q2) == 1 { do { X90(Q0); n += 1; } while n < 3; }\n'
                      'X90(Q1);', target())
    assert any(w.startswith('jump_fproc') for w in mems['qubit_command1']), mems['qubit_command1']
    assert runs_loop_before_last_pulse(mems['qubit_command1'])


def test_no_replication_without_later_operation():
    """A core whose operations all precede the loop does not run it."""
    mems = compile_qd('qubit Q0, Q1; n := 0; X90(Q1); do { X90(Q0); n += 1; } while n < 5;', target())
    assert not has_loop(mems['qubit_command1']), mems['qubit_command1']


def test_loop_meas_across_boards_rejected():
    """Q1's board cannot read Q0's result, so it cannot follow the loop: reject, do not weaken."""
    expect_qd_error(LOOP_MEAS, target('boards'), 'another board')


def test_loop_count_across_boards():
    mems = compile_qd(LOOP_COUNT, target('boards'))
    assert runs_loop_before_last_pulse(mems['b1:qubit_command0']), mems['b1:qubit_command0']


# ---------------------------------------------------------------- parallel { A | B }, then a join

def test_parallel_three_cores():
    sched = schedule(PAR3, target())
    assert starts_after(sched, 'Q2.qdrv', {'Q0.qdrv', 'Q1.qdrv'}), sched
    assert sched[0][0] == sched[1][0], 'on distinct cores both branches start at the barrier'


def test_parallel_one_core():
    sched = schedule(PAR3, target('one_core'))
    assert starts_after(sched, 'Q2.qdrv', {'Q0.qdrv', 'Q1.qdrv'}), sched
    assert sched[1][0] - sched[0][0] == 3, 'one core issues the second branch 3 clocks later'


def test_parallel_two_qubits_share_a_core():
    sched = schedule(PAR3, target('pair_core'))
    assert starts_after(sched, 'Q2.qdrv', {'Q0.qdrv', 'Q1.qdrv'}), sched


def test_parallel_different_durations():
    sched = schedule('qubit Q0, Q1, Q2; parallel { X90(Q0); X90(Q0); X90(Q0); | X90(Q1); } X90(Q2);', target())
    q0 = [p for p in sched if p[2] == 'Q0.qdrv']
    assert [p[0] for p in q0] == [q0[0][0], q0[0][1], q0[1][1]], 'sequential inside the branch'
    assert starts_after(sched, 'Q2.qdrv', {'Q0.qdrv', 'Q1.qdrv'}), 'join waits for the longest branch'


def test_parallel_nested():
    src = 'qubit Q0, Q1, Q2; parallel { parallel { X90(Q0); | X90(Q1); } X90(Q0); | X90(Q2); } X90(Q1);'
    for t in (target(), target('one_core'), target('pair_core')):
        sched = schedule(src, t)
        assert starts_after(sched, 'Q0.qdrv', {'Q0.qdrv', 'Q1.qdrv'}, 1), sched   # inner join
        assert starts_after(sched, 'Q1.qdrv', {'Q0.qdrv', 'Q1.qdrv', 'Q2.qdrv'}, 1), sched   # outer join


def test_parallel_branches_read_one_register():
    """Reading a register in both branches is fine; it lives on both cores."""
    compile_qd('qubit Q1, Q2; n : int = 0;\n'
               'parallel { X90(Q1); if n == 2 { X90(Q1); } | X90(Q2); if n == 3 { X90(Q2); } }', target())


def test_parallel_register_used_after_join():
    mems = compile_qd('qubit Q0, Q1; parallel { m := measure(Q0); | X90(Q1); } if m == 1 { X90(Q1); }', target())
    assert any(w.startswith('alu_fproc') for w in mems['qubit_command1']), mems['qubit_command1']


def test_parallel_register_race_rejected():
    for src in ('qubit Q0, Q1; n := 0; parallel { n += 1; X90(Q0); | X90(Q1); n += 2; }',
                'qubit Q0, Q1; m := 0; parallel { m = measure(Q0); | if m == 1 { X90(Q1); } }'):
        expect_qd_error(src, target(), "and branch")


def test_parallel_shared_qubit_rejected():
    expect_qd_error('qubit Q0, Q1; parallel { X90(Q0); | X90(Q1); X90(Q0); }', target(), 'both use Q0')


def test_parallel_runtime_loops_then_join_rejected():
    loops = 'parallel { do { X90(Q0); m0 = measure(Q0); } while m0 == 1; | do { X90(Q1); m1 = measure(Q1); } while m1 == 1; }'
    for after in ('X90(Q2);', 'X90(Q0);'):
        expect_qd_error(f'qubit Q0, Q1, Q2; m0 := 1; m1 := 1; {loops} {after}', target(),
                        'cannot guarantee the order of the loop')


def test_parallel_runtime_loops_serialized():
    """measure(Q1) after the block: core 1 follows Q0's loop, then runs its own, so the second
    branch runs after the first. Branches may be serialized; accepted."""
    loops = 'parallel { do { X90(Q0); m0 = measure(Q0); } while m0 == 1; | do { X90(Q1); m1 = measure(Q1); } while m1 == 1; }'
    mems = compile_qd(f'qubit Q0, Q1; m0 := 1; m1 := 1; {loops} measure(Q1);', target())
    assert sum(w.startswith('jump_cond') for w in mems['qubit_command0']) == 1
    assert sum(w.startswith('jump_cond') for w in mems['qubit_command1']) == 2


def test_parallel_runtime_loops_without_join():
    """Nothing follows the block: each core runs only its own loop."""
    mems = compile_qd('qubit Q0, Q1; m0 := 1; m1 := 1; parallel { do { X90(Q0); m0 = measure(Q0); } while m0 == 1; '
                      '| do { X90(Q1); m1 = measure(Q1); } while m1 == 1; }', target())
    assert [sum(w.startswith('jump_cond') for w in ws) for ws in mems.values()] == [1, 1], mems


def test_parallel_runtime_loop_and_static_branch_then_join():
    mems = compile_qd('qubit Q0, Q1, Q2; m := 1; parallel { do { X90(Q0); m = measure(Q0); } while m == 1; '
                      '| X90(Q1); } X90(Q2);', target())
    assert runs_loop_before_last_pulse(mems['qubit_command2']), mems['qubit_command2']
    assert not has_loop(mems['qubit_command1']), mems['qubit_command1']


def test_parallel_runtime_loops_on_one_core():
    """One core runs both loops in turn, so it can follow both: accepted (serialized)."""
    mems = compile_qd('qubit Q0, Q1; n := 0; k := 0; parallel { do { X90(Q0); n += 1; } while n < 3; '
                      '| do { X90(Q1); k += 1; } while k < 2; } measure(Q0);', target('shared_core'))
    assert sum(w.startswith('jump_cond') for w in mems['qubit_command0']) == 2


def test_parallel_runtime_delay_rejected():
    expect_qd_error('qubit Q0, Q1; tau : time = 1 us; parallel { delay(tau); X90(Q0); | X90(Q1); }', target(),
                    'runtime delay cannot be inside a parallel branch')


def test_par_is_gone():
    expect_qd_error('qubit Q0, Q1; par { { X90(Q0); } { X90(Q1); } }', target(), 'par was replaced by')


# ---------------------------------------------------------------- runner

def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith('test_') and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  ok    {name}')
        except Exception as e:                            # noqa: BLE001  report and continue
            failed += 1
            print(f'  FAIL  {name}: {type(e).__name__}: {str(e)[:200]}')
    print('PASS' if not failed else f'{failed} FAILURE(S)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

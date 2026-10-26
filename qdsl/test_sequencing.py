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

from .test_cores import compile_qd, expect_qd_error, target

LOOP_MEAS = 'qubit Q0, Q1; m := 1; do { X90(Q0); m = measure(Q0); } while m == 1; X90(Q1);'
LOOP_COUNT = 'qubit Q0, Q1; n := 0; do { X90(Q0); n += 1; } while n < 5; X90(Q1);'


def runs_loop_before_last_pulse(words: list[str]) -> bool:
    """The core executes a loop's backward jump before its last pulse."""
    last = max(i for i, w in enumerate(words) if w.startswith('pulse_write_trig'))
    return any(w.startswith('jump_cond') for w in words[:last])


def has_loop(words: list[str]) -> bool:
    return any(w.startswith('jump_cond') for w in words)


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

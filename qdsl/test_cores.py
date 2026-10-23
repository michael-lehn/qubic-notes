"""Tests of the physical-core model (qdsl/cores.py) and its use by the compiler.

    python -m qdsl.test_cores          (from ~/git/qubic-notes, after `source env.sh`)

Mapping tests query CoreModel only. Compilation tests run QD -> QubiC -> assembler with an
alternative channel configuration from qdsl/tests/configs/ and inspect the assembled
instruction memories.
"""
from __future__ import annotations

import copy
import json
import logging
import sys
import tempfile
from pathlib import Path

import distproc.compiler as cm
import distproc.hwconfig as dhw
import distproc.ir.ir as qir

from . import backend
from .cli import front_end
from .cores import ConfigError, CoreId, CoreModel
from .diag import QdError
from .target import DEFAULT_CHANNELS, Target

CONFIGS = Path(__file__).parent / 'tests' / 'configs'
logging.disable(logging.WARNING)
_targets: dict[str, Target] = {}


def target(config: str | None = None) -> Target:
    path = DEFAULT_CHANNELS if config is None else str(CONFIGS / f'{config}.json')
    if path not in _targets:
        _targets[path] = Target(channels_path=path)
    return _targets[path]


def core(name: str, ind: int, board: str = '') -> CoreId:
    return CoreId(board, name, ind)


def compile_qd(src: str, t: Target) -> dict[str, list[str]]:
    """Compile and return {instruction memory: [decoded words]}."""
    ir, _ = front_end(src, 'test.qd', t)
    b = backend.build(ir, t)
    return {name: [backend.decode(w) for w in ws] for name, ws in b.words().items()}


def pulses(words: list[str]) -> list[str]:
    return [w for w in words if w.startswith('pulse_write_trig')]


def expect_qd_error(src: str, t: Target, fragment: str):
    try:
        compile_qd(src, t)
    except QdError as e:
        text = e.msg + ' ' + (e.hint or '')
        assert fragment in text, f'expected {fragment!r} in: {text}'
        return
    raise AssertionError(f'compiled, expected error {fragment!r}')


def expect_config_error(raw: dict, fragment: str):
    try:
        CoreModel.from_config(raw, 'test.json')
    except ConfigError as e:
        assert any(fragment in p for p in e.problems), f'expected {fragment!r} in: {e.problems}'
        return
    raise AssertionError(f'accepted, expected config error {fragment!r}')


def base_raw() -> dict:
    return json.load(open(DEFAULT_CHANNELS))


TWO_CORE_REGS = ('qubit Q0, Q1;\n'
                 + ''.join(f'a{k} : amp = 0.1;\n' for k in range(9))
                 + ''.join(f'b{k} : amp = 0.1;\n' for k in range(8))
                 + ''.join(f'pulse(Q0.qdrv, amp = a{k}, width = 24 ns, env = cos_edge_square(0.25));\n' for k in range(9))
                 + ''.join(f'pulse(Q1.qdrv, amp = b{k}, width = 24 ns, env = cos_edge_square(0.25));\n' for k in range(8)))


# ---------------------------------------------------------------- A: vendored ZCU216 configuration

def test_a_vendored_mapping():
    m = target().cores
    for i in range(8):
        assert m.cores_of(f'Q{i}') == {core('qubit', i)}
        assert m.cores_of(f'Q{i}.qdrv') == {core('qubit', i)}
        assert m.channels_of_core(core('qubit', i)) == (f'Q{i}.qdrv', f'Q{i}.rdrv', f'Q{i}.rdlo')
        assert m.qubits_of_core(core('qubit', i)) == (f'Q{i}',)
    assert len(m.cores_of('Q0', 'Q1')) == 2
    assert m.notes == [] and m.fproc_board_problem == {}
    assert all(m.fproc_problem(f'Q{i}', m.cores) is None for i in range(8))


def test_a_vendored_agrees_with_qubic():
    """Our grouping and qubit->channel mapping equal QubiC's for the supported configuration."""
    m = target().cores
    theirs = cm.proc_grouping_from_channelconfig(dhw.load_channel_configs(DEFAULT_CHANNELS))
    assert sorted(map(sorted, m.proc_grouping())) == sorted(map(sorted, theirs))
    default = qir.QubitScoperFromTup(('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo'))
    for q in [f'Q{i}' for i in range(8)] + ['Q3.rdlo']:
        assert m.qubit_scoper().get_scope(q) == default.get_scope(q), q


def test_a_vendored_registers_per_core():
    """9 + 8 registers on two cores is fine (the same program fails on one shared core, test B)."""
    mems = compile_qd(TWO_CORE_REGS, target())
    assert set(mems) == {'qubit_command0', 'qubit_command1'}


# ---------------------------------------------------------------- B: two qubits share one core

def test_b_shared_mapping():
    m = target('shared_core').cores
    assert m.cores_of('Q0') == m.cores_of('Q1') == {core('qubit', 0)}
    assert m.cores_of('Q0', 'Q1') == {core('qubit', 0)}
    assert m.qubits_of_core(core('qubit', 0)) == ('Q0', 'Q1')
    assert m.proc_grouping() == [('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo', 'Q1.qdrv')]


def test_b_shared_compiles_to_one_core():
    mems = compile_qd('qubit Q0, Q1; X90(Q0); X90(Q1);', target('shared_core'))
    assert list(mems) == ['qubit_command0'], mems
    cfgs = [p.split('cfg=')[1].split()[0] for p in pulses(mems['qubit_command0'])]
    assert cfgs == ['0', '3'], cfgs                     # Q0.qdrv is element 0, Q1.qdrv element 3


def test_b_shared_par_rejected():
    expect_qd_error('qubit Q0, Q1; par { { X90(Q0); } { X90(Q1); } }', target('shared_core'),
                    'both run on processor core qubit/0')


def test_b_shared_registers_counted_together():
    expect_qd_error(TWO_CORE_REGS, target('shared_core'), 'core qubit/0 needs 17 registers')


def test_b_missing_channel():
    expect_qd_error('qubit Q0, Q1; pulse(Q1.rdrv, amp = 0.1, width = 24 ns, env = cos_edge_square(0.25));',
                    target('shared_core'), "channel 'Q1.rdrv' is not in the channel configuration")


# ---------------------------------------------------------------- C: one qubit spans two cores

def test_c_split_mapping():
    m = target('split_qubit').cores
    assert m.cores_of('Q0') == {core('qubit', 0), core('qubit', 1)}
    assert m.cores_of('Q0.qdrv') == m.cores_of('Q0.rdrv') == {core('qubit', 0)}
    assert m.cores_of('Q0.rdlo') == {core('qubit', 1)}
    assert m.qubit_scoper().get_scope('Q0') == {'Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'}


def test_c_split_measure_uses_both_cores():
    mems = compile_qd('qubit Q0; measure(Q0);', target('split_qubit'))
    assert set(mems) == {'qubit_command0', 'qubit_command1'}, mems
    assert [p.split('cfg=')[1].split()[0] for p in pulses(mems['qubit_command0'])] == ['1']   # rdrv
    assert [p.split('cfg=')[1].split()[0] for p in pulses(mems['qubit_command1'])] == ['4']   # rdlo + save_result


def test_c_split_loop_runs_on_both_cores():
    mems = compile_qd('qubit Q0; n := 0; do { measure(Q0); n += 1; } while n < 3;', target('split_qubit'))
    for name in ('qubit_command0', 'qubit_command1'):
        assert any(w.startswith('jump_cond') for w in mems[name]), (name, mems[name])


def test_c_split_feedback_uses_rdlo_core():
    mems = compile_qd('qubit Q0; if measure(Q0) == 1 { X90(Q0); }', target('split_qubit'))
    jumps = [w for ws in mems.values() for w in ws if w.startswith('jump_fproc')]
    assert jumps and all('func_id=1' in w for w in jumps), jumps     # core_ind of Q0.rdlo


# ---------------------------------------------------------------- D: two boards

def test_d_boards_mapping():
    m = target('boards').cores
    a, b = core('qubit', 0, 'b0'), core('qubit', 0, 'b1')
    assert m.cores_of('Q0') == {a} and m.cores_of('Q1') == {b} and a != b
    assert str(a) == 'b0:qubit/0' and a.instr_mem == ('b0', 'qubit_command0')
    assert m.notes == []


def test_d_boards_compile():
    mems = compile_qd('qubit Q0, Q1; X90(Q0); X90(Q1);', target('boards'))
    assert set(mems) == {'b0:qubit_command0', 'b1:qubit_command0'}, mems


def test_d_boards_feedback_on_own_board():
    """Each board has its own FPROC: feedback read only on the measuring board is fine."""
    mems = compile_qd('qubit Q0, Q1; if measure(Q0) == 1 { X90(Q0); } X90(Q1);', target('boards'))
    jumps = {k: [w for w in ws if w.startswith('jump_fproc')] for k, ws in mems.items()}
    assert len(jumps['b0:qubit_command0']) == 1 and 'func_id=0' in jumps['b0:qubit_command0'][0], jumps
    assert jumps['b1:qubit_command0'] == [], jumps


def test_d_boards_cross_board_feedback_rejected():
    for src in ('qubit Q0, Q1; if measure(Q0) == 1 { X90(Q1); }',
                'qubit Q0, Q1; m : int = 0; m = measure(Q0); if m == 1 { X90(Q1); }'):
        expect_qd_error(src, target('boards'), 'would read the FPROC of another board')


# ---------------------------------------------------------------- E: core types

def test_e_core_types_mapping():
    m = target('core_types').cores
    expected = {'Q0': core('qubit', 0), 'Q1': core('aux', 0), 'Q2': core('qubit', 10), 'Q3': core('qubit1', 0)}
    for q, c in expected.items():
        assert m.cores_of(q) == {c}, q
    assert len(set(expected.values())) == 4
    assert {c.instr_mem[1] for c in expected.values()} == {'qubit_command0', 'aux_command0', 'qubit_command10',
                                                            'qubit1_command0'}


def test_e_qubic_helper_would_merge():
    """QubiC's string key merges qubit/10 and qubit1/0; QD keeps them apart."""
    path = str(CONFIGS / 'core_types.json')
    theirs = cm.proc_grouping_from_channelconfig(dhw.load_channel_configs(path))
    assert len(theirs) == 3 and len(target('core_types').cores.proc_grouping()) == 4
    assert any("key 'qubit10'" in n for n in target('core_types').cores.notes)


def test_e_two_measuring_core_types_reject_feedback():
    raw = json.load(open(CONFIGS / 'core_types.json'))
    rdlo = dict(raw['Q0.rdlo'], core_name='aux', elem_ind=1,
                **{k: f'aux_{k}' for k in ('env_mem_name', 'freq_mem_name', 'acc_mem_name')})
    m = CoreModel.from_config({**raw, 'Q1.rdlo': rdlo})
    for q in ('Q0', 'Q1'):
        assert "core types 'aux', 'qubit' all measure" in m.fproc_problem(q), q


def test_e_two_rf_mix_on_one_core_reject_feedback():
    raw = json.load(open(CONFIGS / 'shared_core.json'))
    rdlo = dict(raw['Q0.rdlo'], elem_ind=1, **{k: f'q1_{k}' for k in ('env_mem_name', 'freq_mem_name',
                                                                       'acc_mem_name')})
    raw['Q1.qdrv']['elem_ind'] = 3
    raw.pop('Q0.rdrv')
    m = CoreModel.from_config({**raw, 'Q1.rdlo': rdlo})
    assert 'more than one rf_mix element' in m.fproc_problem('Q0')


def test_e_core_types_compile():
    mems = compile_qd('qubit Q0, Q1, Q2, Q3; X90(Q0); X90(Q1); X90(Q2); X90(Q3);', target('core_types'))
    assert set(mems) == {'qubit_command0', 'aux_command0', 'qubit_command10', 'qubit1_command0'}, mems
    assert all(len(pulses(ws)) == 1 for ws in mems.values())


# ---------------------------------------------------------------- F: invalid configurations

def test_f_invalid_configs():
    r = base_raw()
    del r['fpga_clk_freq']
    expect_config_error(r, "'fpga_clk_freq'")

    r = base_raw(); del r['Q0.qdrv']['core_ind']
    expect_config_error(r, "channel 'Q0.qdrv': missing 'core_ind'")

    r = base_raw(); r['Q0.qdrv']['core_ind'] = True
    expect_config_error(r, "'core_ind' must be int")

    r = base_raw(); r['Q0.qdrv']['core_ind'] = -1
    expect_config_error(r, 'negative core_ind')

    r = base_raw(); r['Q0.qdrv']['core'] = 0
    expect_config_error(r, 'unknown field(s) core')

    r = base_raw(); r['Q0.rdrv']['elem_ind'] = 0
    expect_config_error(r, 'share elem_ind 0 but differ')

    r = base_raw(); r['Q0.rdrv']['elem_ind'] = 4
    expect_config_error(r, 'elem_ind 4')

    r = base_raw(); r['Q0.qdrv'].pop('core_name'); r['Q0.rdrv']['core_name'] = ''
    r['Q0.rdlo']['core_name'] = ''
    expect_config_error(r, 'both as null and as ""')

    r = base_raw(); r['Q1.qdrv']['env_mem_name'] = r['Q0.qdrv']['env_mem_name']
    expect_config_error(r, "memory ':qubit_qdrv_env0' is used by Q0.qdrv.env_mem_name, Q1.qdrv.env_mem_name")

    r = base_raw(); r['Q0.qdrv']['env_mem_name'] = 'env{core}'
    expect_config_error(r, 'cannot format env_mem_name')


def test_f_valid_variants_accepted():
    # same memory name on different boards is legal: memories are per board
    CoreModel.from_config(json.load(open(CONFIGS / 'boards.json')))
    # a core spelled consistently without core_name is legal
    r = base_raw()
    for k in ('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'):
        r[k].pop('core_name')
    m = CoreModel.from_config(r)
    assert m.cores_of('Q0') == {CoreId('', '', 0)} and CoreId('', '', 0).instr_mem == ('', 'command0')
    # one element under two channel names (identical type and memories) is an alias, not an error
    r = base_raw(); r['C0.qdrv'] = dict(r['Q0.qdrv'])
    m = CoreModel.from_config(r)
    assert m.cores_of('C0') == m.cores_of('Q0') and any('aliases of element 0' in n for n in m.notes)


def test_f_target_reports_config_error():
    bad = copy.deepcopy(base_raw()); bad['Q0.rdrv']['elem_ind'] = 0
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'bad.json'
        json.dump(bad, open(path, 'w'))
        try:
            Target(channels_path=str(path))
        except ConfigError as e:
            assert 'share elem_ind 0' in str(e) and str(path) in str(e)
            return
    raise AssertionError('Target accepted an invalid configuration')


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
            print(f'  FAIL  {name}: {type(e).__name__}: {e}')
    print('PASS' if not failed else f'{failed} FAILURE(S)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

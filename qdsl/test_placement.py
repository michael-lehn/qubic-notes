"""Tests of `place`: QD names for cores, checking placements against the channel
configuration, and that placements leave the compiled program unchanged.

    python -m qdsl.test_placement      (from ~/git/qubic-notes, after `source env.sh`)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import backend
from . import syntax as A
from .diag import Diagnostics, QdError
from .lower import Lowering
from .run_tests import channels_of
from .sema import Sema
from .syntax import parse
from .target import CoreId, PlacementError, Target
from .test_cores import target

HERE = Path(__file__).parent
REPO = HERE.parent
logging.disable(logging.WARNING)


def analyse(src: str, t: Target) -> Sema:
    sema = Sema(t, Diagnostics('test.qd', src))
    Lowering(sema, sema.run(parse(src)), t).emit()
    return sema


def words(prog: A.Program, src: str, t: Target) -> dict[str, list[int]]:
    sema = Sema(t, Diagnostics('test.qd', src))
    ir = Lowering(sema, sema.run(prog), t).emit()
    return backend.build(ir, t).words()


def without_place(prog: A.Program) -> A.Program:
    return A.Program([it for it in prog.items if not isinstance(it, A.PlaceDecl)])


def expect_error(src: str, t: Target, fragment: str, line: int | None = None):
    try:
        analyse(src, t)
    except QdError as e:
        text = e.msg + ' ' + (e.hint or '')
        assert fragment in text, f'expected {fragment!r} in: {text}'
        assert line is None or e.pos.line == line, f'error at line {e.pos.line}, expected {line}'
        return
    raise AssertionError(f'accepted, expected error {fragment!r}')


def core(ind: int, name: str = 'qubit', board: str = '') -> CoreId:
    return CoreId(board, name, ind)


# ---------------------------------------------------------------- core names

def test_names_unnamed_board():
    m = target().cores
    assert m.boards() == {'board0': ''}
    assert m.resolve_core('board0', 'core3') == core(3)
    assert m.core_label(core(3)) == 'board0.core3'


def test_names_named_boards():
    m = target('boards').cores
    assert set(m.boards()) == {'b0', 'b1'}
    assert m.resolve_core('b1', 'core0') == core(0, board='b1')
    try:
        m.resolve_core('board0', 'core0')
    except PlacementError as e:
        assert 'b0, b1' in e.hint
    else:
        raise AssertionError('board0 resolved in a configuration with named boards only')


def test_names_ambiguous_core_type():
    m = target('core_types').cores          # qubit/0, aux/0, qubit/10, qubit1/0
    try:
        m.resolve_core('board0', 'core0')
    except PlacementError as e:
        assert 'ambiguous' in e.msg and 'board0.qubit.core0' in e.hint and 'board0.aux.core0' in e.hint
    else:
        raise AssertionError('board0.core0 resolved although three core types have core_ind 0')
    assert m.resolve_core('board0', 'core0', 'aux') == core(0, 'aux')
    assert m.resolve_core('board0', 'core10') == core(10)       # not confused with qubit1/0
    assert m.core_label(core(0, 'qubit1')) == 'board0.qubit1.core0'
    assert m.core_label(core(10)) == 'board0.core10'


def test_names_reject_malformed_core():
    for bad in ('cpu0', 'core', 'core01', 'core-1'):
        try:
            target().cores.resolve_core('board0', bad)
        except PlacementError:
            continue
        raise AssertionError(f'{bad!r} accepted as a core name')


# ---------------------------------------------------------------- accepted placements

def test_whole_qubit():
    s = analyse('qubit Q0;\nplace Q0 on board0.core0;\nX90(Q0);\n', target())
    assert {ch: c for ch, (c, _) in s.placements.items()} == \
        {'Q0.qdrv': core(0), 'Q0.rdrv': core(0), 'Q0.rdlo': core(0)}


def test_individual_channels():
    s = analyse('qubit Q1;\nplace Q1.qdrv on board0.core1;\nplace Q1.rdlo on board0.core1;\nX90(Q1);\n', target())
    assert set(s.placements) == {'Q1.qdrv', 'Q1.rdlo'}          # Q1.rdrv is left to the configuration


def test_comma_separated_one_statement():
    src = ('qubit Q1;\n'
           'place Q1.qdrv on board0.core1,\n      Q1.rdrv on board0.core2,\n      Q1.rdlo on board0.core2;\n'
           'X90(Q1);\nmeasure(Q1);\n')
    prog = parse(src)
    decls = [it for it in prog.items if isinstance(it, A.PlaceDecl)]
    assert len(decls) == 1 and len(decls[0].placements) == 3
    s = analyse(src, target('spread_qubit'))
    assert {ch: c.core_ind for ch, (c, _) in s.placements.items()} == {'Q1.qdrv': 1, 'Q1.rdrv': 2, 'Q1.rdlo': 2}


def test_qubits_share_a_core():
    analyse('qubit Q0, Q1;\nplace Q0 on board0.core0, Q1.qdrv on board0.core0;\nX90(Q0); X90(Q1);\n',
            target('shared_core'))
    analyse('qubit Q0, Q1, Q2;\nplace Q0 on board0.core0, Q1 on board0.core0, Q2 on board0.core0;\n'
            'X90(Q0); X90(Q1); X90(Q2);\n', target('one_core'))


def test_qubit_spans_three_cores():
    s = analyse('qubit Q2;\nplace Q2.qdrv on board0.core3, Q2.rdrv on board0.core4, Q2.rdlo on board0.core5;\n'
                'X90(Q2);\nmeasure(Q2);\n', target('spread_qubit'))
    assert {c.core_ind for c, _ in s.placements.values()} == {3, 4, 5}


def test_named_board_and_core_type():
    analyse('qubit Q0, Q1;\nplace Q0 on b0.core0, Q1 on b1.core0;\nX90(Q0); X90(Q1);\n', target('boards'))
    analyse('qubit Q1;\nplace Q1 on board0.aux.core0;\nX90(Q1);\n', target('core_types'))


def test_repeating_a_placement_is_not_a_conflict():
    analyse('qubit Q0;\nplace Q0 on board0.core0;\nplace Q0.rdlo on board0.core0;\nX90(Q0);\n', target())


def test_place_is_not_a_reserved_prefix():
    analyse('qubit Q0;\nplacement := 1;\nonce := 2;\nplace Q0 on board0.core0;\nX90(Q0);\n', target())


# ---------------------------------------------------------------- rejected placements

def test_unknown_qubit():
    expect_error('qubit Q0;\nplace Q1 on board0.core1;\n', target(), "unknown qubit 'Q1'", 2)


def test_unknown_channel():
    expect_error('qubit Q0;\nplace Q0.drive on board0.core0;\n', target(), "'Q0.drive' is not a channel")


def test_channel_not_configured():
    expect_error('qubit Q1;\nplace Q1.rdrv on board0.core0;\n', target('one_core'),
                 "'Q1.rdrv' is not in the channel configuration")


def test_unknown_board():
    expect_error('qubit Q0;\nplace Q0 on board1.core0;\n', target(), "no board 'board1'")


def test_unknown_core():
    expect_error('qubit Q0;\nplace Q0 on board0.core8;\n', target(), 'no core board0.core8')
    expect_error('qubit Q0;\nplace Q0 on board0.aux.core0;\n', target(), 'no core board0.aux.core0')


def test_ambiguous_core():
    expect_error('qubit Q0;\nplace Q0 on board0.core0;\n', target('core_types'), 'is ambiguous')


def test_conflicting_placements():
    expect_error('qubit Q0;\nplace Q0 on board0.core0;\nplace Q0.rdlo on board0.core1;\n', target(),
                 "conflicting placement of 'Q0.rdlo': board0.core1 here, board0.core0 at line 2", 3)
    expect_error('qubit Q0;\nplace Q0.qdrv on board0.core0, Q0.qdrv on board0.core1;\n', target(),
                 "conflicting placement of 'Q0.qdrv'")


def test_inconsistent_with_configuration():
    expect_error('qubit Q0;\nplace Q0 on board0.core1;\n', target(), 'wires Q0.qdrv to board0.core0')
    # whole-qubit placement of a qubit the configuration splits over two cores
    expect_error('qubit Q0;\nplace Q0 on board0.core0;\n', target('split_qubit'),
                 'place Q0.qdrv on board0.core0, Q0.rdrv on board0.core0, Q0.rdlo on board0.core1;')
    # two qubits on one core, where the configuration gives each its own
    expect_error('qubit Q0, Q1;\nplace Q0 on board0.core0, Q1 on board0.core0;\n', target(),
                 'cannot place Q1 on board0.core0')


def test_place_only_at_top_level():
    expect_error('qubit Q0;\nif 1 == 1 { place Q0 on board0.core0; }\n', target(), 'top level')
    expect_error('qubit Q0;\np :: proc(q: qubit) { place Q0 on board0.core0; }\np(Q0);\n', target(), 'top level')


# ---------------------------------------------------------------- compiled output

def test_placement_emits_nothing():
    src = 'qubit Q0;\nplace Q0 on board0.core0;\nX90(Q0);\n'
    t = target()
    sema = Sema(t, Diagnostics('test.qd', src))
    mir = sema.run(parse(src))
    assert len(mir) == 1, mir                                    # only the gate; place is not an operation


def test_scopes_follow_placement():
    """A loop over a measurement of Q1, whose channels span two cores, followed by an operation
    on a third core: all three cores take part (control-flow replication), exactly as without
    the placement."""
    src = ('qubit Q0, Q1;\n'
           'place Q0 on board0.core0;\n'
           'place Q1.qdrv on board0.core1, Q1.rdrv on board0.core2, Q1.rdlo on board0.core2;\n'
           'm := 1;\ndo { X90(Q1); m = measure(Q1); } while m == 1;\nX90(Q0);\n')
    t = target('spread_qubit')
    prog = parse(src)
    with_p, without = words(prog, src, t), words(without_place(prog), src, t)
    assert with_p == without
    assert set(with_p) == {'qubit_command0', 'qubit_command1', 'qubit_command2'}, sorted(with_p)
    for mem in with_p:
        assert any(backend.decode(w).startswith('jump_cond') for w in with_p[mem]), f'{mem} does not run the loop'


def test_examples_unchanged_by_placement():
    """Every example declares its placement; removing the declarations changes no word."""
    n = 0
    for f in sorted((HERE / 'examples').glob('*.qd')):
        src = f.read_text()
        prog = parse(src)
        assert any(isinstance(it, A.PlaceDecl) for it in prog.items), f'{f.name} has no place declaration'
        cfg = channels_of(src)
        t = target(Path(cfg).stem) if cfg else target()
        assert words(prog, src, t) == words(without_place(prog), src, t), f'{f.name}: output differs'
        n += 1
    assert n >= 17, n


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
            print(f'  FAIL  {name}: {type(e).__name__}: {str(e)[:300]}')
    print('PASS' if not failed else f'{failed} FAILURE(S)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

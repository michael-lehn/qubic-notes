"""Compile every example to machine code and check every error case.

    python -m qdsl.run_tests          (from ~/git/qubic-notes, after `source env.sh`)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import backend
from .cli import front_end
from .diag import Diagnostics, QdError
from .target import Target

HERE = Path(__file__).parent
logging.disable(logging.WARNING)       # QubiC's "Z-phase inside loops" warning is noise here


def pulses(b: backend.Build) -> list[tuple[int, str]]:
    prog = b.compiler.ir_prog
    return sorted((i.start_time, i.dest) for blk in prog.blocknames_by_ind
                  for i in prog.blocks[blk]['instructions'] if i.name == 'pulse')


def start(ps, dest, nth=0) -> int:
    return [t for t, d in ps if d == dest][nth]


# Hand-written QubiC-IR Example 0 (outputs/out_a.txt): QD must produce the same words.
EX0_WORDS = [0xb0000000000000000000000000000000, 0x1000000ccc0000000000000000000000,
             0x90080300020000400c000200007a1320, 0x9008fa0002000040080a1220007a14a0,
             0x9008fa00023c53c009fffec0007a3a20, 0x1100000ccc0000000000000000000000,
             0x61fffc2a500000000000000000000000, 0x3500007fff0000200000000000000000,
             0xa0000000000000000000000000000000]


def check_example(name: str, b: backend.Build):
    ps = pulses(b)
    if name == 'ex0_amp_sweep':
        assert b.words()['qubit_command0'] == EX0_WORDS, 'differs from hand-written IR'
    elif name == 'seq_vs_par':
        assert start(ps, 'Q0.qdrv') == 5 and start(ps, 'Q1.qdrv') == 21, ps
        assert start(ps, 'Q0.qdrv', 1) == start(ps, 'Q1.qdrv', 1) == 37, ps
    elif name == 'ex7_two_qubits':
        assert start(ps, 'Q1.qdrv') == start(ps, 'Q2.qdrv'), 'X90s not parallel'
        assert start(ps, 'Q1.rdrv') == start(ps, 'Q2.rdrv'), 'readout not aligned'
    elif name == 'ex6_active_reset':
        ops = [i['op'] for i in next(iter(b.asm.program.values()))]
        assert 'idle' in ops and 'jump_fproc' in ops, ops
    elif name == 't1_unrolled':
        reads = [t for t, d in ps if d == 'Q0.rdrv']
        gaps = [b - a for a, b in zip(reads, reads[1:])]
        assert len(reads) == 5, reads
        assert all(g2 - g1 == 5000 for g1, g2 in zip(gaps, gaps[1:])), gaps   # tau grows by 10 us = 5000 clks
    elif name == 't1_runtime':
        ops = b.asm.program[('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo')]
        assert any(i['op'] == 'inc_qclk' and isinstance(i['in0'], str) for i in ops), 'no register inc_qclk'
        assert len(b.words()['qubit_command0']) < 22, 'should beat the unrolled version'
    elif name == 'ex3_counter':
        assert any('jump_cond' == i['op'] for i in b.asm.program[('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo')])


def main() -> int:
    target = Target()
    failures = 0
    print('examples')
    for f in sorted((HERE / 'examples').glob('*.qd')):
        try:
            ir, diag = front_end(f.read_text(), f.name, target)
            b = backend.build(ir, target)
            check_example(f.stem, b)
            n = sum(len(ws) for ws in b.words().values())
            print(f'  ok    {f.name:24s} {len(b.words())} core(s), {n} words'
                  + (f', {len(diag.warnings)} warning(s)' if diag.warnings else ''))
        except Exception as e:
            failures += 1
            msg = Diagnostics(f.name, f.read_text()).format_error(e) if isinstance(e, QdError) else repr(e)
            print(f'  FAIL  {f.name}: {msg}')
    print('errors')
    for f in sorted((HERE / 'errors').glob('*.qd')):
        src = f.read_text()
        expect = src.splitlines()[0].removeprefix('// expect:').strip()
        try:
            front_end(src, f.name, target)
        except QdError as e:
            text = Diagnostics(f.name, src).format_error(e)
            if expect in text:
                print(f'  ok    {f.name:24s} line {e.pos.line}: {e.msg[:60]}')
                continue
            print(f'  FAIL  {f.name}: expected {expect!r}, got:\n{text}')
        else:
            print(f'  FAIL  {f.name}: accepted, expected {expect!r}')
        failures += 1
    print('PASS' if not failures else f'{failures} FAILURE(S)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

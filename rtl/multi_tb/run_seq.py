"""Sequencing checks on RTL: does the physical pulse timing respect QD's source order?

Each case compiles a QD program, runs it on multicore_top (forcing the measurement bits where
a loop depends on them), turns every strobe into a pulse interval [start, start + length) on its
channel, and checks that every pulse of one group ends before any pulse of the next group
starts. It also checks that no timed instruction was reached after its timestamp (slack >= 0)
and that every core finished.

    source env.sh && python rtl/multi_tb/run_seq.py [CASE ...]
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from qdsl import backend
from qdsl.cli import front_end, quiet_qubic
from qdsl.target import Target

HERE = Path(__file__).parent
BUILD = HERE / 'build'
CONFIGS = HERE / '../../qdsl/tests/configs'
N_CORES = 3


@dataclass
class Case:
    name: str
    src: str
    order: list                      # groups of channels, e.g. [['Q0.qdrv', 'Q0.rdrv'], ['Q1.qdrv']]
    meas: str = ''                   # QD_MEAS
    config: str | None = None        # fixture in qdsl/tests/configs
    counts: dict = field(default_factory=dict)   # expected number of pulses per channel


LOOP_MEAS = '''qubit Q0, Q1;
m := 1;
do {
    X90(Q0);
    m = measure(Q0);
} while m == 1;
X90(Q1);
'''

LOOP_COUNT = '''qubit Q0, Q1;
n := 0;
do {
    X90(Q0);
    n += 1;
} while n < 5;
X90(Q1);
'''

CASES = [
    Case('loop_meas_two_cores', LOOP_MEAS, [['Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'], ['Q1.qdrv']], '0:1,1,0',
         counts={'Q0.qdrv': 3, 'Q0.rdlo': 3, 'Q1.qdrv': 1}),
    Case('loop_meas_two_cores_once', LOOP_MEAS, [['Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'], ['Q1.qdrv']], '0:0',
         counts={'Q0.qdrv': 1, 'Q1.qdrv': 1}),
    Case('loop_meas_one_core', LOOP_MEAS, [['Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'], ['Q1.qdrv']], '0:1,1,0',
         'shared_core', counts={'Q0.qdrv': 3, 'Q1.qdrv': 1}),
    Case('loop_count_two_cores', LOOP_COUNT, [['Q0.qdrv'], ['Q1.qdrv']], counts={'Q0.qdrv': 5, 'Q1.qdrv': 1}),
    Case('loop_count_one_core', LOOP_COUNT, [['Q0.qdrv'], ['Q1.qdrv']], config='shared_core',
         counts={'Q0.qdrv': 5, 'Q1.qdrv': 1}),
]


def compile_case(c: Case):
    t = Target() if c.config is None else Target(channels_path=str(CONFIGS / f'{c.config}.json'))
    ir, _ = front_end(c.src, f'{c.name}.qd', t)
    b = backend.build(ir, t)
    BUILD.mkdir(exist_ok=True)
    out = BUILD / f'seq_{c.name}.json'
    mems = {n.strip(':'): [f'{w:08x}' for w in np.frombuffer(buf, dtype='<u4')]
            for n, buf in b.exe.program_binaries.items() if 'command' not in n}
    words = b.words()
    if any(not name.startswith('qubit_command') or int(name.removeprefix('qubit_command')) >= N_CORES
           for name in words):
        raise RuntimeError(f'{c.name}: the testbench models qubit_command0..{N_CORES - 1}, got {sorted(words)}')
    json.dump({**{n: [f'{w:032x}' for w in ws] for n, ws in words.items()}, 'memories': mems}, open(out, 'w'))
    clk = t.fpga.fpga_clk_period
    lengths = {}
    for blk in b.compiler.ir_prog.blocknames_by_ind:
        for i in b.compiler.ir_prog.blocks[blk]['instructions']:
            if i.name == 'pulse':
                lengths[i.dest] = max(lengths.get(i.dest, 0), int(np.ceil(i.twidth / clk)))
    chan = {(next(iter(t.cores.cores_of(ch))).core_ind, t.channel_configs[ch].elem_ind): ch
            for ch in t.channel_configs if '.' in ch}
    return out, lengths, chan


def simulate(binary: Path, tag: str, meas: str) -> dict:
    out = BUILD / f'{tag}.result.json'
    out.unlink(missing_ok=True)
    env = dict(os.environ, QD_BIN=str(binary), QD_NSHOT='1', QD_OUT=str(out), QD_MEAS=meas, QD_MAX='2000000')
    subprocess.run(['make'], cwd=HERE, env=env, stdout=open(BUILD / f'{tag}.log', 'w'), stderr=subprocess.STDOUT)
    if not out.exists():
        raise RuntimeError(f'no result, see {BUILD / tag}.log')
    return json.load(open(out))


def intervals(r: dict, lengths: dict, chan: dict) -> list[tuple[int, int, str]]:
    out = []
    for e in r['events']:
        if e['kind'] == 'strobe':
            ch = chan[(e['core'], e['cfg'] & 3)]
            out.append((e['cycle'], e['cycle'] + lengths.get(ch, 0), ch))
    return sorted(out)


def check(c: Case, verbose=True) -> bool:
    binary, lengths, chan = compile_case(c)
    r = simulate(binary, f'seq_{c.name}', c.meas)
    iv = intervals(r, lengths, chan)
    t0 = min(e['cycle'] for e in r['events'] if e['kind'] == 'shot_start')
    ok, notes = True, []
    for ch, n in c.counts.items():
        got = sum(1 for _, _, d in iv if d == ch)
        if got != n:
            ok = False
            notes.append(f'{ch}: {got} pulses, expected {n}')
    for a, b in zip(c.order, c.order[1:]):
        ea = max((e for _, e, d in iv if d in a), default=None)
        sb = min((s for s, _, d in iv if d in b), default=None)
        if ea is None or sb is None:
            ok = False
            notes.append(f'missing pulses for {a} or {b}')
        elif sb < ea:
            ok = False
            notes.append(f'ORDER VIOLATED: {"/".join(b)} starts at {sb - t0}, before {"/".join(a)} ends at {ea - t0}')
        else:
            notes.append(f'{"/".join(b)} starts at {sb - t0} >= end of {"/".join(a)} at {ea - t0}')
    issues = [e for e in r['events'] if e['kind'] == 'issue']
    worst = min((e['slack'] for e in issues), default=None)
    if worst is not None and worst < 0:
        ok = False
    if not r['done']:
        ok = False
        notes.append('did not finish (a core hung)')
    notes.append(f'min trigger slack {worst} clocks')
    if verbose:
        print(f'  {"ok  " if ok else "FAIL"} {c.name}')
        for s, e, d in iv:
            print(f'         pulse {d:8s} [{s - t0:6d}, {e - t0:6d})')
        for n in notes:
            print(f'         {n}')
    return ok


def main(names) -> int:
    quiet_qubic()
    good = True
    for c in CASES:
        if not names or c.name in names:
            good &= check(c)
    print('PASS' if good else 'FAILURES')
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

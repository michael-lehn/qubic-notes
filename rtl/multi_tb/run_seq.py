"""Sequencing checks on RTL: does the physical pulse timing respect QD's source order?

Each case compiles a QD program, runs it on multicore_top (forcing the measurement bits where
a loop depends on them), turns every strobe into a pulse interval [start, start + length) on its
channel, and checks each (before, after) pair: every selected pulse of `before` ends before any
selected pulse of `after` starts. A selector is a channel (all its pulses) or 'channel@k' (its
k-th pulse; negative k counts from the end). It also checks that no timed instruction was
reached after its timestamp (slack >= 0) and that every core finished.

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
    order: list                      # (before, after) selector lists, e.g. [(['Q0.qdrv'], ['Q1.qdrv'])]
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

Q0_ALL = ['Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo']

PAR3 = 'qubit Q0, Q1, Q2;\nparallel {\n    X90(Q0);\n|\n    X90(Q1);\n}\nX90(Q2);\n'

CASES = [
    # a runtime loop, then another qubit
    Case('loop_meas_two_cores', LOOP_MEAS, [(Q0_ALL, ['Q1.qdrv'])], '0:1,1,0',
         counts={'Q0.qdrv': 3, 'Q0.rdlo': 3, 'Q1.qdrv': 1}),
    Case('loop_meas_two_cores_once', LOOP_MEAS, [(Q0_ALL, ['Q1.qdrv'])], '0:0',
         counts={'Q0.qdrv': 1, 'Q1.qdrv': 1}),
    Case('loop_meas_one_core', LOOP_MEAS, [(Q0_ALL, ['Q1.qdrv'])], '0:1,1,0',
         'shared_core', counts={'Q0.qdrv': 3, 'Q1.qdrv': 1}),
    Case('loop_count_two_cores', LOOP_COUNT, [(['Q0.qdrv'], ['Q1.qdrv'])], counts={'Q0.qdrv': 5, 'Q1.qdrv': 1}),
    Case('loop_count_one_core', LOOP_COUNT, [(['Q0.qdrv'], ['Q1.qdrv'])], config='shared_core',
         counts={'Q0.qdrv': 5, 'Q1.qdrv': 1}),
    # parallel { A | B }, then a join
    Case('par_three_cores', PAR3, [(['Q0.qdrv', 'Q1.qdrv'], ['Q2.qdrv'])]),
    Case('par_one_core', PAR3, [(['Q0.qdrv', 'Q1.qdrv'], ['Q2.qdrv'])], config='one_core'),
    Case('par_pair_core', PAR3, [(['Q0.qdrv', 'Q1.qdrv'], ['Q2.qdrv'])], config='pair_core'),
    Case('par_durations', 'qubit Q0, Q1, Q2; parallel { X90(Q0); X90(Q0); X90(Q0); | X90(Q1); } X90(Q2);',
         [(['Q0.qdrv@0'], ['Q0.qdrv@1']), (['Q0.qdrv@1'], ['Q0.qdrv@2']), (['Q0.qdrv', 'Q1.qdrv'], ['Q2.qdrv'])],
         counts={'Q0.qdrv': 3}),
    Case('par_nested', 'qubit Q0, Q1, Q2; parallel { parallel { X90(Q0); | X90(Q1); } X90(Q0); | X90(Q2); } X90(Q1);',
         [(['Q0.qdrv@0', 'Q1.qdrv@0'], ['Q0.qdrv@1']), (['Q0.qdrv', 'Q1.qdrv@0', 'Q2.qdrv'], ['Q1.qdrv@1'])]),
    Case('par_nested_one_core', 'qubit Q0, Q1, Q2; parallel { parallel { X90(Q0); | X90(Q1); } X90(Q0); '
         '| X90(Q2); } X90(Q1);',
         [(['Q0.qdrv@0', 'Q1.qdrv@0'], ['Q0.qdrv@1']), (['Q0.qdrv', 'Q1.qdrv@0', 'Q2.qdrv'], ['Q1.qdrv@1'])],
         config='one_core'),
    # runtime loops inside parallel branches
    Case('par_loop_and_static_then_join', 'qubit Q0, Q1, Q2; m := 1;\n'
         'parallel { do { X90(Q0); m = measure(Q0); } while m == 1; | X90(Q1); }\nX90(Q2);',
         [(Q0_ALL + ['Q1.qdrv'], ['Q2.qdrv'])], '0:1,1,0', counts={'Q0.qdrv': 3}),
    Case('par_loops_serialized', 'qubit Q0, Q1; m0 := 1; m1 := 1;\n'
         'parallel { do { X90(Q0); m0 = measure(Q0); } while m0 == 1; '
         '| do { X90(Q1); m1 = measure(Q1); } while m1 == 1; }\nmeasure(Q1);',
         [(Q0_ALL + ['Q1.qdrv', 'Q1.rdlo@-2'], ['Q1.rdrv@-1'])], '0:1,0;1:1,1,0',
         counts={'Q0.qdrv': 2, 'Q1.qdrv': 3, 'Q1.rdrv': 4}),
    Case('par_loops_one_core', 'qubit Q0, Q1; n := 0; k := 0;\n'
         'parallel { do { X90(Q0); n += 1; } while n < 3; | do { X90(Q1); k += 1; } while k < 2; }\nmeasure(Q0);',
         [(['Q0.qdrv', 'Q1.qdrv'], ['Q0.rdrv'])], config='shared_core', counts={'Q0.qdrv': 3, 'Q1.qdrv': 2}),
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


def select(iv: list, selectors: list) -> list[tuple[int, int]]:
    out = []
    for sel in selectors:
        ch, _, k = sel.partition('@')
        pulses = [(s, e) for s, e, d in iv if d == ch]
        if k:
            if -len(pulses) <= int(k) < len(pulses):
                out.append(pulses[int(k)])
        else:
            out += pulses
    return out


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
    for a, b in c.order:
        ea = max((e for _, e in select(iv, a)), default=None)
        sb = min((s for s, _ in select(iv, b)), default=None)
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

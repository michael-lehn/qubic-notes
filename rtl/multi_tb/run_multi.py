"""Multi-core checks on RTL: N cores + fproc_meas + shot sequencer.

Compiles QD programs (some with deliberately broken variants), runs them on
multicore_top, and checks the claims about cores that never synchronize at
runtime.

    source env.sh && python rtl/multi_tb/run_multi.py
"""
import copy
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import distproc.hwconfig as dhw

from qdsl import backend
from qdsl.cli import front_end, quiet_qubic
from qdsl.target import Target

HERE = Path(__file__).parent
EX = HERE / '../../qdsl/examples'
BUILD = HERE / 'build'
QDRV, RDRV, RDLO = 0, 1, 6                           # cfg values: element index (+ save_result for rdlo)


def emit(name: str, ir: list, target: Target) -> Path:
    b = backend.build(ir, target)
    mems = {n.strip(':'): [f'{w:08x}' for w in np.frombuffer(buf, dtype='<u4')]
            for n, buf in b.exe.program_binaries.items() if 'command' not in n}
    out = BUILD / f'{name}.json'
    json.dump({**{c: [f'{w:032x}' for w in ws] for c, ws in b.words().items()}, 'memories': mems}, open(out, 'w'))
    return out


def compile_qd(name: str, src: str, **fpga) -> list:
    target = Target()
    if fpga:
        target.fpga = dhw.FPGAConfig(**fpga)
    ir, _ = front_end((EX / src).read_text(), src, target)
    return ir, target


def simulate(binary: Path, tag: str, nshot=1, adc='1,1,1') -> dict:
    out = BUILD / f'{tag}.result.json'
    out.unlink(missing_ok=True)
    env = dict(os.environ, QD_BIN=str(binary), QD_NSHOT=str(nshot), QD_ADC=adc, QD_OUT=str(out))
    subprocess.run(['make'], cwd=HERE, env=env, stdout=open(BUILD / f'{tag}.log', 'w'), stderr=subprocess.STDOUT)
    if not out.exists():
        raise RuntimeError(f'no result, see {BUILD / tag}.log')
    return json.load(open(out))


def strobes(r, core=None, cfg=None, shot=None):
    return [e for e in r['events'] if e['kind'] == 'strobe' and (core is None or e['core'] == core)
            and (cfg is None or e['cfg'] == cfg) and (shot is None or e['shot'] == shot)]


def report(ok: bool, what: str, detail: str):
    print(f'  {"ok  " if ok else "FAIL"} {what:52s} {detail}')
    return ok


def main() -> int:
    quiet_qubic()
    BUILD.mkdir(exist_ok=True)
    good = True

    print('mc_align.qd: cross-core alignment without runtime sync')
    r = simulate(emit('mc_align', *compile_qd('mc_align', 'mc_align.qd')), 'mc_align')
    x1, x2 = strobes(r, 1, QDRV)[0], strobes(r, 2, QDRV)[0]
    rd1, rd2 = strobes(r, 1, RDRV)[0], strobes(r, 2, RDRV)[0]
    good &= report(x1['cycle'] == x2['cycle'], 'parallel X90s fire in the same clock', f"cycle {x1['cycle']} / {x2['cycle']}")
    good &= report(rd1['cycle'] == rd2['cycle'], 'par readout fires in the same clock', f"cycle {rd1['cycle']} / {rd2['cycle']}")

    print('mc_feedback.qd, 3 shots, Q0 measures 1, 0, 1: cross-core feedback')
    r = simulate(emit('mc_feedback', *compile_qd('mc_feedback', 'mc_feedback.qd')), 'mc_feedback', 3, '1,1;-1,1;1,1')
    played = [len(strobes(r, 1, QDRV, s)) == 2 for s in range(3)]
    good &= report(played == [True, False, True], 'X90s on Q1 (core 1) follow Q0 (core 0)', f'played per shot {played}')
    req = [e for e in r['events'] if e['kind'] == 'fproc_request']
    same = all(len({e['cycle'] for e in req if e['shot'] == s}) == 1 for s in range(3))
    good &= report(same, 'both cores request the result in the same clock', f"qclk {sorted({e['qclk'] for e in req})}")
    joins = {e['qclk'] for e in strobes(r, 1, RDRV)}
    good &= report(joins == {1406}, 'join readout at a fixed time in every shot', f'qclk {sorted(joins)}')
    starts = [e['cycle'] for e in r['events'] if e['kind'] == 'shot_start']
    periods = {b - a for a, b in zip(starts, starts[1:])}
    good &= report(len(periods) == 1, 'every shot takes the same time', f'{periods} clocks')
    regs = [e['meas_reg'] for e in req if e['core'] == 1]
    good &= report(regs[1] >> 1 & 1 == 1, "Q1's bit from shot 0 is still latched in shot 1", f'meas_reg per shot {regs}')

    print('mc_t1_runtime.qd: runtime delay on two cores')
    r = simulate(emit('mc_t1', *compile_qd('mc_t1', 'mc_t1_runtime.qd')), 'mc_t1')
    r0, r1 = [e['cycle'] for e in strobes(r, 0, RDRV)], [e['cycle'] for e in strobes(r, 1, RDRV)]
    pis = [e['cycle'] for e in strobes(r, 0, QDRV)][1::2]
    waits = [b - a for a, b in zip(pis, r0)]
    good &= report(r0 == r1, 'readouts aligned across cores every iteration', f'cycles {r0}')
    good &= report(waits == [16, 5016, 10016], 'pi -> readout grows by 10 us per iteration', f'{waits} clocks')

    print('negative: mc_feedback.qd with hold 62 clocks, Q0 measures 1 then 0')
    r = simulate(emit('mc_feedback_h62', *compile_qd('h62', 'mc_feedback.qd', fproc_meas_clks=62)),
                 'mc_feedback_h62', 2, '1,1;-1,1')
    played = [len(strobes(r, 1, QDRV, s)) == 2 for s in range(2)]
    good &= report(played == [False, True], "too-early read uses the PREVIOUS shot's bit",
                   f'X90s played per shot {played} (correct would be [True, False])')

    print('negative: mc_t1_runtime.qd with the clock shift on Q0 only')
    ir, target = compile_qd('t1_q0', 'mc_t1_runtime.qd')
    ir = copy.deepcopy(ir)

    def scope_q0(items):
        for i in items:
            if i.get('name') == 'inc_qclk':
                i['scope'] = ['Q0']
            for k in ('body', 'true', 'false'):
                scope_q0(i.get(k, []))
    scope_q0(ir)
    r = simulate(emit('mc_t1_q0', ir, target), 'mc_t1_q0')
    r0, r1 = [e['cycle'] for e in strobes(r, 0, RDRV)], [e['cycle'] for e in strobes(r, 1, RDRV)]
    skew = [a - b for a, b in zip(r0, r1)]
    good &= report(skew != [0] * len(skew), 'cores drift apart without the shared shift',
                   f'readout skew Q0 - Q1 per iteration {skew} clocks')

    print('PASS' if good else 'FAILURES')
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())

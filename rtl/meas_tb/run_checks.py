"""Find the real timing margins of measurement feedback on RTL (ex6_active_reset.qd).

Compiles the program with modified FPGAConfig constants, runs each on the
processor + fproc_meas + rdlo element model, and reports whether the branch saw
the fresh measurement and whether the conditional pulse fired.

    source env.sh && python rtl/meas_tb/run_checks.py
"""
import json
import os
import subprocess
from pathlib import Path

import distproc.hwconfig as dhw

from qdsl import backend
from qdsl.cli import front_end, quiet_qubic
from qdsl.target import Target

HERE = Path(__file__).parent
SRC = HERE / '../../qdsl/examples/ex6_active_reset.qd'
BUILD = HERE / 'build'


def compile_variant(name: str, **fpga) -> Path:
    target = Target()
    target.fpga = dhw.FPGAConfig(**fpga)
    ir, _ = front_end(SRC.read_text(), SRC.name, target)
    b = backend.build(ir, target)
    out = BUILD / f'{name}.json'
    mems = {n.strip(':'): [f'{w:08x}' for w in __import__('numpy').frombuffer(buf, dtype='<u4')]
            for n, buf in b.exe.program_binaries.items() if 'command' not in n}
    json.dump({**{c: [f'{w:032x}' for w in ws] for c, ws in b.words().items()}, 'memories': mems}, open(out, 'w'))
    return out


def simulate(binary: Path, adc: int, tag: str) -> dict | None:
    out = BUILD / f'{tag}.result.json'
    out.unlink(missing_ok=True)
    env = dict(os.environ, QD_BIN=str(binary), QD_ADC=str(adc), QD_OUT=str(out))
    subprocess.run(['make'], cwd=HERE, env=env, stdout=open(BUILD / f'{tag}.log', 'w'), stderr=subprocess.STDOUT)
    return json.load(open(out)) if out.exists() else None


def main():
    quiet_qubic()
    BUILD.mkdir(exist_ok=True)
    variants = [
        ('default (meas 64, jump_fproc 8)', 'default', {}),
        ('hold 63 clks', 'hold63', {'fproc_meas_clks': 63}),
        ('hold 62 clks', 'hold62', {'fproc_meas_clks': 62}),
        ('jump_fproc budget 7', 'jf7', {'jump_fproc_clks': 7}),
    ]
    print(f'{"variant":34} {"ADC":>4} {"bit":>4} {"meas_reg new":>12} {"FPROC sample":>12} '
          f'{"fresh?":>7} {"X90 strobes":>12} {"X90 slack":>9} {"done":>5}')
    for label, name, fpga in variants:
        binary = compile_variant(name, **fpga)
        for adc in (1, -1):
            r = simulate(binary, adc, f'{name}_adc{adc:+d}')
            if r is None:
                print(f'{label:34} {adc:4d}   simulation produced no report (see build/{name}_adc{adc:+d}.log)')
                continue
            sample = r['fproc_enable'] + 1                       # fproc_meas latches data one clock after enable
            upd = r['meas_reg_update']
            fresh = 'yes' if upd is not None and upd <= sample else ('n/a' if upd is None else 'STALE')
            x90 = [q for q, cfg in r['strobes'] if cfg & 3 == 0]
            cond = [(op, q, t) for op, q, t in r['decodes'] if op == 'pulse_write_trig' and 1370 < t < 1400]
            slack = cond[0][2] - cond[0][1] if cond else None
            print(f'{label:34} {adc:4d} {r["meas_bit"]:4d} {str(upd):>12} {sample:12d} {fresh:>7} '
                  f'{str(x90):>12} {str(slack):>9} {str(r["done"]):>5}')


if __name__ == '__main__':
    main()

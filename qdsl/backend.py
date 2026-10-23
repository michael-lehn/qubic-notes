"""QubiC-IR -> distributed processor assembly -> 128-bit words, plus reports.

The instruction decoder is ours, written from distproc/command_gen.py."""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import distproc.assembler as am
import distproc.command_gen as cg
import distproc.compiler as cm
import qubic.rfsoc.hwconfig as rfhw

from .target import INSTR_MEM_WORDS, Target

_OPC = {v: k for k, v in cg.opcodes.items()}
_ALU = {v: k for k, v in cg.alu_opcodes.items()}


@dataclass
class Build:
    ir: list
    compiler: cm.Compiler
    asm: cm.CompiledProgram
    exe: object

    def words(self) -> dict[str, list[int]]:
        out = {}
        for name, buf in self.exe.program_binaries.items():
            if 'command' in name:
                out[name.strip(':')] = [int.from_bytes(buf[a:a + 16], 'little') for a in range(0, len(buf), 16)]
        return out


def build(ir: list, target: Target) -> Build:
    # QubiC defaults to name patterns ('{qubit}.qdrv', ...) for both mappings; use the
    # channel configuration instead, so QubiC's cores are QD's CoreIds.
    grouping = target.cores.proc_grouping()
    passes = cm.get_passes(target.fpga, target.qchip, qubit_grouping=target.cores.qubit_scoper(),
                           proc_grouping=grouping)
    comp = cm.Compiler(copy.deepcopy(ir), grouping)
    comp.run_ir_passes(passes)
    asm = comp.compile()
    exe = am.GlobalAssembler(asm, target.channel_configs, rfhw.elemconfig_classfactory).get_assembled_program()
    b = Build(ir, comp, asm, exe)
    for name, ws in b.words().items():
        if len(ws) > INSTR_MEM_WORDS:
            raise RuntimeError(f'{name}: {len(ws)} instructions exceed the {INSTR_MEM_WORDS}-word memory')
    return b


# ---------------------------------------------------------------- decoding

def _bits(w, lo, n):
    return (w >> lo) & ((1 << n) - 1)


def decode(w: int) -> str:
    name = _OPC.get(_bits(w, 123, 5))
    if name in ('pulse_write', 'pulse_write_trig'):
        pos, wid = cg.pulse_field_pos, cg.pulse_field_widths
        f = [f't={_bits(w, pos["cmd_time"], 32)}'] if name == 'pulse_write_trig' else []
        if _bits(w, pos['cfg'] + 4, 1):
            f.append(f'cfg={_bits(w, pos["cfg"], 4)}')
        for fld in ('amp', 'freq', 'phase', 'env_word'):
            en, mux = _bits(w, pos[fld] + wid[fld] + 1, 1), _bits(w, pos[fld] + wid[fld], 1)
            if en:
                f.append(f'{fld}=r{_bits(w, 116, 4)}' if mux else f'{fld}={_bits(w, pos[fld], wid[fld])}')
        return f'{name:16s} ' + ' '.join(f)
    op8 = _bits(w, 120, 8)
    name = _OPC.get(op8 >> 3, f'?{op8 >> 3:05b}')
    if name.removesuffix('_i') in ('reg_alu', 'jump_cond', 'alu_fproc', 'jump_fproc', 'inc_qclk'):
        base = name.removesuffix('_i')
        v = _bits(w, 88, 32)
        in0 = f'#{v - (1 << 32) if v >> 31 else v}' if name.endswith('_i') else f'r{_bits(w, 116, 4)}'
        f = [f'alu={_ALU[op8 & 7]}', f'in0={in0}']
        if base in ('reg_alu', 'jump_cond'):
            f.append(f'in1=r{_bits(w, 84, 4)}')
        if base in ('reg_alu', 'alu_fproc'):
            f.append(f'out=r{_bits(w, 80, 4)}')
        if base in ('jump_cond', 'jump_fproc'):
            f.append(f'->@{_bits(w, 68, 16)}')
        if base in ('alu_fproc', 'jump_fproc'):
            f.append(f'func_id={_bits(w, 52, 8)}')
        return f'{name:16s} ' + ' '.join(f)
    if name == 'jump_i':
        return f'{name:16s} ->@{_bits(w, 68, 16)}'
    if name == 'idle':
        return f'{name:16s} until t={_bits(w, 5, 32)}'
    return name or '?'


# ---------------------------------------------------------------- reports

def timing(b: Build, target: Target) -> str:
    clk = target.fpga.fpga_clk_period
    prog = b.compiler.ir_prog
    loops = {name: lp for name, lp in prog.loops.items()}
    rows = []
    for blk in prog.blocknames_by_ind:
        for ins in prog.blocks[blk]['instructions']:
            if ins.name == 'pulse':
                n = int(np.ceil(ins.twidth / clk))
                rows.append((ins.start_time, ins.dest, n, ins.tag or '', blk))
            elif ins.name == 'idle':
                rows.append((ins.end_time, 'idle', 0, 'wait for measurement', blk))
    out = [f'{"start":>8} {"[us]":>9}  {"channel":9} {"len":>5}  {"source":10} block']
    for t, dest, n, tag, blk in sorted(rows):
        out.append(f'{t:8d} {t * clk * 1e6:9.3f}  {dest:9} {n:5d}  {tag:10} {blk}')
    for name, lp in loops.items():
        out.append(f'loop {name}: body {lp.delta_t} clks = {lp.delta_t * clk * 1e6:.3f} us per iteration')
    shifts = [(blk, i.var) for blk in prog.blocknames_by_ind for i in prog.blocks[blk]['instructions']
              if i.name == 'inc_qclk']
    for blk, var in shifts:
        out.append(f'runtime delay in {blk}: every later time on all cores shifts by the register value '
                   f'(static times above exclude it)')
    return '\n'.join(out)


def listing(b: Build) -> str:
    out = []
    for name, ws in sorted(b.words().items()):
        out.append(f'{name}  ({len(ws)} words)')
        out += [f'  @{i:<4d} {w:032x}  {decode(w)}' for i, w in enumerate(ws)]
    return '\n'.join(out)


def assembly(b: Build) -> str:
    out = []
    for core, prog in sorted(b.asm.program.items()):
        out.append(f'core {core}')
        for ins in prog:
            d = {k: v for k, v in ins.items() if k != 'op'}
            if isinstance(d.get('env'), dict):
                d['env'] = d['env']['env_func']
            out.append(f"  {ins['op']:12s} " + ', '.join(f'{k}={v:.6g}' if isinstance(v, float) else f'{k}={v}'
                                                        for k, v in d.items()))
    return '\n'.join(out)

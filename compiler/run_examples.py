"""Compile QubiC-IR examples through the real distproc toolchain and dump
IR / per-core assembly / 128-bit machine words (decoded).

The decoder below is written by me from distproc/command_gen.py field layout;
it is NOT part of QubiC.
"""
import copy
import json
import logging
import os
import sys

import numpy as np

import distproc.assembler as am
import distproc.command_gen as cg
import distproc.compiler as cm
import distproc.hwconfig as dhw
import qubic.rfsoc.hwconfig as rfhw
import qubitconfig.qchip as qc

logging.basicConfig(level=logging.WARNING, format='    [log %(levelname)s %(module)s] %(message)s')

QUBIC_ROOT = os.environ.get('QUBIC_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'vendor'))
SW = f'{QUBIC_ROOT}/software/examples'
QCHIP = qc.QChip(f'{SW}/qubitcfg.json')
CHAN_CFG = dhw.load_channel_configs(f'{SW}/channel_config.json')
FPGA_CFG = dhw.FPGAConfig()

OPC = {v: k for k, v in cg.opcodes.items()}
ALU = {v: k for k, v in cg.alu_opcodes.items()}


def bits(w, lo, n):
    return (w >> lo) & ((1 << n) - 1)


def s32(v):
    return v - (1 << 32) if v & (1 << 31) else v


def decode(w):
    op5 = bits(w, 123, 5)
    name = OPC.get(op5)
    if name in ('pulse_write', 'pulse_write_trig'):
        f = []
        pos, wid = cg.pulse_field_pos, cg.pulse_field_widths
        if name == 'pulse_write_trig':
            f.append(f't={bits(w, pos["cmd_time"], 32)}')
        if bits(w, pos['cfg'] + 4, 1):
            f.append(f'cfg={bits(w, pos["cfg"], 4)}')
        for fld in ('amp', 'freq', 'phase', 'env_word'):
            en = bits(w, pos[fld] + wid[fld] + 1, 1)
            mux = bits(w, pos[fld] + wid[fld], 1)
            if en and mux:
                f.append(f'{fld}=r{bits(w, 116, 4)}')
            elif en:
                f.append(f'{fld}={bits(w, pos[fld], wid[fld])}')
        return f'{name:16s} ' + ' '.join(f)
    op8 = bits(w, 120, 8)
    op5b, alu = op8 >> 3, op8 & 7
    name = OPC.get(op5b, f'?{op5b:05b}')
    if name in ('reg_alu', 'reg_alu_i', 'jump_cond', 'jump_cond_i', 'alu_fproc', 'alu_fproc_i',
                'jump_fproc', 'jump_fproc_i', 'inc_qclk', 'inc_qclk_i'):
        imm = name.endswith('_i')
        in0 = f'#{s32(bits(w, 88, 32))}' if imm else f'r{bits(w, 116, 4)}'
        f = [f'alu={ALU[alu]}', f'in0={in0}']
        base = name.removesuffix('_i')
        if base in ('reg_alu', 'jump_cond'):
            f.append(f'in1=r{bits(w, 84, 4)}')
        if base in ('reg_alu', 'alu_fproc'):
            f.append(f'out=r{bits(w, 80, 4)}')
        if base in ('jump_cond', 'jump_fproc'):
            f.append(f'->@{bits(w, 68, 8)}')
        if base in ('alu_fproc', 'jump_fproc'):
            f.append(f'func_id={bits(w, 52, 16)}')
        return f'{name:16s} ' + ' '.join(f)
    if name == 'jump_i':
        return f'{name:16s} ->@{bits(w, 68, 8)}'
    if name == 'idle':
        return f'{name:16s} until t={bits(w, 5, 32)}'
    return f'{name or "?":16s}'


def fmt_asm(instr):
    d = {k: v for k, v in instr.items() if k != 'op'}
    if 'env' in d and isinstance(d['env'], dict):
        d['env'] = f"{d['env']['env_func']}({', '.join(f'{k}={v:g}' for k, v in d['env']['paradict'].items())})"
    elif 'env' in d and isinstance(d['env'], (list, np.ndarray)):
        d['env'] = f'<{len(d["env"])} samples>'
    for k in ('freq', 'phase'):
        if isinstance(d.get(k), float):
            d[k] = f'{d[k]:.6g}'
    return f"{instr['op']:12s} " + ', '.join(f'{k}={v}' for k, v in d.items())


def run(title, program, flags=None, show_ir=True, cores=None):
    print('=' * 100)
    print(title)
    print('=' * 100)
    passes = cm.get_passes(FPGA_CFG, QCHIP, compiler_flags=flags)
    comp = cm.Compiler(copy.deepcopy(program))
    comp.run_ir_passes(passes)
    if show_ir:
        print('--- IR after all passes (basic blocks, scheduled) ---')
        for b in comp.ir_prog.blocknames_by_ind:
            blk = comp.ir_prog.blocks[b]
            print(f'  [{b}] start={blk.get("start_time")} dur={blk.get("duration")} '
                  f'succ={list(comp.ir_prog.control_flow_graph.successors(b))}')
            for ins in blk['instructions']:
                d = ins.to_dict() if hasattr(ins, 'to_dict') else {'name': ins.name}
                if 'env' in d and isinstance(d['env'], list) and len(d['env']) > 4:
                    d['env'] = f'<{len(d["env"])} samples>'
                if hasattr(ins, 'start_time') and ins.start_time is not None:
                    d['start_time'] = ins.start_time
                print(f'      {d}')
        if comp.ir_prog.loops:
            print('  loops:', {k: v.to_dict() for k, v in comp.ir_prog.loops.items()})
    cprog = comp.compile()
    print('--- Distributed-processor assembly (per core) ---')
    for core, prog in sorted(cprog.program.items()):
        if cores and core[0].split('.')[0] not in cores:
            continue
        print(f'  core {core}:')
        for i in prog:
            print(f'      {fmt_asm(i)}')
    asm = am.GlobalAssembler(cprog, CHAN_CFG, rfhw.elemconfig_classfactory)
    exe = asm.get_assembled_program()
    print('--- Machine code (128-bit words, little-endian in BRAM) ---')
    for name, buf in sorted(exe.program_binaries.items()):
        if 'command' in name:
            if cores and not any(name.endswith(str(CHAN_CFG[f'{q}.qdrv'].core_ind)) for q in cores):
                continue
            print(f'  {name}:')
            for a in range(0, len(buf), 16):
                w = int.from_bytes(buf[a:a + 16], 'little')
                print(f'      @{a // 16:<3d} {w:032x}  {decode(w)}')
        else:
            print(f'  {name}: {len(buf)} bytes')
    print('  result channels:', {k: (v.mem_name, v.reads_per_shot) for k, v in exe.result_channels.items()})
    print()
    return comp, cprog, exe


EX = {}

# 0. The user's amplitude sweep (verbatim from the question)
EX['0'] = ('Ex0: user amplitude sweep (verbatim IR from question)', [
    {'name': 'declare', 'var': 'amp', 'scope': ['Q0'], 'dtype': 'amp'},
    {'name': 'set_var', 'value': 0.1, 'var': 'amp'},
    {'name': 'loop', 'cond_lhs': 1.0, 'alu_cond': 'ge', 'cond_rhs': 'amp', 'scope': ['Q0'], 'body': [
        {'name': 'delay', 't': 500.e-6},
        {'name': 'pulse', 'phase': 0, 'freq': 4944383311, 'amp': 'amp', 'twidth': 2.4e-08,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}}, 'dest': 'Q0.qdrv'},
        {'name': 'read', 'qubit': 'Q0'},
        {'name': 'alu', 'op': 'add', 'lhs': 0.1, 'rhs': 'amp', 'out': 'amp'}]}])

# 1. int variable = 42
EX['1'] = ('Ex1: declare int x; x = 42', [
    {'name': 'declare', 'var': 'x', 'scope': ['Q0'], 'dtype': 'int'},
    {'name': 'set_var', 'var': 'x', 'value': 42}])

# 2. add two int vars
EX['2'] = ('Ex2: c = a + b', [
    {'name': 'declare', 'var': 'a', 'scope': ['Q0'], 'dtype': 'int'},
    {'name': 'declare', 'var': 'b', 'scope': ['Q0'], 'dtype': 'int'},
    {'name': 'declare', 'var': 'c', 'scope': ['Q0'], 'dtype': 'int'},
    {'name': 'set_var', 'var': 'a', 'value': 3},
    {'name': 'set_var', 'var': 'b', 'value': 4},
    {'name': 'alu', 'op': 'add', 'lhs': 'a', 'rhs': 'b', 'out': 'c'}])

# 3. counter loop: 5 x X90
EX['3'] = ('Ex3: counter loop, i = 0; do { X90(Q0); i += 1; } while (5 > i)', [
    {'name': 'declare', 'var': 'i', 'scope': ['Q0'], 'dtype': 'int'},
    {'name': 'set_var', 'var': 'i', 'value': 0},
    {'name': 'loop', 'cond_lhs': 5, 'alu_cond': 'ge', 'cond_rhs': 'i', 'scope': ['Q0'], 'body': [
        {'name': 'X90', 'qubit': ['Q0']},
        {'name': 'alu', 'op': 'add', 'lhs': 1, 'rhs': 'i', 'out': 'i'}]}])

# 4. shaped pulse
EX['4'] = ('Ex4: one shaped pulse on Q0.qdrv (named freq, constant params)', [
    {'name': 'pulse', 'dest': 'Q0.qdrv', 'freq': 'Q0.freq', 'phase': np.pi / 2, 'amp': 0.5,
     'twidth': 32e-9, 'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}}}])

# 5. measurement
EX['5'] = ('Ex5: measure Q0 (read gate)', [
    {'name': 'read', 'qubit': ['Q0']}])

# 6. conditional on measurement (active reset style)
EX['6'] = ('Ex6: if (measure(Q0) == 1) { X90(Q0); X90(Q0); }', [
    {'name': 'read', 'qubit': ['Q0']},
    {'name': 'branch_fproc', 'cond_lhs': 1, 'alu_cond': 'eq', 'func_id': 'Q0.meas', 'scope': ['Q0'],
     'true': [{'name': 'X90', 'qubit': ['Q0']}, {'name': 'X90', 'qubit': ['Q0']}],
     'false': []},
    {'name': 'read', 'qubit': ['Q0']}])

# 7. two qubits: parallel X90s, CNOT, simultaneous readout
EX['7'] = ('Ex7: X90(Q1); X90(Q2); CNOT(Q2,Q1); read(Q1); read(Q2)', [
    {'name': 'X90', 'qubit': ['Q1']},
    {'name': 'X90', 'qubit': ['Q2']},
    {'name': 'CNOT', 'qubit': ['Q2', 'Q1']},
    {'name': 'read', 'qubit': ['Q1']},
    {'name': 'read', 'qubit': ['Q2']}])

# 7b. same as 7 but raw pulses with no barrier: shows ASAP-per-channel
EX['7b'] = ('Ex7b: three raw pulses written "sequentially" on Q0.qdrv, Q1.qdrv, Q0.rdrv', [
    {'name': 'pulse', 'dest': d, 'freq': f, 'phase': 0, 'amp': 0.5, 'twidth': 32e-9,
     'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}}}
    for d, f in [('Q0.qdrv', 'Q0.freq'), ('Q1.qdrv', 'Q1.freq'), ('Q0.rdrv', 'Q0.readfreq')]])

if __name__ == '__main__':
    keys = sys.argv[1:] or list(EX)
    for k in keys:
        title, prog = EX[k]
        try:
            run(title, prog)
        except Exception as e:
            print(f'  !! {type(e).__name__}: {e}\n')

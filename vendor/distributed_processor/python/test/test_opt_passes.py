import pytest
import numpy as np
import ipdb
import distproc.compiler as cm
import distproc.ir.ir as ir
import distproc.ir.passes as ps
import distproc.ir.instructions as iri
import distproc.assembler as am
import distproc.hwconfig as hw
import qubitconfig.qchip as qc
import json
import difflib
import logging
try:
    from rich import print
except:
    pass

logging.basicConfig(level=logging.DEBUG)

def test_hw_virtualz_opt():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()
    program = [{'name': 'declare', 'var': 'q0_phase', 'scope': ['Q0'], 'dtype': 'phase'},
               {'name': 'bind_phase', 'var': 'q0_phase', 'freq': 'Q0.freq'},#'qubit': 'Q0'},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/4},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']}]
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(optimize_reg_ops=True))[:10]
    compiler.run_ir_passes(passes)
    print(passes)
    for statement in compiler.ir_prog.blocks['block_0']['instructions']:
        print(statement)

    with open('test_outputs/test_opt_hw_virtualz.txt', 'r') as f:
        filein = f.read().rstrip('\n')

    try:
        assert compiler.ir_prog.serialize() == filein

    except AssertionError as err:
        with open('test_outputs/test_opt_hw_virtualz_err.txt', 'w') as ferr:
            ferr.write(compiler.ir_prog.serialize())

        raise err

def test_hw_virtualz_twocycle():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()
    program = [{'name': 'declare', 'var': 'q0_phase', 'scope': ['Q0'], 'dtype': 'phase'},
               {'name': 'bind_phase', 'var': 'q0_phase', 'freq': 'Q0.freq'},#'qubit': 'Q0'},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/4},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/4},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']}]
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(optimize_reg_ops=True))[:10]
    compiler.run_ir_passes(passes)
    print(passes)
    for statement in compiler.ir_prog.blocks['block_0']['instructions']:
        print(statement)

    with open('test_outputs/test_opt_hw_virtualz_twocycle.txt', 'r') as f:
        filein = f.read().rstrip('\n')

    try:
        assert compiler.ir_prog.serialize() == filein

    except AssertionError as err:
        with open('test_outputs/test_opt_hw_virtualz_twocycle_err.txt', 'w') as ferr:
            ferr.write(compiler.ir_prog.serialize())

        raise err

def test_read_fproc():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()
    program = [iri.Declare(var='fpread', scope='Q0'),
               iri.Declare(var='junk', scope='Q0'),
               iri.ReadFproc(func_id=0, scope='Q0', var='fpread'),
               iri.ReadFproc(func_id=0, scope='Q0', var='fpread'),
               iri.Alu(lhs='fpread', rhs='junk', out='junk', op='add'),
               iri.ReadFproc(func_id=0, scope='Q0', var='fpread'),
               iri.Alu(lhs=2, rhs='fpread', out='fpread', op='add'),
               iri.Alu(lhs=5, rhs='fpread', out='fpread', op='add'),
               iri.Alu(lhs=7, rhs='fpread', out='fpread', op='add')]

    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(optimize_reg_ops=True))[:10]
    compiler.run_ir_passes(passes)
    print(passes)
    for statement in compiler.ir_prog.blocks['block_0']['instructions']:
        print(statement)
        
    with open('test_outputs/test_opt_read_fproc.txt', 'r') as f:
        filein = f.read().rstrip('\n')

    try:
        assert compiler.ir_prog.serialize() == filein

    except AssertionError as err:
        with open('test_outputs/test_opt_read_fproc_err.txt', 'w') as ferr:
            ferr.write(compiler.ir_prog.serialize())

        raise err

def test_hw_virtualz_loop():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()
    program = [{'name': 'declare', 'var': 'q0_phase', 'scope': ['Q0'], 'dtype': 'phase'},
               {'name': 'declare', 'var': 'loopind', 'dtype': 'int', 'scope': ['Q0']},
               {'name': 'bind_phase', 'var': 'q0_phase', 'freq': 'Q0.freq'},#'qubit': 'Q0'},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3},

               {'name': 'loop', 'cond_lhs': 10, 'cond_rhs': 'loopind', 'alu_cond': 'ge', 
                'scope': ['Q0'], 'body':[
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3},
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3},
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
                    {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/3}]
                },

               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']}]
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(optimize_reg_ops=True))[:10]
    compiler.run_ir_passes(passes)
    print(passes)
    print(compiler.ir_prog.serialize())
    with open('test_outputs/test_opt_virtualz_loop.txt', 'r') as f:
        filein = f.read().rstrip('\n')

    try:
        assert compiler.ir_prog.serialize() == filein

    except AssertionError as err:
        with open('test_outputs/test_opt_virtualz_loop.txt', 'w') as ferr:
            ferr.write(compiler.ir_prog.serialize())

        raise err

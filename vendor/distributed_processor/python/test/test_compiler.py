import pytest
import numpy as np
import os
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
try:
    from rich import print
except:
    pass

def elementconfigtest_factory(*args, **kwargs):
    return ElementConfigTest

class ElementConfigTest(hw.ElementConfig):
    def __init__(self, samples_per_clk, interp_ratio):
        super().__init__(2.e-9, samples_per_clk)
        self._freqs = []
        self._envs = {}

    def compile_envs(self):
        return np.zeros(10).tobytes(), {'asdf': 0}

    def compile_freqs(self):
        freq_ind_map = {f: self._freqs.index(f) for f in self._freqs}
        return np.asarray(self._freqs).tobytes(), freq_ind_map

    def add_env(self, env):
        self._envs['asdf'] = env
        return 'asdf'

    def add_freq(self, freq, freq_ind):
        self._freqs.append(freq)

    def get_cw_env_word(self, env_start_ind, env_length):
        return 0

    def length_nclks(self, tlength):
        return int(np.ceil(tlength/self.fpga_clk_period))

    def get_cfg_word(self, elem_ind, mode_bits):
        return elem_ind

def compare_output(serialized_prog: str, prog_name: str, dirname: str = './test_outputs'):
    reference_outfile = os.path.join(dirname, prog_name + '_out.txt')
    errfile = os.path.join(dirname, prog_name + '_err.txt')
    if os.path.isfile(reference_outfile):
        with open(reference_outfile, 'r') as f:
            filein = f.read().rstrip('\n')
            try:
                assert serialized_prog == filein
            except AssertionError as err:
                with open(errfile, 'w') as ferr:
                    ferr.write(serialized_prog)

                raise err

    else:
        with open(reference_outfile, 'w') as f:
            f.write(serialized_prog)
            raise Exception(f'outfile: {reference_outfile} not found, writing current test output')



def test_phase_resolve():
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    fpga_config = hw.FPGAConfig(**fpga_config)
    qchip = qc.QChip('qubitcfg.json')
    program = []
    program.append({'name':'X90', 'qubit': ['Q0']})
    program.append({'name':'X90', 'qubit': ['Q1']})
    program.append({'name':'X90Z90', 'qubit': ['Q0']})
    program.append({'name':'X90', 'qubit': ['Q0']})
    program.append({'name':'virtual_z', 'qubit': ['Q0'], 'phase': np.pi/4})
    program.append({'name':'X90', 'qubit': ['Q0']})
    program.append({'name':'X90', 'qubit': ['Q1']})
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    pulse_list = compiler.ir_prog.blocks['block_0']['instructions']
    assert pulse_list[0].phase == 0
    assert pulse_list[1].phase == 0
    assert pulse_list[3].phase == np.pi/2
    assert pulse_list[4].phase == 3*np.pi/4
    assert pulse_list[5].phase == 0
    return compiler.ir_prog

def test_basic_schedule():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name':'X90', 'qubit': ['Q0']},
            {'name':'X90', 'qubit': ['Q1']},
            {'name':'X90Z90', 'qubit': ['Q0']},
            {'name':'X90', 'qubit': ['Q0']},
            {'name':'X90', 'qubit': ['Q1']},
            {'name':'read', 'qubit': ['Q0']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    pulse_list = compiler.ir_prog.blocks['block_0']['instructions']
    assert pulse_list[0].start_time == 5
    assert pulse_list[1].start_time == 5
    assert pulse_list[2].start_time == 21 #scheduled_prog[0]['gate'].contents[0].twidth
    assert pulse_list[3].start_time == 37 #scheduled_prog[0]['gate'].contents[0].twidth \
    assert pulse_list[4].start_time == 13 #scheduled_prog[1]['gate'].contents[0].twidth
    assert pulse_list[5].start_time == 53 #scheduled_prog[0]['gate'].contents[0].twidth \
              #+ scheduled_prog[2]['gate'].contents[0].twidth + scheduled_prog[3]['gate'].contents[0].twidth
def test_pulse_compile():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name':'X90', 'qubit': ['Q0']},
               {'name':'X90', 'qubit': ['Q1']},
               {'name':'X90Z90', 'qubit': ['Q0']},
               {'name':'X90', 'qubit': ['Q0']},
               {'name':'X90', 'qubit': ['Q1']},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv'},
               {'name':'read', 'qubit': ['Q0']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_pulse_compile')

def test_compiledprog_serialize():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name':'X90', 'qubit': ['Q0']},
               {'name':'X90', 'qubit': ['Q1']},
               {'name':'X90Z90', 'qubit': ['Q0']},
               {'name':'X90', 'qubit': ['Q0']},
               {'name':'X90', 'qubit': ['Q1']},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv'},
               {'name':'read', 'qubit': ['Q0']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()
    progstr = prog.serialize()
    assert progstr == cm.deserialize_compiled_program(progstr).serialize()
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

def test_pulse_compile_ir():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [iri.Gate('X90', 'Q0'),
                iri.Gate('X90', 'Q1'),
                iri.Gate('X90Z90', 'Q0'),
                iri.Gate('X90', 'Q0'),
                iri.Gate('X90', 'Q1'),
                iri.Pulse(phase=np.pi/2, freq='Q0.freq', env=np.ones(100), twidth=24.e-9,
                          amp=0.5, dest='Q0.qdrv'),
                iri.Gate('read', 'Q0')]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_pulse_compile_ir')

def test_pulse_compile_nogate():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv'},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100, dtype=np.float32), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.rdrv'},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv'},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 1234234, 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q1.qdrv'},
               {'name':'read', 'qubit': ['Q0']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, 
                           compiler_flags={'schedule':True, 'resolve_gates': True})
    passes.append(ps.LintSchedule(fpga_config, proc_grouping=[('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]))
    compiler.run_ir_passes(passes)
    prog = compiler.compile()
    print(prog.program)
    return prog

#def test_linear_cfg():
#    qchip = qc.QChip('qubitcfg.json')
#    fpga_config = {'alu_instr_clks': 2,
#                   'fpga_clk_period': 2.e-9,
#                   'jump_cond_clks': 3,
#                   'jump_fproc_clks': 4,
#                   'pulse_regwrite_clks': 1}
#    program = [{'name': 'X90', 'qubit': ['Q0']},
#               {'name': 'X90', 'qubit': ['Q1']}]
#    fpga_config = hw.FPGAConfig(**fpga_config)
#    compiler = cm.Compiler(program, 'by_qubit', fpga_config, qchip)
#    compiler._make_basic_blocks()
#    print('basic_blocks{}'.format(compiler._basic_blocks))
#    compiler._generate_cfg()
#    print('cfg {}'.format(compiler._control_flow_graph))
#    assert True


#def test_onebranch_cfg():
#    qchip = qc.QChip('qubitcfg.json')
#    fpga_config = {'alu_instr_clks': 2,
#                   'fpga_clk_period': 2.e-9,
#                   'jump_cond_clks': 3,
#                   'jump_fproc_clks': 4,
#                   'pulse_regwrite_clks': 1}
#    program = [{'name': 'X90', 'qubit': ['Q0']},
#               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 0, 
#                'func_id': 0, 'true': [{'name': 'X90', 'qubit': ['Q0']}],
#                'false': [{'name': 'X90', 'qubit': ['Q1']}], 'scope':['Q0', 'Q1']},
#               {'name': 'X90', 'qubit': ['Q1']}]
#    fpga_config = hw.FPGAConfig(**fpga_config)
#    compiler = cm.Compiler(program, 'by_qubit', fpga_config, qchip)
#    compiler._make_basic_blocks()
#    compiler._generate_cfg()
#    for blockname, block in compiler._basic_blocks.items():
#        print('{}: {}'.format(blockname, block))
#
#    for source, dest in compiler._control_flow_graph.items():
#        print('{}: {}'.format(source, dest))
#    for source, dest in compiler._global_cfg.items():
#        print('{}: {}'.format(source, dest))
#    assert True


def test_multrst_cfg():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 1,
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q0']}], 'scope':['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 0,
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q1']}], 'scope':['Q1']},
               {'name': 'X90', 'qubit': ['Q1']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    # ipdb.set_trace()
    prog = compiler.compile()
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_multirst_cfg')

def test_multrst_fproc_res_cfg():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()

    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q0']}], 'scope':['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q1']}], 'scope':['Q1']},
               {'name': 'X90', 'qubit': ['Q1']}]
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip)
    # passes.append(ps.LintSchedule(fpga_config, proc_grouping=[('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]))
    compiler.run_ir_passes(passes)
    prog = compiler.compile()
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_multirst_fproc_res_cfg')

def test_fproc_hold():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()

    program = [{'name': 'block', 'body':[
                   {'name': 'X90', 'qubit': ['Q0']},
                   {'name': 'read', 'qubit': ['Q0']},
                   {'name': 'X90', 'qubit': ['Q0']}]},
               {'name': 'read', 'qubit': ['Q1']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q0']}], 'scope':['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q1']}], 'scope':['Q1']},
               {'name': 'X90', 'qubit': ['Q1']}]
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    # ipdb.set_trace()
    prog = compiler.compile()
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_fproc_hold')

def test_linear_compile():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'read', 'qubit': ['Q0']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()
    print()
    print('lincomp_prog')
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_linear_compile')

#TODO: refactor test with new format
# def test_linear_compile_globalasm():
#     qchip = qc.QChip('qubitcfg.json')
#     fpga_config = {'alu_instr_clks': 2,
#                    'fpga_clk_period': 2.e-9,
#                    'jump_cond_clks': 3,
#                    'jump_fproc_clks': 4,
#                    'pulse_regwrite_clks': 1}
#     program = [{'name': 'X90', 'qubit': ['Q0']},
#                {'name': 'X90', 'qubit': ['Q1']},
#                {'name': 'read', 'qubit': ['Q0']}]
#     fpga_config = hw.FPGAConfig(**fpga_config)
#     channel_configs = hw.load_channel_configs('../test/channel_config.json')
#     compiler = cm.Compiler(program)
#     compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
#     compiled_prog = compiler.compile()
#     #compiled_prog = cm.CompiledProgram(compiler.asm_progs, fpga_config)
# 
#     globalasm = am.GlobalAssembler(compiled_prog, channel_configs, elementconfigtest_factory)
#     asm_prog = globalasm.get_assembled_program()
#     sorted_prog = {chan_ind: {buffer: asm_prog[chan_ind][buffer] for buffer in sorted(asm_prog[chan_ind].keys())} 
#                       for chan_ind in sorted(asm_prog.keys())}
#     with open('test_outputs/test_linear_compile_globalasm.txt', 'r') as f:
#         assert str(sorted_prog) == f.read().rstrip('\n')

def test_simple_loop():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'Z90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'declare', 'var': 'loopind', 'dtype': 'int', 'scope': ['Q0']},
               {'name': 'loop', 'cond_lhs': 10, 'cond_rhs': 'loopind', 'alu_cond': 'ge', 
                'scope': ['Q0'], 'body':[
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'X90', 'qubit': ['Q0']}]},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'block', 'body': [
                    {'name': 'X90', 'qubit': ['Q1']}
                    ]}]

    fpga_config = hw.FPGAConfig(**fpga_config)

    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()

    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_simple_loop')

def test_simple_loop_scoped():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'block', 'body': [
                    {'name': 'X90', 'qubit': ['Q1']}
                    ]},
               {'name': 'Z90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'declare', 'var': 'loopind', 'dtype': 'int', 'scope': ['Q0']},
               {'name': 'loop', 'cond_lhs': 10, 'cond_rhs': 'loopind', 'alu_cond': 'ge', 
                'scope': ['Q0'], 'body':[
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'X90', 'qubit': ['Q0']}]},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'block', 'body': [
                    {'name': 'X90', 'qubit': ['Q1']}
                    ]}]

    fpga_config = hw.FPGAConfig(**fpga_config)

    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()

    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_simple_loop_scoped')

def test_compound_loop():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_load_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'declare', 'var': 'loopind', 'dtype': 'int', 'scope': ['Q0']},
               {'name': 'loop', 'cond_lhs': 10, 'cond_rhs': 'loopind', 'alu_cond': 'ge', 
                'scope': ['Q0', 'Q1'], 'body':[
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'X90', 'qubit': ['Q0']}]},
               {'name': 'CR', 'qubit': ['Q1', 'Q0']},
               {'name': 'X90', 'qubit': ['Q1']}]

    fpga_config = hw.FPGAConfig(**fpga_config)

    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()

    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_compound_loop')

def test_nested_loop():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_load_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'declare', 'var': 'loopind', 'dtype': 'int', 'scope': ['Q0']},
               {'name': 'declare', 'var': 'loopind2', 'dtype': 'int', 'scope': ['Q0']},
               {'name': 'loop', 'cond_lhs': 10, 'cond_rhs': 'loopind', 'alu_cond': 'ge', 
                'scope': ['Q0', 'Q1'], 'body':[
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'X90', 'qubit': ['Q0']},
                    {'name': 'loop', 'cond_lhs': 10, 'cond_rhs': 'loopind2', 'alu_cond': 'ge',
                     'scope': ['Q0', 'Q1'], 'body':[
                         {'name': 'X90', 'qubit': ['Q1']},
                         {'name': 'read', 'qubit': ['Q0']}]}]},
               {'name': 'CR', 'qubit': ['Q1', 'Q0']},
               {'name': 'X90', 'qubit': ['Q1']}]

    fpga_config = hw.FPGAConfig(**fpga_config)

    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    prog = compiler.compile()

    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_nested_loop')

    return prog

def test_scoper_procgroup_gen():
    scoper = ir.CoreScoper(('Q0.rdrv', 'Q0.rdlo', 'Q0.qdrv', 'Q1.rdrv', 'Q1.qdrv', 'Q1.rdlo'))
    grouping = {dest: ('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo') for dest in ('Q0.rdrv', 'Q0.rdlo', 'Q0.qdrv')}
    grouping.update({dest: ('Q1.qdrv', 'Q1.rdrv', 'Q1.rdlo') for dest in ('Q1.rdrv', 'Q1.rdlo', 'Q1.qdrv')})
    assert json.dumps(scoper.proc_groupings, sort_keys=True) == json.dumps(grouping, sort_keys=True)

def test_scoper_procgroup_gen_bychan():
    scoper = ir.CoreScoper(('Q0.rdrv', 'Q0.rdlo', 'Q0.qdrv', 'Q1.rdrv', 'Q1.qdrv', 'Q1.rdlo'), 
                        proc_grouping=[('{qubit}.qdrv',), ('{qubit}.rdrv', '{qubit}.rdlo')])
    grouping = {dest: ('Q0.rdrv', 'Q0.rdlo') for dest in ('Q0.rdrv', 'Q0.rdlo')}
    grouping.update({'Q0.qdrv': ('Q0.qdrv',)})
    grouping.update({dest: ('Q1.rdrv', 'Q1.rdlo') for dest in ('Q1.rdrv', 'Q1.rdlo')})
    grouping.update({'Q1.qdrv': ('Q1.qdrv',)})
    #print(scoper.proc_groupings)
    assert json.dumps(scoper.proc_groupings, sort_keys=True) == json.dumps(grouping, sort_keys=True)

def test_hw_virtualz():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'declare', 'var': 'q0_phase', 'scope': ['Q0'], 'dtype': 'phase'},
               {'name': 'bind_phase', 'var': 'q0_phase', 'freq': 'Q0.freq'},#'qubit': 'Q0'},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'virtual_z', 'qubit': 'Q0', 'phase': np.pi/2},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip))
    for statement in compiler.ir_prog.blocks['block_0']['instructions']:
        print(statement)
    prog = compiler.compile()

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    print()
    for coreprog in prog.program.values():
        for statement in coreprog:
            print(statement)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    compare_output(prog.serialize(), 'test_hw_virtualz')

def test_user_schedule():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 5},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100, dtype=np.float32), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.rdrv', 'start_time': 8},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 11},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 1234234, 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q1.qdrv', 'start_time': 5}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(schedule=False))
    compiler.run_ir_passes(passes)
    prog = compiler.compile()
    print(prog.program)
    return prog

def test_user_wrong_schedule():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 5},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100, dtype=np.float32), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.rdrv', 'start_time': 6},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 11},
               {'name': 'pulse', 'phase': 'np.pi/2', 'freq': 1234234, 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q1.qdrv', 'start_time': 5}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(schedule=False))
    with pytest.raises(Exception):
        compiler.run_ir_passes(passes)
    prog = compiler.compile()
    print(prog.program)
    return prog

def test_serialize_multrst():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()

    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q0']}], 'scope':['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q1']}], 'scope':['Q1']},
               {'name': 'X90', 'qubit': ['Q1']}]
    passes = cm.get_passes(fpga_config, qchip)
    passes.append(ps.LintSchedule(fpga_config, proc_grouping=[('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]))

    # reserialzie at every pass
    for irpass in passes:
        compiler = cm.Compiler(program)
        compiler.run_ir_passes([irpass])
        program = compiler.ir_prog.serialize()

    prog = compiler.compile()
    #print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_multirst_fproc_res_cfg')
    
    return compiler.ir_prog.serialize()

def test_freq_declaration():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()
    program = [{'name': 'declare_freq', 'freq': 5.e9, 'freqname': 'Q0.freq'},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 0},
               {'name': 'virtual_z', 'phase': np.pi/2, 'freq': 'Q0.freq'},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 'env': np.ones(100),
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 6},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q1.qdrv', 'start_time': 0}]

    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(schedule=False))
    compiler = cm.Compiler(program)
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(schedule=False))
    compiler.run_ir_passes(passes)
    prog = compiler.compile()


    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_freq_declare')

def test_freq_declaration_hw():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()
    program = [{'name': 'declare_freq', 'freq': 5.e9, 'freqname': 'Q0.freq0', 'freq_ind': 0, 'scope': {'Q0', 'Q1'}},
               {'name': 'declare_freq', 'freq': 5.2e9, 'freqname': 'Q0.freq1', 'freq_ind': 1, 'scope': {'Q0', 'Q1'}},
               {'name': 'declare', 'var': 'freqind'},
               {'name': 'set_var', 'var': 'freqind', 'value': 0},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'freqind', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv'},
               {'name': 'virtual_z', 'phase': np.pi/2, 'freq': 'Q0.freq'},
               {'name': 'alu', 'lhs': 1, 'op': 'add', 'rhs': 'freqind', 'out': 'freqind'},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'freqind', 'env': np.ones(100),
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q0.qdrv'},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'freqind', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q1.qdrv'},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 'env': np.ones(100), 
                'twidth': 24.e-9, 'amp':0.5, 'dest': 'Q1.qdrv'}]

    passes = cm.get_passes(fpga_config, qchip)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(passes)
    prog = compiler.compile()


    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_freq_declare_hw')

def test_normalize_end_t():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()

    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q0']}], 'scope':['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q1']}], 'scope':['Q1']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'read', 'qubit': ['Q0']}]
    passes = cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(multi_board=True))
    passes.append(ps.LintSchedule(fpga_config, proc_grouping=[('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]))

    compiler = cm.Compiler(program)
    compiler.run_ir_passes(passes)
    prog = compiler.compile()
    #print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_normalize_end_t')
    
    return compiler.ir_prog.serialize()

def test_fproc_hold_user_sched():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()

    program = [
                {'name': 'declare_freq', 'freqname':'Q0.freq', 'freq': 5.e9},
                {'name': 'declare_freq', 'freqname':'Q1.freq', 'freq': 5.5e9},

                {'name': 'block', 'scope': 'Q0', 'body':[
                    {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                     'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3,
                            "twidth": 3.2e-08
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 0},
                    {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                     'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3,
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 20},
                ]},

               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q1.freq', 
                 'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3,
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q1.qdrv', 'start_time': 0},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                'env': {
                   "env_func": "DRAG",
                   "paradict": {
                       "alpha": -0.2624037641352016,
                       "delta": -268000000.0,
                       "sigmas": 3,
                       }
                   }, "twidth": 1.e-06, 'amp':0.5, 'dest': 'Q0.rdlo', 'start_time': 0},

               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                'true': [],
                'false': [
                    {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                     'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 0},
                   ], 'scope':['Q0']},

               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [],
                'false': [
                    {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                     'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3,
                            "twidth": 4.2e-08
                            }
                        }, "twidth": 4.2e-08, 'amp':0.5, 'dest': 'Q1.qdrv', 'start_time': 0},
                    ], 'scope':['Q1']}, 

                {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                 'env': {
                    "env_func": "DRAG",
                    "paradict": {
                        "alpha": -0.2624037641352016,
                        "delta": -268000000.0,
                        "sigmas": 3
                        }
                    }, "twidth": 5.e-08, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 0},
        ]
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags={'schedule': False}))
    # ipdb.set_trace()
    prog = compiler.compile()
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_fproc_hold_user_sched')

def test_fproc_hold_delay():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = hw.FPGAConfig()


    program = [
                {'name': 'declare_freq', 'freqname':'Q0.freq', 'freq': 5.e9},
                {'name': 'declare_freq', 'freqname':'Q1.freq', 'freq': 5.5e9},

               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q1.freq', 
                 'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3,
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q1.qdrv', 'start_time': 0},
               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                'env': {
                   "env_func": "DRAG",
                   "paradict": {
                       "alpha": -0.2624037641352016,
                       "delta": -268000000.0,
                       "sigmas": 3,
                       }
                   }, "twidth": 1.e-06, 'amp':0.5, 'dest': 'Q0.rdlo', 'start_time': 0},

               {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                 'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3,
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 500},

               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                'true': [],
                'false': [
                    {'name': 'pulse', 'phase': np.pi/2, 'freq': 'Q0.freq', 
                     'env': {
                        "env_func": "DRAG",
                        "paradict": {
                            "alpha": -0.2624037641352016,
                            "delta": -268000000.0,
                            "sigmas": 3
                            }
                        }, "twidth": 3.2e-08, 'amp':0.5, 'dest': 'Q0.qdrv', 'start_time': 0},
                   ], 'scope': ['Q0']}

        ]
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags={'schedule': False}))
    # ipdb.set_trace()
    prog = compiler.compile()
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}

    channel_configs = hw.load_channel_configs('../test/channel_config.json')
    globalasm = am.GlobalAssembler(prog, channel_configs, elementconfigtest_factory)
    asm_prog = globalasm.get_assembled_program()

    compare_output(prog.serialize(), 'test_fproc_hold_delay')

def test_fproc_scoper():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 1,
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q0']}]},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 0,
                'true': [],
                'false': [{'name': 'X90', 'qubit': ['Q1']}]},
               {'name': 'X90', 'qubit': ['Q1']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(scope_control_flow=True)))
    # ipdb.set_trace()
    prog = compiler.compile()
    print(prog.program)
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(prog.serialize(), 'test_fproc_scoper')

def test_nested_fproc_scoper():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 1,
                'true': [
                    {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 0,
                     'true': [],
                     'false': [{'name': 'X90', 'qubit': ['Q1']}]},
                         ],
                'false': [
                    {'name': 'X90', 'qubit': ['Q0']}
                    ]
                },
               {'name': 'X90', 'qubit': ['Q1']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes([cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(scope_control_flow=True))[0]])
    print(compiler.ir_prog.serialize())
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(compiler.ir_prog.serialize(), 'test_nested_fproc_scoper')

def test_nested_fproc_sched():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q1']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [
                    {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                     'true': [],
                     'false': [{'name': 'X90', 'qubit': ['Q1']}]},
                         ],
                'false': [
                    {'name': 'X90', 'qubit': ['Q0']}
                    ]
                },
               {'name': 'X90', 'qubit': ['Q1']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(scope_control_flow=True)))
    print(compiler.ir_prog.serialize())
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    compare_output(compiler.ir_prog.serialize(), 'test_nested_fproc_scoper_sched')

def test_derive_phasetracker():
    qchip = qc.QChip('qubitcfg.json')
    program = [{'name': 'derive_phase_tracker', 'freq': 'Q2.freq', 'components': [('Q0.freq', 1), ('Q1.freq', -2)]},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'virtualz', 'qubit': ['Q1'], 'phase': np.pi},
               {'name': 'X90', 'qubit': ['Q2']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'X90', 'qubit': ['Q0']},
               ]
    fpga_config = hw.FPGAConfig()
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(scope_control_flow=True)))
    print(compiler.ir_prog.serialize())
    compare_output(compiler.ir_prog.serialize(), 'test_derive_phasetracker')

def test_distribute_phase():
    qchip = qc.QChip('qubitcfg.json')
    program = [{'name': 'derive_phase_tracker', 'freq': 'Q2.freq', 'components': [('Q0.freq', 1), ('Q1.freq', -2)]},
               {'name': 'X90', 'qubit': ['Q0']},
               {'name': 'virtualz', 'qubit': ['Q1'], 'phase': 2},
               {'name': 'virtualz', 'qubit': ['Q2'], 'phase': 1},
               {'name': 'X90', 'qubit': ['Q2']},
               {'name': 'X90', 'qubit': ['Q1']},
               {'name': 'X90', 'qubit': ['Q0']},
               ]
    fpga_config = hw.FPGAConfig()
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(scope_control_flow=True)))
    print(compiler.ir_prog.serialize())
    compare_output(compiler.ir_prog.serialize(), 'test_distribute_phase')

def test_nested_fproc_halt():
    qchip = qc.QChip('qubitcfg.json')
    fpga_config = {'alu_instr_clks': 2,
                   'fpga_clk_period': 2.e-9,
                   'jump_cond_clks': 3,
                   'jump_fproc_clks': 4,
                   'pulse_regwrite_clks': 1}
    program = [{'name': 'X90', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q0']},
               {'name': 'read', 'qubit': ['Q1']},
               {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q1.meas',
                'true': [
                    {'name': 'branch_fproc', 'alu_cond': 'eq', 'cond_lhs': 1, 'func_id': 'Q0.meas',
                     'true': [
                         {'name': 'halt', 'scope': ['Q0', 'Q1']}],
                     'false': [{'name': 'X90', 'qubit': ['Q1']}]},
                         ],
                'false': [
                    {'name': 'X90', 'qubit': ['Q0']}
                    ]
                },
               {'name': 'X90', 'qubit': ['Q1']}]
    fpga_config = hw.FPGAConfig(**fpga_config)
    compiler = cm.Compiler(program)
    compiler.run_ir_passes(cm.get_passes(fpga_config, qchip, compiler_flags=cm.CompilerFlags(scope_control_flow=True)))
    print(compiler.ir_prog.serialize())
    #sorted_program = {key: prog.program[key] for key in sorted(prog.program.keys())}
    # with open('test_outputs/test_nested_fproc_scoper_sched.txt', 'r') as f:
    #     filein = f.read().rstrip('\n')

    # try:
    #     assert compiler.ir_prog.serialize() == filein

    # except AssertionError as err:
    #     with open('test_outputs/test_nested_fproc_scoper_sched_err.txt', 'w') as ferr:
    #         ferr.write(compiler.ir_prog.serialize())

    #     raise err

def test_proc_group_gen():
    channel_configs = hw.load_channel_configs('channel_config.json')
    grouping = cm.proc_grouping_from_channelconfig(channel_configs)
    assert grouping[0] == ('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo')
    assert grouping[1] == ('Q1.qdrv', 'Q1.rdrv', 'Q1.rdlo')

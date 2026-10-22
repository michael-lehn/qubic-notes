import pytest
import numpy as np
import ipdb
import distproc.assembler as asm 
import distproc.compiler as cm
import distproc.hwconfig as hw
import qubitconfig.qchip as qc
import qubitconfig.wiremap as wm

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

#def test_prog_fromlist():
#    chancfgs = hw.load_channel_configs('channel_config.json')
#    asmlist = asm.SingleCoreAssembler(
#            {'Q0.qdrv': chancfgs['Q0.qdrv'], 'Q0.rdrv': chancfgs['Q0.rdrv'], 'Q0.rdlo': chancfgs['Q0.rdlo']},
#            {'Q0.qdrv': ElementConfig(), 'Q0.rdrv': ElementConfig(), 'Q0.rdlo': ElementConfig()})
#    prog = []
#    prog.append({'op':'phase_reset'})
#    prog.append({'op':'reg_write', 'value':np.pi, 'name':'phase', 'dtype': 'phase'})
#    prog.append({'op': 'pulse', 'freq': 100e6, 'env': np.arange(10)/11., 'phase': 'phase', \
#            'amp': 0.9, 'start_time': 15, 'dest': 'Q0.qdrv', 'label': 'pulse0'})
#    prog.append({'op':'done_stb'})
#
#    asmlist.from_list(prog)
#    cmdfl, envfl, freqfl = asmlist.get_compiled_program()
#
#    asmprog = asm.SingleCoreAssembler(
#            {'Q0.qdrv': chancfgs['Q0.qdrv'], 'Q0.rdrv': chancfgs['Q0.rdrv'], 'Q0.rdlo': chancfgs['Q0.rdlo']},
#            {'Q0.qdrv': ElementConfig(), 'Q0.rdrv': ElementConfig(), 'Q0.rdlo': ElementConfig()})
#    asmprog.add_phase_reset()
#    asmprog.add_reg_write('phase', np.pi, 'phase')
#    asmprog.add_pulse(100e6, 'phase', 0.9, 15, np.arange(10)/11., 'Q0.qdrv', label='pulse0')
#    asmprog.add_done_stb()
#    cmdpr, envpr, freqpr = asmprog.get_compiled_program()
#
#    assert np.all(np.asarray(cmdpr) == np.asarray(cmdfl))
#    assert np.all(np.asarray(envpr[0]) == np.asarray(envfl[0]))
#    assert np.all(np.asarray(freqpr) == np.asarray(freqfl))

def test_compiled_prog():
    prog = []
    prog.append({'op':'phase_reset'})
    prog.append({'op':'reg_write', 'value':np.pi, 'name':'phase', 'dtype': 'phase'})
    prog.append({'op': 'pulse', 'freq': 100e6, 'env': np.arange(10)/11., 'phase': 'phase', \
            'amp': 0.9, 'start_time': 15, 'dest': 'Q0.qdrv', 'label': 'pulse0'})
    prog.append({'op':'done_stb'})

    progdict = {('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'): prog}

    program = cm.CompiledProgram(progdict)
    globalasm = asm.GlobalAssembler(program, hw.load_channel_configs('channel_config.json'), elementconfigtest_factory)
    rawasm = globalasm.get_assembled_program()



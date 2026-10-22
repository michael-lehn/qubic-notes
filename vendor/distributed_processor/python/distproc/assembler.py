"""Distributed processor assembly language definition:
    list of dicts; should map 1-to-1 to assembled commands that run on proc

    declaring registers:
        {'op': 'declare_reg', 'name': <str>, 'dtype': <('int',), ('phase', elemind), ('amp', elemind)>} 

        All registers are typed (to allow for straightforward parameterization of phase/amplitude). If a type is 
        not specified when declaring the register the default type is ('int',). 

    declaring frequencies:
        {'op': 'declare_freq', 'freq': <freq_in_Hz>, 'elem_ind': <element_index>, 'freq_ind': <optional_ind_in_buffer>}
        TODO: consider vectorizing this

    pulse cmd:
        {'op': 'pulse', 'freq': <freq_in_Hz, regname>, 'env': <np_array, dict, regname>, 'phase': <phaserad, regname>,
            'amp': <float (normalized to 1), regname>, 'start_time': <starttime_in_clks>, 'dest': <destname>, 'label':<string>} 
        Note: if feeding program dict to SingleUnitAssembler (as opposed to generating a CompiledProgram object and compiling 
        using GlobalAssembler) 'dest' is 'elem_ind' and corresponds to the elem_ind of dest in the ChannelConfig object.

        ways to specify the envelope:
            1. numpy array of samples, normalized to 1
            2. dictionary specifying envelope function + parameters; the format of this dictionary should be specified in 
               ElementConfig.get_env_buffer
            3. register name (parameterizes the env_word field of the pulse command, no real higher level support here)

    register-based instructions:
        reg_alu:
            {'op': 'reg_alu', 'in0': <int, regname>, 'alu_op': alu_opcode_str, 'in1_reg': regname, 'out_reg': out_regname, 'label':<string>}
        inc_qclk:
            {'op': 'inc_qclk', 'in0': <int, regname>, 'label': <string>}
        jump_cond:
            {'op': 'jump_cond', 'in0': <int, regname>, 'alu_op': alu_opcode_str, 'in1_reg': regname, 'jump_label': <string>, 'label':<string>}
        jump_fproc:
            {'op': 'jump_fproc', 'in0': <int, regname>, 'alu_op': alu_op, 'jump_label': jump_label, 'func_id': func_id}
        alu_fproc:
            {'op': 'alu_fproc', 'in0': <int, regname>, 'alu_op': alu_op, 'out_reg': out_regname, 'func_id': func_id, 'label':<string>}
        reg_write:
            {'op': 'reg_write', 'value': <int>, 'name': out_regname, 'dtype': <('int',), ('phase', elemind), ('amp', elemind)>, 'label':<string>} 
            note: this is just a helper/wrapper for a reg_alu instruction

    other:
        {'op': 'phase_reset'}
        {'op': 'done_stb'}

        {'op': 'jump_label', 'dest_label': <labelname>}

"""

import distproc.command_gen as cg
import copy
import numpy as np
from typing import Dict, List, Tuple
import distproc.hwconfig as hw
from distproc.executable import Executable
from collections import OrderedDict
import warnings
import json

ENV_BITS = 16
N_MAX_REGS = 16



class SingleCoreAssembler:
    """
    Class for constructing an assembly-language level program and 
    converting to machine code + env buffers. Program can be constructed
    dynamically using the provided functions or specified/read from text file
    as a list of dictionaries (format at the beginning of this file)
    
    TODO: Consider replacing add_reg_write, etc with alu_cmd instruction
    similar to command_gen

    Attributes
    ----------
        _regs : dict
            key: user-declared register name
            value: dictionary containing:
                'index' : physical register address
                'dtype' : register datatype. Allowed types are:
                    ('int',)
                    ('phase', elemind)
                    ('amp', elemind)
    """

    def __init__(self, chan_cfgs: Dict, elem_cfgs: Dict):
        self.n_element = len(elem_cfgs)
        # self._env_dicts = {chan: OrderedDict() for chan in chan_cfgs.keys()}  
        # self._freq_lists = {chan: [] for chan in chan_cfgs.keys()}
        self._program = []
        self._regs = {}
        self._elem_cfgs = elem_cfgs
        self._chan_cfgs = chan_cfgs

        core_ind_set = {self._chan_cfgs[chan].core_ind for chan in self._chan_cfgs.keys()}
        if len(core_ind_set) != 1:
            raise Exception(f'Program spans multiple cores: {core_ind_set}!')
        self.core_ind = core_ind_set.pop()

        core_name_set = {self._chan_cfgs[chan].core_name for chan in self._chan_cfgs.keys()}
        if len(core_name_set) != 1:
            raise Exception(f'Program spans multiple cores: {core_name_set}!')
        self.core_name = core_name_set.pop()

        board_name_set = {self._chan_cfgs[chan].board_name for chan in self._chan_cfgs.keys()}
        if len(board_name_set) != 1:
            raise Exception(f'Program spans multiple boards: {board_name_set}!')
        self.board_name = board_name_set.pop()

    def from_list(self, cmd_list):
        for i, cmd in enumerate(cmd_list):
            cmdargs = cmd.copy()
            del cmdargs['op']
            if cmd['op'] == 'pulse':
                nreg_params = np.sum([isinstance(cmd[key], str) for key in ['freq', 'amp', 'phase']])
                if nreg_params > 1:
                    warnings.warn(
                        '{} will be split into multiple instructions, which may cause timing problems'.format(cmd))
                self.add_pulse(**cmdargs)
            elif cmd['op'] in ['reg_alu', 'jump_cond', 'alu_fproc', 'jump_fproc']:
                self.add_alu_cmd(**cmd)
            elif cmd['op'] == 'reg_write':
                self.add_reg_write(**cmdargs)
            elif cmd['op'] == 'phase_reset':
                self.add_phase_reset(**cmdargs)
            elif cmd['op'] == 'done_stb':
                self.add_done_stb(**cmdargs)
            elif cmd['op'] == 'declare_freq':
                self.add_freq(**cmdargs)
            elif cmd['op'] == 'declare_reg':
                self.declare_reg(**cmdargs)
            elif cmd['op'] == 'inc_qclk':
                self.add_inc_qclk(**cmdargs)
            elif cmd['op'] == 'idle':
                self.add_idle(**cmdargs)
            elif cmd['op'] == 'jump_label':
                cmd_list[i + 1]['label'] = cmdargs['dest_label']
            elif cmd['op'] == 'jump_i':
                self.add_jump_i(**cmdargs)
            else:
                raise Exception('{} not supported!'.format(cmd))

    def add_jump_i(self, jump_label, label=None):
        cmd = {'op': 'jump_i', 'jump_label': jump_label}
        if label is not None:
            cmd['label'] = label
        self._program.append(cmd)


    def add_idle(self, end_time, label=None):
        cmd = {'op': 'idle', 'end_time': end_time}
        if label is not None:
            cmd['label'] = label
        self._program.append(cmd)

    def add_alu_cmd(self, op: str, in0: int | str, alu_op: str, in1_reg: str = None,
                    out_reg: str = None, jump_label: str = None, func_id: int | tuple | str = None, label: str = None):
        assert op in ['reg_alu', 'jump_cond', 'alu_fproc', 'jump_fproc', 'inc_qclk']
        if in1_reg is not None:
            assert in1_reg in self._regs.keys()
        if isinstance(in0, str):
            assert in0 in self._regs.keys()

        cmd = {'op': op, 'in0': in0, 'alu_op': alu_op}

        if op in ['reg_alu', 'jump_cond']:
            assert in1_reg is not None
            assert func_id is None
            if isinstance(in0, str):
                assert self._regs[in0]['dtype'] == self._regs[in1_reg]['dtype']
            cmd['in1_reg'] = in1_reg
        else:
            assert in1_reg is None

        if op in ['reg_alu', 'alu_fproc']:
            assert out_reg is not None
            if isinstance(in0, str):
                assert self._regs[in0]['dtype'] == self._regs[out_reg]['dtype']
            if in1_reg is not None:
                assert self._regs[in1_reg]['dtype'] == self._regs[out_reg]['dtype']
            cmd['out_reg'] = out_reg
        else:
            assert out_reg is None

        if op in ['jump_cond', 'jump_fproc']:
            assert jump_label is not None
            cmd['jump_label'] = jump_label

        if op in ['alu_fproc', 'jump_fproc']:  # None defaults to 0, implies func_id not used
            cmd['func_id'] = func_id
        else:
            assert func_id is None

        if label is not None:
            cmd['label'] = label

        self._program.append(cmd)

    def add_freq(self, freq, channel, freq_ind=None):
        self._elem_cfgs[channel].add_freq(freq, freq_ind)

    def declare_reg(self, name, dtype='int'):
        """
        Declare a named register that can be referenced
        by subsequent commands
        """
        if not self._regs:
            self._regs[name] = {'index': 0, 'dtype': dtype}
        elif name in self._regs.keys():
            if dtype != self._regs[name]['dtype']:
                raise Exception(f'Duplicate declarations of {name} with different dtype: {dtype}')
        else:
            max_regind = max([reg['index'] for reg in self._regs.values()])
            if max_regind >= N_MAX_REGS - 1:
                raise Exception('cannot add any more regs, limit of {} reached'.format(N_MAX_REGS))
            self._regs[name] = {'index': max_regind + 1, 'dtype': dtype}

    def add_reg_write(self, name, value, dtype=None, label=None):
        """
        Write 'value' to a named register name. CAN be declared implicitly.
        """
        if name not in self._regs.keys():
            if dtype is None:
                dtype = 'int'
            self.declare_reg(name, dtype)
        elif dtype is not None:
            assert dtype == self._regs[name]['dtype']
        self.add_reg_alu(value, 'id0', name, name, label)

    def add_reg_alu(self, in0, alu_op, in1_reg, out_reg, label=None):
        """
        Add a command for an ALU operation on registers.

        Parameters
        ----------
            in0 : int or str
                First input to ALU. If int, assumed to be intermediate value.
                If string, assumed to be named register
            alu_op : str
                'add', 'sub', 'id0', 'id1', 'eq', 'le', 'ge', 'zero'
            in1_reg : str
                Second input to ALU. Named register
            out_reg : str
                Reg that gets written w/ ALU output. CAN be declared implicitly.
        """
        self.add_alu_cmd('reg_alu', in0, alu_op, in1_reg, out_reg, label=label)

    def add_phase_reset(self, label=None):
        cmd = {'op': 'pulse_reset'}
        if label is not None:
            cmd['label'] = label
        self._program.append(cmd)

    def add_done_stb(self, label=None):
        cmd = {'op': 'done_stb'}
        if label is not None:
            cmd['label'] = label
        self._program.append(cmd)

    def add_jump_cond(self, in0, alu_op, in1_reg, jump_label, label=None):
        self.add_alu_cmd('jump_cond', in0, alu_op, in1_reg,
                         jump_label=jump_label, label=label)

    def add_inc_qclk(self, in0, label=None):
        self.add_alu_cmd('inc_qclk', in0, 'add', label=label)

    def add_jump_fproc(self, in0, alu_op, jump_label, func_id=None, label=None):
        self.add_alu_cmd('jump_fproc', in0, alu_op, jump_label=jump_label, func_id=func_id, label=label)

    def add_pulse(self, freq, phase, amp, start_time, env, dest, label=None, tag=None, save_result=None):
        """
        Add a pulse command to the program. 'freq' and 'phase' can be specified by 
        named registers or immediate values.

        Parameters
        ----------
            freq : float, int, str
                If numerical, pulse frequency in Hz; if string, named register
                to use. Register must be declared beforehand.
            phase : float, str
                If numerical, pulse phase in radians; if string, named register
                to use. Register must be declared beforehand.
            env : np.ndarray, str
                Either an array of envelope samples, or a string specifying 
                named envelope to use. Envelope array is hashed to see if it's 
                already been added. Note: doesn't work with user added named envelopes
            length : int
                pulse length in samples. If None, use len(env)
            label : str
                label for this program instruction. Useful (required) for jumps.
        """
        envkey = self._elem_cfgs[dest].add_env(env)

        if isinstance(freq, str):
            assert freq in self._regs.keys()
            assert self._regs[freq]['dtype'] == 'int'
        else:
            self.add_freq(freq, dest)

        if isinstance(amp, str):
            assert amp in self._regs.keys()
            assert self._regs[amp]['dtype'] == 'amp'

        if isinstance(phase, str):
            assert phase in self._regs.keys()
            assert self._regs[phase]['dtype'] == 'phase'

        if isinstance(freq, str) and isinstance(phase, str) and isinstance(amp, str):
            # can only do one pulse_reg write at a time so use two instructions
            self._program.append({'op': 'pulse', 'freq': freq, 'dest': dest, 'label': label})
            self._program.append({'op': 'pulse', 'amp': amp, 'dest': dest})
            cmd = {'op': 'pulse', 'phase': phase, 'start_time': start_time,
                   'env': envkey, 'dest': dest}
        elif (isinstance(freq, str) and ((isinstance(phase, str)) or isinstance(amp, str))):
            self._program.append({'op': 'pulse', 'freq': freq, 'dest': dest, 'label': label})
            cmd = {'op': 'pulse', 'phase': phase, 'amp': amp, 'start_time': start_time,
                   'env': envkey, 'dest': dest}
        elif isinstance(phase, str) and isinstance(amp, str):
            self._program.append({'op': 'pulse', 'phase': phase, 'dest': dest, 'label': label})
            cmd = {'op': 'pulse', 'freq': freq, 'amp': amp, 'start_time': start_time,
                   'env': envkey, 'dest': dest}
        else:
            cmd = {'op': 'pulse', 'freq': freq, 'phase': phase, 'amp': amp,
                   'start_time': start_time, 'env': envkey, 'dest': dest, 'label': label}

        if save_result is not None:
            cmd['save_result'] = save_result

        self._program.append(cmd)

    def _get_env_buffers(self):
        env_buffers = {}
        env_word_maps = {}
        for channame, elem_cfg in self._elem_cfgs.items():
            env_buffer, env_word_maps[channame] = elem_cfg.compile_envs()
            if env_buffer is not None:
                env_buffers[channame] = env_buffer

        return env_buffers, env_word_maps

    def _get_freq_buffers(self):
        freq_buffers = {}
        freq_word_maps = {}
        for channame, elem_cfg in self._elem_cfgs.items():
            freq_buffer, freq_word_maps[channame] = elem_cfg.compile_freqs()
            if freq_buffer is not None:
                freq_buffers[channame] = freq_buffer

        return freq_buffers, freq_word_maps

    def get_program_binaries(self):
        # consider splitting this into a few different functions
        # at top case level
        cmd_buf = bytes()
        freq_list = []
        env_buffers, env_word_map = self._get_env_buffers()
        cmd_label_addrmap = self._get_cmd_labelmap()
        freq_buffers, freq_ind_map = self._get_freq_buffers()
        for cmd in self._program:
            cmd = copy.deepcopy(cmd)  # we are modifying cmd so don't overwrite anything in self._program

            if cmd['op'] == 'pulse':
                pulseargs = {}

                if 'freq' in cmd.keys():
                    if isinstance(cmd['freq'], str):
                        pulseargs['freq_regaddr'] = self._regs[cmd['freq']]['index']
                    else:
                        pulseargs['freq_word'] = freq_ind_map[cmd['dest']][cmd['freq']]

                if 'phase' in cmd.keys():
                    if isinstance(cmd['phase'], str):
                        pulseargs['phase_regaddr'] = self._regs[cmd['phase']]['index']
                    else:
                        pulseargs['phase_word'] = cg.get_phase_word(cmd['phase'])

                if 'amp' in cmd.keys():
                    if isinstance(cmd['amp'], str):
                        pulseargs['amp_regaddr'] = self._regs[cmd['amp']]['index']
                    else:
                        pulseargs['amp_word'] = cg.get_amp_word(cmd['amp'])

                if 'env' in cmd.keys():
                    pulseargs['env_word'] = env_word_map[cmd['dest']][cmd['env']]

                if 'start_time' in cmd.keys():
                    pulseargs['cmd_time'] = cmd['start_time']

                if 'dest' in cmd.keys():
                    pulseargs['cfg_word'] = self._elem_cfgs[cmd['dest']].get_cfg_word(
                            self._chan_cfgs[cmd['dest']].elem_ind, cmd.get('save_result'))

                cmd_buf += cg.pulse_cmd(**pulseargs).to_bytes(16, 'little')

            elif cmd['op'] in ['reg_alu', 'jump_cond', 'alu_fproc', 'jump_fproc', 'inc_qclk']:
                if isinstance(cmd['in0'], str):
                    in0 = self._regs[cmd['in0']]['index']
                    im_or_reg = 'r'
                else:
                    in0 = cmd['in0']
                    im_or_reg = 'i'

                    # if we're writing to/interacting with typed register, typecast intermediate value accordingly
                    if 'out_reg' in cmd.keys() or 'in1_reg' in cmd.keys():
                        dtype = self._regs[cmd['out_reg']]['dtype'] if 'out_reg' in cmd.keys() else \
                        self._regs[cmd['in1_reg']]['dtype']
                        if dtype == 'phase':
                            in0 = cg.get_phase_word(cmd['in0'])
                        elif dtype == 'amp':
                            in0 = cg.get_amp_word(cmd['in0'])
                        elif dtype != 'int':
                            raise Exception(f'invalid register type {dtype}')

                if 'out_reg' in cmd.keys():
                    cmd['out_reg'] = self._regs[cmd['out_reg']]['index']

                if 'jump_label' in cmd.keys():
                    cmd['jump_addr'] = cmd_label_addrmap[cmd['jump_label']]

                if 'in1_reg' in cmd.keys():
                    cmd['in1_reg'] = self._regs[cmd['in1_reg']]['index']

                cmd_raw = cg.alu_cmd(cmd['op'], im_or_reg, in0, cmd.get('alu_op'),
                                     cmd.get('in1_reg'), cmd.get('out_reg'), cmd.get('jump_addr'), cmd.get('func_id'))
                cmd_buf += cmd_raw.to_bytes(16, 'little')

            elif cmd['op'] == 'jump_i':
                cmd['jump_addr'] = cmd_label_addrmap[cmd['jump_label']]
                cmd_buf += cg.jump_i(cmd['jump_addr']).to_bytes(16, 'little')

            elif cmd['op'] == 'pulse_reset':
                cmd_buf += cg.pulse_reset().to_bytes(16, 'little')

            elif cmd['op'] == 'idle':
                cmd_buf += cg.idle(cmd['end_time']).to_bytes(16, 'little')

            elif cmd['op'] == 'done_stb':
                cmd_buf += cg.done_cmd().to_bytes(16, 'little')

            else:
                raise Exception('{} not supported'.format(cmd['op']))

        exe = Executable()
        exe += self._register_acc_chans()

        for channame, env_buf in env_buffers.items():
            exe.add_mem_buffer(self._chan_cfgs[channame].env_mem_name,
                               self._chan_cfgs[channame].board_name, env_buf)
        for channame, freq_buf in freq_buffers.items():
            exe.add_mem_buffer(self._chan_cfgs[channame].freq_mem_name,
                               self._chan_cfgs[channame].board_name, freq_buf)
 
        if self.core_name == '' or self.core_name is None:
            instr_mem_name = f'command{self.core_ind}' 

        else:
            instr_mem_name = f'{self.core_name}_command{self.core_ind}'

        exe.add_mem_buffer(instr_mem_name, self.board_name, cmd_buf)

        return exe
    
    def _register_acc_chans(self):
        exe = Executable()
        for channame, chancfg in self._chan_cfgs.items():
            if chancfg.acc_mem_name is not None:
                exe.add_result_chan(channame, chancfg.acc_mem_name, chancfg.board_name)

        return exe


    def get_sim_program(self):
        """
        Get a pulse/command list usable by simulation tools. Currently, this is the same as
        self._program, but with env names replaced by data
        """
        cmd_list = []
        for cmd in self._program:
            cmd = copy.deepcopy(cmd)
            if cmd['op'] == 'pulse':
                cmd.update({'env': self._elem_cfgs[cmd['dest']]._env_dict[cmd['env']]})
            cmd_list.append(cmd)

        return cmd_list

    def _get_cmd_labelmap(self):
        """
        Get command locations (addresses) for labeled commands.
        Used for jump instructions
        """
        labelmap = {}
        for i, cmd in enumerate(self._program):
            if 'label' in cmd.keys() and cmd['label'] is not None:
                if cmd['label'] in labelmap.keys():
                    raise Exception('label already in use!')
                labelmap[cmd['label']] = i
        return labelmap

class GlobalAssembler:
    """
    Takes a CompiledProgram object and convert to np arrays to be written to FPGA BRAM.
    """

    def __init__(self, compiled_program, channel_configs, elementconfig_factory):
        """
        channel configs is loaded from json file, using hwconfig.load_channel_configs
        """
        self.assemblers = []
        self.channel_configs = channel_configs
        compiled_program = copy.deepcopy(compiled_program)

        if compiled_program.fpga_config is not None \
                and int(np.round(channel_configs['fpga_clk_freq'])) != int(
            np.round(compiled_program.fpga_config.fpga_clk_freq)):
            raise Exception('Program target clock {} Hz does not match HW clock \
                    {}'.format(compiled_program.fpga_config.fpga_clk_freq, channel_configs['fpga_clk_freq']))

        for proc_group in compiled_program.proc_groups:
            elem_cfgs = {}
            chan_cfgs = {}
            for chan in proc_group:
                chan_cfg = channel_configs[chan]
                chan_cfgs[chan] = chan_cfg
                elementconfig_class = elementconfig_factory(chan_cfg.elem_type)
                elem_cfgs[chan] = elementconfig_class(**chan_cfg.elem_params)

            self.assemblers.append(SingleCoreAssembler(chan_cfgs, elem_cfgs))
            self._resolve_fproc_chans(compiled_program.program[proc_group])
            self._resolve_duplicate_jump_labels(compiled_program.program[proc_group])
            self.assemblers[-1].from_list(compiled_program.program[proc_group])

    def _resolve_fproc_chans(self, single_core_program):
        """
        1) Replace the 'dest' key in pulse commands with 'elem_ind' according to self.channel_configs
        2) Resolve FPROC func_ids according to the following:
            if int, do nothing
            if tuple, resolve using hw.ChannelConfig object; first index is the key of the object 
            in the channel_configs dict, second element is the attribute:
                e.g. ('Q0.rdlo', 'core_ind') resolves to channel_configs['Q0.rdlo'].core_ind
            if string, resolve directly using the channel_configs dict
        """
        for statement in single_core_program:
            if statement['op'] == 'alu_fproc' or statement['op'] == 'jump_fproc':
                if isinstance(statement['func_id'], tuple):
                    config_obj = self.channel_configs[statement['func_id'][0]]
                    statement['func_id'] = getattr(config_obj, statement['func_id'][1])
                elif isinstance(statement['func_id'], str):
                    statement['func_id'] = self.channel_configs[statement['func_id']]
                else:
                    assert isinstance(statement['func_id'], int)

    def _resolve_duplicate_jump_labels(self, single_core_program):
        combined_jumps = {}
        cur_jumplabel = None

        i = 0
        while i < len(single_core_program) - 1:
            #if single_core_program[i]['op'] == 'jump_label' and single_core_program[i + 1]['op'] == 'jump_label':
            #    combined_jumps[single_core_program[i]['dest_label']] = single_core_program[i + 1]['dest_label']
            #    single_core_program.pop(i)
            #    i -= 1
            if single_core_program[i]['op'] == 'jump_label':
                if cur_jumplabel is None:
                    cur_jumplabel = single_core_program[i]['dest_label']
                else:
                    combined_jumps[single_core_program[i]['dest_label']] = cur_jumplabel
                    single_core_program.pop(i)
                    i -= 1

            else:
                cur_jumplabel = None
            
            i += 1

        if combined_jumps != {}:
            for statement in single_core_program:
                if 'jump_label' in statement.keys() and statement['jump_label'] in combined_jumps.keys():
                    statement['jump_label'] = combined_jumps[statement['jump_label']]

    def get_assembled_program(self):
        """
        Get assembled program to load onto FPGA.

        Returns
        -------
            assembled_prog : dict
                keys : proc core index
                values : dict
                    'cmd_list' : list of proc commands (128-bit wide)
                    'env_buffers' : list of env buffers (one per element assigned to core)
                    'freq_buffers' : list of freq buffers
        """
        assembled_prog = Executable()
        for asm in self.assemblers:
            assembled_prog += asm.get_program_binaries()

        return assembled_prog

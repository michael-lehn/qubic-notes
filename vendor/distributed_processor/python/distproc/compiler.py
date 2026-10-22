"""
High-level tools for controlling the compilation process. Most of the core
IR lowering is done using passes defined in distproc.ir, but this module contains
tools for defining and running compiler flows (Compiler and CompilerFlags), and 
performing the final conversion to distributed processor assembly (Compiler.compile()).
"""

import numpy as np
from collections import defaultdict
import copy
import logging 
import pandas as pd
from attrs import define
from typing import Dict, Tuple, List

try:
    import ipdb
except ImportError:
    logging.warning('failed to import ipdb')
import json
from collections import OrderedDict

import qubitconfig.qchip as qc
import distproc.assembler as asm
import distproc.hwconfig as hw
import distproc.ir.ir as ir
import distproc.ir.passes as passes

@define
class CompilerFlags:
    """
    Attributes
    ----------
    resolve_gates: bool
        Set to True if there are Gate instructions that need to be resolved
    schedule: bool
        If True, the Schedule pass is run, else the user is expected to provide a timestamp for all timed instructions
    multi_board: bool
        Set to True if program spans multiple FPGA boards

    """
    scope_control_flow: bool = False
    resolve_gates: bool = True
    schedule: bool = True
    multi_board: bool = False
    optimize_reg_ops: bool = False


def get_passes(fpga_config: hw.FPGAConfig, qchip: qc.QChip = None, 
               compiler_flags: CompilerFlags | dict = None,
               qubit_grouping: Tuple[str] | Dict[str, set] | ir.QubitScoper = ('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo'),
               proc_grouping: List[Tuple] = [('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]):
    """
    Return a list of IR passes to run, according to the provided configs, qubit/proc 
    core groupings, and compiler configuration flags.

    Parameters
    ----------
    fpga_config: hw.FPGAConfig
    qchip: qc.Qchip
    compiler_flags: CompilerFlags | dict
    qubit_grouping: Tuple[str]
        Tuple of channels corresponding to a given qubit; name of qubit must be provided 
        as format string inside channel name (see example)
    proc_grouping: List[Tuple]
        List of tuples grouping the channels into processor cores. Format strings can be used to 
        encode multiple groupings with the same format (e.g. the default will match any core with channels
        matching the expressions for an arbitrary value of `{qubit}`).

    Returns
    -------
    List[ir.Pass]
        List of ir.Pass objects
    """

    if compiler_flags is None:
        compiler_flags = CompilerFlags()
    elif isinstance(compiler_flags, dict):
        compiler_flags = CompilerFlags(**compiler_flags)

    if isinstance(qubit_grouping, Tuple) or isinstance(qubit_grouping, List):
        qubit_scoper = ir.QubitScoperFromTup(qubit_grouping)
    elif isinstance(qubit_grouping, Dict):
        qubit_scoper = ir.QubitScoperFromDict(qubit_grouping)
    else:
        qubit_scoper = qubit_grouping

    if compiler_flags.scope_control_flow:
        cur_passes = [passes.ScopeControlFlow(qubit_scoper)]

    else:
        cur_passes = []

    cur_passes.extend([passes.FlattenProgram(),
                       passes.MakeBasicBlocks()])

    cur_passes.extend([passes.ScopeProgram(qubit_scoper),
                       passes.RegisterVarsAndFreqs(qchip)])

    if compiler_flags.resolve_gates:
        if qchip is None:
            raise Exception('qchip object required for ResolveGates pass')
        cur_passes.append(passes.ResolveGates(qchip, qubit_scoper))

    cur_passes.extend([passes.GenerateCFG(),
                       passes.ResolveHWVirtualZ()])

    cur_passes.extend([passes.ResolveVirtualZ(),
                       passes.RescopeVars()])

    if compiler_flags.optimize_reg_ops:
        cur_passes.append(passes.OptimizeALU())

    cur_passes.extend([passes.ResolveFreqs(),
                       passes.ResolveFPROCChannels(fpga_config)])
    
    cur_passes.append(passes.Schedule(fpga_config, proc_grouping, compiler_flags.multi_board, compiler_flags.schedule))

    if not compiler_flags.schedule:
        cur_passes.append(passes.LintSchedule(fpga_config, proc_grouping))

    return cur_passes


class Compiler:
    """
    Class for compiling a quantum circuit encoded in the QubiC IR format. Broadly, compilation has 
    three stages:

      1. Load program into the Python IR format; i.e. a distproc.ir.IRProgram object
      2. Run a series of compiler passes on the IR. This is where the bulk of the compilation 
         happens, including:
           - gate resolution
           - virtualz phase resolution
           - scheduling
           - resolution of named frequencies
           - program block scoping
      3. Compile the program down to distributed processor assembly (CompiledProgram object).

    """

    def __init__(self, program, proc_grouping=[('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]):
        """
        Parameters
        ----------
        program: List | Dict | str 
            Program source. Can be any of the following forms:
                - List of instructions (dict or instruction classes from distproc.ir.instructions). 
                - Dictionary (with or without metadata). Must contain 'program' field, which can either 
                  be a list of instructions, or a dictionary of basic blocks (each containing a list of instructions).
                  Metadata is initialized as necessary.
                - JSON string. Decoded and resolved into one of the above forms.
        proc_grouping : List[Tuple[str]]
            list of tuples grouping channels to proc cores. Format keys
            (e.g. {qubit}) can be used to make general groupings.

        """
        self.ir_prog = ir.IRProgram(program)
        self._proc_grouping = proc_grouping

    def run_ir_passes(self, passes: list):
        """
        Run a list of IR passes on the program. get_default_passes()
        can be used to generate this list in most cases.

        Parameters
        ----------
            passes : list
                list of passes. Each element is an ir.Pass object.
        """
        for ir_pass in passes:
            ir_pass.run_pass(self.ir_prog)

    def compile(self):
        """
        Compiler the program from the intermediate representation down to pulse-level 
        assembly (i.e. a CompiledProgram object). This includes splitting up the program
        statements into constituent distributed processor cores according to the 
        proc_grouping provided at Compiler instantiation

        Returns
        -------
            CompiledProgram
        """
        self._core_scoper = ir.CoreScoper(self.ir_prog.scope, self._proc_grouping)
        asm_progs = {grp: [{'op': 'phase_reset'}] for grp in self._core_scoper.proc_groupings_flat}
        for blockname in self.ir_prog.blocknames_by_ind:
            self._compile_block(asm_progs, self.ir_prog.blocks[blockname]['instructions'])

        for proc_group in self._core_scoper.proc_groupings_flat:
            asm_progs[proc_group].append({'op': 'done_stb'})

        return CompiledProgram(asm_progs)

    def _compile_block(self, asm_progs, instructions):
        proc_groups_bydest = self._core_scoper.proc_groupings
        # TODO: add twidth attribute to env, not pulse
        for i, instr in enumerate(instructions):
            if instr.name == 'pulse':
                proc_group = proc_groups_bydest[instr.dest]

                if instr.env is None or isinstance(instr.env, dict):
                    env = instr.env
                elif isinstance(instr.env[0], dict):
                    env = instr.env[0]
                    if len(instr.env) > 1:
                        logging.getLogger(__name__).warning(f'Only first env paradict {env} is being used')
                else:
                    env = instr.env

                if isinstance(env, dict):
                    if 'twidth' not in env['paradict'].keys():
                        env = copy.deepcopy(env)
                        env['paradict']['twidth'] = instr.twidth
                    elif env['paradict']['twidth'] != instr.twidth:
                        raise Exception('Pulse twidth differs from envelope!')

                asm_instr = {'op': 'pulse', 'freq': instr.freq, 'phase': instr.phase, 'amp': instr.amp,
                             'env': env, 'start_time': instr.start_time, 'dest': instr.dest}

                if instr.tag is not None:
                    asm_instr['tag'] = instr.tag
                if instr.save_result is not None:
                    asm_instr['save_result'] = instr.save_result

                asm_progs[proc_group].append(asm_instr)

            elif instr.name == 'jump_label':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'jump_label', 'dest_label': instr.label})

            elif instr.name == 'declare':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'declare_reg', 'name': instr.var, 'dtype': instr.dtype})

            elif instr.name == 'declare_freq':
                if instr.freq_ind is not None:
                    if instr.scope is None:
                        raise Exception(f'Hardware-declared frequency: {instr.freqname} @ {instr.freq} Hz must be scoped!')
                    for core in self._core_scoper.get_groups_bydest(instr.scope):
                        for dest in sorted(instr.scope):
                            if dest in core:
                                asm_progs[core].append({'op': 'declare_freq', 'freq': instr.freq, 
                                                        'channel': dest, 'freq_ind': instr.freq_ind})

            elif instr.name == 'alu':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'reg_alu', 'in0': instr.lhs, 'in1_reg': instr.rhs, 
                                                      'alu_op': instr.op, 'out_reg': instr.out})

            elif instr.name == 'set_var':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'reg_alu', 'in0': instr.value, 'in1_reg': instr.var,
                                            'alu_op': 'id0', 'out_reg': instr.var})
            elif instr.name == 'read_fproc':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'alu_fproc', 'in0': 0, 'alu_op': 'id1', 
                             'func_id': instr.func_id, 'out_reg': instr.var})

            elif instr.name == 'alu_fproc':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'alu_fproc', 'in0': instr.lhs, 'alu_op': instr.op, 
                             'func_id': instr.func_id, 'out_reg': instr.out})

            elif instr.name == 'jump_fproc':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'jump_fproc', 'in0': instr.cond_lhs, 'alu_op': instr.alu_cond, 
                             'jump_label': instr.jump_label, 'func_id': instr.func_id})

            elif instr.name == 'jump_cond':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'jump_cond', 'in0': instr.cond_lhs, 'alu_op': instr.alu_cond, 
                             'jump_label': instr.jump_label, 'in1_reg': instr.cond_rhs})

            elif instr.name == 'jump_i':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'jump_i', 'jump_label': instr.jump_label})

            elif instr.name == 'loop_end':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'inc_qclk', 'in0': -self.ir_prog.loops[instr.loop_label].delta_t})

            elif instr.name == 'idle':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'idle', 'end_time': instr.end_time})

            elif instr.name == 'halt':
                for core in self._core_scoper.get_groups_bydest(instr.scope):
                    asm_progs[core].append({'op': 'done_stb'})

            else:
                raise Exception(f'{instr.name} not yet implemented')

    def _resolve_duplicate_jumps(self):
        #todo: write method to deal with multiple jump labels in a row
        pass

def proc_grouping_from_channelconfig(channel_configs: Dict[str, hw.ChannelConfig]) -> List[Tuple[str]]:
    proc_groups = defaultdict(list)
    for chan_name, channel in channel_configs.items():
        if isinstance(channel, hw.ChannelConfig):
            core_name = '' if channel.core_name is None else channel.core_name
            core_key = channel.board_name + core_name + str(channel.core_ind)
            proc_groups[core_key].append(chan_name)

    return list(tuple(grouping) for grouping in proc_groups.values())
        
@define
class CompiledProgram:
    """
    Simple class for reading/writing compiler output.

    Attributes
    ----------

    program: Dict[Tuple, List]

      - keys : proc group tuples (e.g. ('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo'))
            this is a tuple of channels that are driven by that proc core
      - values : assembly program for corresponding proc core, in the format
            specified at the top of assembler.py. 

            NOTE: there is one deviation from this format; pulse commands 
            have a 'dest' field indicating the pulse channel, instead of
            an 'elem_ind'
    proc_groups: List[Tuple]
        list of proc group tuples

    """

    program: Dict[Tuple[str], List[str]]
    fpga_config: hw.FPGAConfig = None

    @property
    def proc_groups(self):
        return self.program.keys()

    def serialize(self):
        jsondict = {str(tuple(proc_group)): prog for proc_group, prog in self.program.items()}
        if self.fpga_config is not None:
            jsondict['fpga_config'] = self.fpga_config

        return json.dumps(jsondict, indent=4, cls=ir._IREncoder, sort_keys=True)

def deserialize_compiled_program(prog_str: str):
    """
    De-serializes a compiled program object from a string (generated by `CompiledProgram.serialize`)

    Parameters
    ----------
    prog_str: str
        serialized program, generated by CompiledProgram.serialize
    """
    jsondict = json.loads(prog_str)
    if 'fpga_config' in jsondict:
        fpga_config = jsondict.pop('fpga_config')
    else:
        fpga_config = None
    program = {tuple(chan.strip() for chan in proc_group_str.strip('(').strip(')').replace("'", '').split(',')): prog 
               for proc_group_str, prog in jsondict.items()}

    return CompiledProgram(program, fpga_config)


def plot_pulse_sequence(compiled_program) -> pd.DataFrame:
    """
    Write a qubic sequence from a compiled_program.    

    Parameters
    ----------
    compiled_program (CompiledProgram): QubiC compiled program.    Returns:

    Returns
    -------
    pd.DataFrame: QubiC sequence.
    """
    from distproc.compiler import CompiledProgram
    assert isinstance(compiled_program, CompiledProgram)    
    df = pd.DataFrame()
    channels = list(compiled_program.program.keys())
    ns = 1.e-9
    us = 1.e-6
    for channel in channels:
        qubit = channel[0].split('.')[0]
        tags = []
        times = []
        # dests = []
        for pulse in compiled_program.program[channel]:
            if 'tag' in pulse.keys():
                tags.append(pulse['tag'])
                times.append(pulse['start_time'])
                # dests.append(pulse['dest'])
        times = np.array(times) - times[0]
        times = np.around(times* 2 * ns / us, 3)
        df = df.join(
            pd.DataFrame({qubit: tags}, index=times),
            how='outer'
        )    
        df.index.name = '[us]'

    return df.fillna('')

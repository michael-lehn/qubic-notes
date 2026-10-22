import distproc.compiler as cm
import distproc.assembler as am
import qubic.rfsoc.hwconfig as hw
import qubitconfig.qchip as qc
import json
import os
from typing import List, Dict, Tuple
import logging
from abc import ABC, abstractmethod

def run_compile_stage(program: List, 
                      fpga_config: hw.FPGAConfig, 
                      qchip: qc.QChip, 
                      compiler_flags: Dict[str, bool] | cm.CompilerFlags = None,
                      qubit_grouping: Tuple[str] = ('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo'),
                      proc_grouping: List[Tuple] = [('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')],
                      suppress_duplicate_warnings: bool = False) -> cm.CompiledProgram | List[cm.CompiledProgram]:
    """
    Wrapper around distributed processor compiler stage. 

    Parameters
    ----------
    program: list
        single QubiC program or list of programs. Each program can be:

            - list of dicts formatted according to the QubiC Higher-level 
              Representation
            - list of QubiC intermediate representation instructions 
              (distproc.ir_instruction classes)
    fpga_config: hw.FPGAConfig
    qchip: qc.QChip
    compiler_flags: dict | cm.CompilerFlags
        Options for configuring the compiler; see distproc.compiler.get_passes for 
        more details. Default is None, which sets all flags to True (fine for 
        most use cases)
    suppress_warnings: bool
        If True, suppress duplicate instances of a warning within a batch

    Returns
    -------
    CompiledProgram or List[CompiledProgram]
        object containing compiled program
    """
    if suppress_duplicate_warnings:
        initialize_logging(suppress_warnings=True)
    else:
        initialize_logging(suppress_warnings=False)

    passes = cm.get_passes(fpga_config, qchip, compiler_flags=compiler_flags, 
                           qubit_grouping=qubit_grouping, proc_grouping=proc_grouping)
    if isinstance(program[0], dict):
        compiler = cm.Compiler(program, proc_grouping)
        compiler.run_ir_passes(passes)
        return compiler.compile()
    elif isinstance(program[0], list):
        compiled_progs = []
        for circuit in program:
            compiler = cm.Compiler(circuit, proc_grouping)
            compiler.run_ir_passes(passes)
            compiled_progs.append(compiler.compile())
        return compiled_progs
    else:
        raise TypeError

def run_assemble_stage(compiled_program: cm.CompiledProgram | List[cm.CompiledProgram], 
                       channel_configs: Dict[str, hw.ChannelConfig], target_platform: str = 'rfsoc') -> Dict | List[Dict]:
    """
    Wrapper around distributed processor assembler stage. 

    Parameters
    ----------
    compiled_program: CompiledProgram | List[CompiledProgram]
    channel_configs: hw.ChannelConfig
    target_platform: str
        target hardware platform; currently only 'rfsoc' is supported

    Returns
    -------
    dict or list of dict
        dict(s) containing the assembled binaries 
    """
    if target_platform != 'rfsoc':
        raise Exception('rfsoc is currently the only supported platform!')

    if isinstance(compiled_program, list):
        raw_asm_progs = []
        for prog in compiled_program:
            asm = am.GlobalAssembler(prog, channel_configs, hw.elemconfig_classfactory)
            raw_asm_progs.append(asm.get_assembled_program())
        return raw_asm_progs

    else:
        asm = am.GlobalAssembler(compiled_program, channel_configs, hw.elemconfig_classfactory)
        return asm.get_assembled_program()

class ToolChainLogFilter(logging.Filter, ABC):
    """
    This is to make sure we have a reset method, and the ability to detect and
    remove logging filters that we have added (so we don't remove all filters).
    """

    @abstractmethod
    def reset(self):
        pass

class WarningSuppressor(ToolChainLogFilter):

    def __init__(self, stage='compile'):
        self._levels = ['warning']
        if stage == 'compile':
            self.modules = ['passes', 'compiler']
        else:
            raise NotImplementedError('filter for {stage} not implemented yet')
        self._prev_logs = set()

    def filter(self, record: logging.LogRecord):
        current_log = (record.levelname, record.msg)

        if record.module not in self.modules and record.levelname.lower() not in self._levels:
            return True
        elif current_log in self._prev_logs:
            return False
        else:
            self._prev_logs.add(current_log)
            return True

    def reset(self):
        self._prev_logs = set()

def initialize_logging(suppress_warnings=True):
    """
    TODO: add more logging options to user reqs, also maybe
    move the logging.basicConfig call to another global init method
    """
    logging.basicConfig()
    if suppress_warnings:
        for handler in logging.root.handlers:
            if len(handler.filters) == 0:
                handler.addFilter(WarningSuppressor())
            else:
                for filter in handler.filters:
                    if isinstance(filter, ToolChainLogFilter):
                        filter.reset()

    else:
        for handler in logging.root.handlers:
            for filter in handler.filters:
                if isinstance(filter, ToolChainLogFilter):
                    handler.removeFilter(filter)


import abc
from abc import ABC
from collections import OrderedDict
import qubic.state_disc as sd
import qubic.toolchain as tc
import qubic.results.counts as ct
from qubic.results.tools import pack_s11_results
from qubitconfig.qchip import QChip
from qubic.abstract_runner import AbstractCircuitRunner
from distproc.compiler import CompiledProgram, CompilerFlags
from distproc.executable import Executable
from distproc.hwconfig import ChannelConfig, FPGAConfig
from typing import Dict, List
import numpy as np
import logging
import itertools

try:
    import ipdb
except ImportError:
    pass

class JobManager:
    """
    Class for compiling and executing circuits. Contains necessary
    config objects for compilation, runner for execution, and 
    (optionally) GMMManager for state classification.

    Attributes
    ----------
    fpga_config : FPGAConfig 
    qchip : qubitconfig.qchip.QChip
    circuit_runner : CircuitRunner or CircuitRunnerClient
    gmm_manager : qubic.state_disc.GMMManager


    TODO: add readout correction and heralding
    """

    def __init__(self, fpga_config: FPGAConfig, 
                 channel_configs: Dict[str, ChannelConfig], 
                 circuit_runner: AbstractCircuitRunner,
                 qchip: QChip = None,
                 gmm_manager: sd.GMMManager = None, 
                 target_platform: str = 'rfsoc'):
        """
        Parameters
        ----------
        fpga_config: FPGAConfig
        channel_configs: Dict[str, ChannelConfig]
        circuit_runner: AbstractCircuitRunner
        qchip: QChip
        gmm_manager: sd.GMMManager
        target_platform: str
        """

        self.fpga_config = fpga_config
        self.channel_configs = channel_configs
        self.runner = circuit_runner
        self.qchip = qchip
        self.update_gmm(gmm_manager)

    def update_gmm(self, gmm_manager: sd.GMMManager):
        """
        Update the GMMManager used to classify IQ data.

        Parameters
        ----------
        gmm_manager: GMMManager
        """
        if gmm_manager is None: # instantiate empty GMMManager
            self.gmm_manager = sd.GMMManager(chanmap_or_chan_cfgs=self.channel_configs)
        elif isinstance(gmm_manager, str):
            self.gmm_manager = sd.GMMManager(load_file=gmm_manager, chanmap_or_chan_cfgs=self.channel_configs)
        else:
            assert isinstance(gmm_manager, sd.GMMManager)
            if hasattr(self,'gmm_manager'):
                self.gmm_manager.update(gmm_manager)
            else:
                self.gmm_manager=gmm_manager

    def build_and_run_circuits(self, program_list: List, 
                               n_total_shots: int, 
                               outputs : List[str] = ['s11'], 
                               compiler_flags: Dict[str, bool] | CompilerFlags = None, 
                               fit_gmm: bool = False, reads_per_shot: int = 1, 
                               qchip: QChip = None, 
                               reload_cmd: bool = True, 
                               reload_freq: bool = True, 
                               reload_env: bool = True, 
                               zero_between_reload: bool = True) -> dict:
        """
        Compile and run provided list of circuits. Output data products/analysis are controlled 
        by 'output' parameter. 

        Parameters
        ----------
        program_list: list
            list of QubiC circuits (input to compiler layer), CompiledProgram objects,
            or raw_asm_prog dicts.
        n_total_shots: int
            number of shots to run for each circuit
        outputs: list
            list of 's11', 'shots', and/or 'counts'
        compiler_flags: dict | CompilerFlags
            see CompilerFlags definition for allowed keys
        fit_gmm: bool
        qchip: qubitconfig.qchip.QChip
            if provided, override self.qchip for compilation
        reads_per_shot : int
            number of reads (measurements) per qubit in each instruction
        reload_cmd: bool
        reload_freq: bool
        reload_env: bool
        zero_between_reload: bool

        Returns
        -------
        dict
            results with keys/types matching the provided 'outputs'

        """
        if qchip is None:
            qchip = self.qchip

        if not isinstance(program_list, list):
            raise TypeError("program_list of invalid type")

        if isinstance(program_list[0], list):
            self.compiled_progs = tc.run_compile_stage(program_list, self.fpga_config, qchip, 
                                                       compiler_flags=compiler_flags)         
            self.raw_asm_progs = tc.run_assemble_stage(self.compiled_progs, self.channel_configs)
                
        elif isinstance(program_list[0], CompiledProgram):
            self.compiled_progs = program_list
            self.raw_asm_progs = tc.run_assemble_stage(self.compiled_progs, self.channel_configs)

        elif isinstance(program_list[0], Executable): #this is raw asm
            #todo: put in check for raw asm
            self.raw_asm_progs = program_list

        else:
            raise TypeError('{} invalid program list'.format(program_list))

        s11 = self.runner.run_circuit_batch(self.raw_asm_progs, n_total_shots, reads_per_shot,
                                            reload_cmd=reload_cmd, reload_freq=reload_freq, reload_env=reload_env, 
                                            zero_between_reload=zero_between_reload)

        output_dict = {}
        if fit_gmm:
            packed_s11 = pack_s11_results(s11)
            self.gmm_manager.fit(packed_s11)
            self.gmm_manager.set_labels_maxtomin(packed_s11, [0, 1])

        if 's11' in outputs:
            output_dict['s11'] = s11
        if 'shots' in outputs or 'counts' in outputs:
            if 'shots' in outputs:
                output_dict['shots'] = []
            if 'counts' in outputs:
                output_dict['counts'] = []

            for s11_i in s11:
                shots = self.gmm_manager.predict(s11_i)
                if 'shots' in outputs:
                    output_dict['shots'].append(shots)
                if 'counts' in outputs:
                    output_dict['counts'].append(ct.CircuitCounts(shots))

        return output_dict

    def collect_all(self, program_list: List, num_shots_per_circuit: int, 
                    reads_per_shot: int | dict = 1, qchip: QChip = None) -> dict:
        """
        Wrapper around build_and_run_circuits with simplified args. All output data
        products (shots, counts, s11) are provided).

        Parameters
        ----------
        program_list: list
            list of QubiC circuits (input to compiler layer), CompiledProgram objects,
            or raw_asm_prog dicts.
        num_shots_per_circuit: int
            number of shots to run for each circuit
        reads_per_shot: int
        qchip: qubitconfig.qchip.QChip
            if provided, override self.qchip for compilation

        Returns
        -------
            dict
                all result types, keyed by ['s11', 'shots', 'counts']
        """
        output_dict = self.build_and_run_circuits(program_list, num_shots_per_circuit, ['s11','shots','counts'],
                                                    reads_per_shot=reads_per_shot, qchip=qchip)
        return {k:output_dict[k] for k in ['s11','shots','counts']}

    def collect_raw_IQ(self, program_list: list, num_shots_per_circuit: int, 
                       reads_per_shot: int | dict = 1, qchip: QChip = None) -> dict:
        """
        Wrapper around build_and_run_circuits with simplified args. Returns integrated,
        unclassified IQ data.

        Parameters
        ----------
        program_list: list
            list of QubiC circuits (input to compiler layer), CompiledProgram objects,
            or raw_asm_prog dicts.
        num_shots_per_circuit: int
            number of shots to run for each circuit
        reads_per_shot: int
        qchip: qubitconfig.qchip.QChip
            if provided, override self.qchip for compilation

        Returns
        -------
        dict
            accumulated s11 shots, keyed by channel index
        """
        output_dict = self.build_and_run_circuits(program_list, num_shots_per_circuit, ['s11'],
                                                    reads_per_shot=reads_per_shot, qchip=qchip)
        return output_dict['s11']

    def collect_classified_shots(self, program_list: list, num_shots_per_circuit: int, 
                                 reads_per_shot: int | dict, qchip: QChip = None) -> dict:
        """
        Wrapper around build_and_run_circuits with simplified args. Returns integrated,
        classified IQ data.

        Parameters
        ----------
        program_list: list
            list of QubiC circuits (input to compiler layer), CompiledProgram objects,
            or raw_asm_prog dicts.
        num_shots_per_circuit: int
            number of shots to run for each circuit
        reads_per_shot: int
        qchip: qubitconfig.qchip.QChip
            if provided, override self.qchip for compilation

        Returns
        -------
        dict
            classified shots, keyed by qubit
        """
        output_dict = self.build_and_run_circuits(program_list, num_shots_per_circuit, ['shots'], reads_per_shot=reads_per_shot, qchip=qchip)
        return output_dict['shots']

    def collect_counts(self, program_list: list, num_shots_per_circuit: int, 
                       reads_per_shot: int | dict, qchip: QChip = None) -> List[ct.CircuitCounts]:
        """
        Wrapper around build_and_run_circuits with simplified args. Returns list of bitstring
        counts (List[CircuitCounts] object).

        Parameters
        ----------
        program_list: list
            list of QubiC circuits (input to compiler layer), CompiledProgram objects,
            or raw_asm_prog dicts.
        num_shots_per_circuit: int
            number of shots to run for each circuit
        reads_per_shot: int
        qchip: qubitconfig.qchip.QChip
            if provided, override self.qchip for compilation

        Returns
        -------
        List[CircuitCounts]
            results in the form of bitstring counts
        """
        output_dict = self.build_and_run_circuits(program_list, num_shots_per_circuit, ['counts'],
                                                    reads_per_shot=reads_per_shot, qchip=qchip)
        return output_dict['counts']


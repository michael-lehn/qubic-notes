"""Core tools for QubiC intermediate representation (IR). Compiler
passes found in passes.py (and rc_passes.py), instruction set is in instructions.py
"""

from attrs import define, field
from typing import List, Dict, Tuple, Set
import numpy as np
import json
import networkx as nx
import parse
import re
from abc import ABC, abstractmethod
import qubitconfig.qchip as qc
import logging
import distproc.hwconfig as hw
import distproc.ir.instructions as iri

DEFAULT_N_QUBITS = 20

@define
class _Frequency:
    freq: float
    zphase: float
    scope: set = field(converter=lambda x: set() if x is None else x)

    def to_dict(self) -> Dict[str, float | set]:
        d = {'freq': self.freq, 'zphase': self.zphase}
        if self.scope is not None:
            d['scope'] = self.scope

        return d

@define
class _Variable:
    name: str
    scope: set = field(converter=lambda x: set() if x is None else x)
    dtype: str = 'int' # 'int', 'phase', or 'amp'

    def to_dict(self) -> Dict[str, str]:
        return {'scope': self.scope, 'dtype': self.dtype}

@define
class _Loop:
    name: str
    scope: set 
    start_time: int
    delta_t: int

    def to_dict(self) -> Dict[str, str | set | int]:
        return {'scope': self.scope, 'start_time': self.start_time, 'delta_t': self.delta_t}

class IRProgram:
    """
    Defines and stores an intermediate representation for qubic programs. All program 
    instructions are defined by one of the (public) classes in ir_instructions.py. 

    The program itself is stored in the control_flow_graph attribute, where each node is 
    a "basic block", defined to be a chunk of code with only linear control flow (i.e. all
    jumps, etc happen between blocks, not inside a block). The possible control flow paths
    through the program are specified as directed edges within this graph, and are determined
    during the GenerateCFG pass.

    In general, each node has the following attibutes:

      - instructions: list containing the program instructions
      - scope: set of channels involved with this block
    Other attributes can be added during various compiler passes

    Attributes
    ----------
    freqs: Dict[float | str, float]
        dictionary of named or anonymous freqs
    vars: Dict[str, _Variable]
        dictionary of _Variable objects (mapped to proc core registers)
    loops: Dict[str, _Loop]
        dictionary of named _Loop objects (stores start time and delta_t for scheduling)
    hw_zphase_bindings: Dict[float | str, str]
        dictionary mapping freq --> var if virtual-z phase tracking is done in hardware

    """

    def __init__(self, source: List | Dict | str):
        """
        Parameters
        ----------
        source: List | Dict | str 
            Program source. Can be any of the following forms:
                - List of instructions (dict or instruction classes). If instructions are dict,
                  they are converted to class-based representations. Metadata fields (freqs, vars, 
                  control_flow_graph, etc) are initialized empty
                - Dictionary (with or without metadata). Must contain 'program' field, which can either 
                  be a list of instructions, or a dictionary of basic blocks (each containing a list of instructions).
                  Metadata is initialized as necessary.
                - JSON string. Decoded and resolved into one of the above forms.

        """
        self._freqs = {}
        self._vars = {}
        self._hw_zphase_bindings = {}
        self.loops = {}
        if isinstance(source, str):
            source = json.loads(source)
        if isinstance(source, list):
            self._cfg_from_list(source)
        elif isinstance(source, dict):
            if isinstance(source['program'], list):
                self._cfg_from_list(source['program'])
            else:
                self._cfg_from_blocks(source['program'])

            if 'vars' in source:
                for varname, vardict in source['vars'].items():
                    self.register_var(varname, vardict['scope'], vardict['dtype'])

            if 'freqs' in source:
                for freqname, freq in source['freqs'].items():
                    self.register_freq(freqname, freq)

            if 'loops' in source:
                for loopname, loop in source['loops'].items():
                    self.register_loop(loopname, loop['scope'], loop['start_time'], loop['delta_t'])

            if 'hw_zphase_bindings' in source:
                for freq, var in source['hw_zphase_bindings'].items():
                    self.register_phase_binding(freq, var)

            if 'control_flow_graph' in source:
                for node, targets in source['control_flow_graph'].items():
                    for target in targets:
                        self.control_flow_graph.add_edge(node, target)

            if 'scope' in source:
                for blockname, scope in source['scope'].items():
                    self.control_flow_graph.nodes[blockname]['scope'] = set(scope)

        else:
            raise Exception(f'Invalid program format: {type(source)}')

    def _cfg_from_list(self, instr_list):
        if isinstance(instr_list[0], dict):
            instr_list = _resolve_instr_objects(instr_list)
        self.control_flow_graph = nx.DiGraph()
        self.control_flow_graph.add_node('block_0', instructions=instr_list, ind=0)

    def _cfg_from_blocks(self, block_dict):
        self.control_flow_graph = nx.DiGraph()
        for i, (blockname, instrs) in enumerate(block_dict.items()):
            if isinstance(instrs[0], dict):
                instrs = _resolve_instr_objects(instrs)
            self.control_flow_graph.add_node(blockname, instructions=instrs, ind=i)
 
    @property
    def blocks(self):
        return self.control_flow_graph.nodes

    @property
    def blocknames_by_ind(self):
        return sorted(self.control_flow_graph.nodes, key=lambda node: self.control_flow_graph.nodes[node]['ind'])

    @property
    def freqs(self):
        return self._freqs

    @property
    def vars(self):
        return self._vars

    @property
    def bound_zphase_freqs(self) -> list:
        """
        freq (names) whose phases are bound to a hardware register
        """
        return list(self._hw_zphase_bindings.keys())

    @property
    def scope(self) -> set[str]:
        """
        Channel scope of the full program
        """
        return set().union(*list(self.control_flow_graph.nodes[node]['scope'] for node in self.blocks))

    def get_zphase_var(self, freq) -> str:
        return self._hw_zphase_bindings[freq]

    def register_freq(self, key: float | str, freq: float) -> None:
        if key in self._freqs and self._freqs[key] != freq:
            raise Exception(f'frequency {key} already registered; provided freq {freq}\
                    does not match {self._freqs[key]}')
        self._freqs[key] = freq

    def register_phase_binding(self, freq: float | str, varname: str) -> None:
        assert varname in self._vars.keys()
        assert self._vars[varname].dtype == 'phase'
        if freq in self._hw_zphase_bindings and varname != self._hw_zphase_bindings[freq]:
            raise Exception(f'frequency {freq} already bound to {self._hw_zphase_bindings[freq]}')
        self._hw_zphase_bindings[freq] = varname

    def register_var(self, varname, scope, dtype) -> None:
        if varname in self._vars.keys():
            if scope is not None:
                self._vars[varname].scope = set(scope).union(self._vars[varname].scope)
            if dtype != self._vars[varname].dtype:
                raise Exception(f'conflicting declarations of {varname} found')
        else:  
            self._vars[varname] = _Variable(varname, scope, dtype)

    def register_loop(self, name, scope, start_time, delta_t=None) -> None:
        self.loops[name] = _Loop(name, scope, start_time, delta_t)

    def serialize(self) -> str:
        """
        serialize the program into a json string

        Returns
        -------
        str
            JSON string of the program and any metadata attributes
        """
        jsondict = {}
        progdict = {}
        for nodename in self.blocknames_by_ind:
            instructions = self.blocks[nodename]['instructions']
            progdict[nodename] = []
            for instr in instructions:
                progdict[nodename].append(instr.to_dict())

        jsondict['program'] = progdict

        if self.vars:
            jsondict['vars'] = {}
            for varname, var in self.vars.items():
                jsondict['vars'][varname] = var.to_dict()

        if self.freqs:
            jsondict['freqs'] = {}
            for freqname, freq in self.freqs.items():
                jsondict['freqs'][freqname] = freq

        if self.loops:
            jsondict['loops'] = {}
            for loopname, loop in self.loops.items():
                jsondict['loops'][loopname] = loop.to_dict()

        if self._hw_zphase_bindings:
            jsondict['hw_zphase_bindings'] = {}
            for freq, varname in self._hw_zphase_bindings.items():
                jsondict['hw_zphase_bindings'][freq] = varname

        if 'scope' in self.control_flow_graph.nodes[self.blocknames_by_ind[0]]:
            jsondict['scope'] = {}
            for nodename in self.blocknames_by_ind:
                jsondict['scope'][nodename] = self.blocks[nodename]['scope']

        cfg_edges = {}
        for nodename in self.blocks:
            cfg_edges[nodename] = list(self.control_flow_graph.successors(nodename))

        jsondict['control_flow_graph'] = cfg_edges

        return json.dumps(jsondict, indent=4, cls=_IREncoder)


def _resolve_instr_objects(source: list[dict]):
    full_program = []
    for instr in source:
        instr_class = getattr(iri, _get_instr_classname(instr['name']))
        if instr['name'] == 'virtualz':
            instr['name'] = 'virtual_z'

        instr_obj = instr_class(**instr)

        if 'true' in instr.keys():
            instr_obj.true = _resolve_instr_objects(instr['true'])
        if 'false' in instr.keys():
            instr_obj.false = _resolve_instr_objects(instr['false'])
        if 'body' in instr.keys():
            instr_obj.body = _resolve_instr_objects(instr['body'])

        full_program.append(instr_obj)

    return full_program


def _get_instr_classname(name):
    classname = ''.join(word.capitalize() for word in name.split('_'))
    if name == 'virtualz':
        classname = 'VirtualZ'
    elif classname not in dir(iri):
        classname = 'Gate'
    return classname


class _IREncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return sorted(list(obj))
        elif isinstance(obj, np.ndarray):
            return list(obj)
        elif isinstance(obj, np.complexfloating):
            return str(obj)
        else:
            return json.JSONEncoder.default(self, obj)


class QubitScoper(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def get_scope(self, qubits) -> Set[str]:
        pass

class QubitScoperFromTup(QubitScoper):
    """
    Class for handling qubit -> channel mapping.
    "Scope" here refers to the set of channels a given instruction will affect (blcok)
    for scheduling and control flow purposes. For example, an X90 gate on Q1 will 
    be scoped to all channels Q1.*, since we don't want any other pulses playing on
    the other Q1 channels simultaneously. 

    Qubits should be explicitly declared using the `qubits` parameter to `__init__`. 
    """

    def __init__(self, mapping: Tuple[str] = ('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo'), qubits: int | List | Set | Tuple = None):
        self._mapping = mapping

        if isinstance(qubits, int):
            self._qubits = set([f'Q{i}' for i in range(qubits)])
        else:
            self._qubits = qubits

    def get_scope(self, qubits) -> Set[str]:
        if isinstance(qubits, str):
            qubits = [qubits]

        channels = ()
        for qubit in qubits:
            if self.is_qubit(qubit):
                qubit_chans = tuple(chan.format(qubit=qubit) for chan in self._mapping)
            else:
                qubit_chans = (qubit,)
            channels += qubit_chans

        return set(channels)

    def is_qubit(self, qubit: str) -> bool:
        if self._qubits is None:
            if re.fullmatch('Q\\d+', qubit) is not None:
                return True
            else:
                return False
        else:
            return qubit in self._qubits


class QubitScoperFromDict(QubitScoper):
    def __init__(self, mapping: Dict[str, List[str] | Set[str] | Tuple[str]]):
        """
        mapping: Dict[str, set | list | tuple]
        """
        self._map_dict = mapping

    def get_scope(self, qubits) -> Set[str]:
        if isinstance(qubits, str):
            qubits = [qubits]

        channels = set()
        for qubit in qubits:
            channels = channels.union(set(self._map_dict[qubit]))

        return channels


class Pass(ABC):
    """
    Passes go here. An abstract "Pass" class is used to make it easy to create parameterized
    passes and give them to the compiler
    """
    def __init__(self):
        """
        Configuration parameters are passed in here
        """
        pass

    @abstractmethod
    def run_pass(self, ir_prog: IRProgram) -> None:
        """
        Only argument should be `ir_prog`. Effects should mutate the `ir_prog` object;
        nothing is returned.

        Parameters
        ----------
        ir_prog: IRProgram
        """
        pass


class CoreScoper:
    """
    Class for grouping firmware output channels into distributed processor cores. Processor cores are named using
    a tuple of channels controlled by that core (e.g. (Q0.qdrv, Q0.rdrv, Q0.rdlo))
    """

    def __init__(self, qchip_or_dest_channels=None, proc_grouping=[('{qubit}.qdrv', '{qubit}.rdrv', '{qubit}.rdlo')]):
        if isinstance(qchip_or_dest_channels, qc.QChip):
            self._dest_channels = qchip_or_dest_channels.dest_channels
        else:
            self._dest_channels = qchip_or_dest_channels
        self._generate_proc_groups(proc_grouping)

        self.proc_groupings_flat = set(self.proc_groupings.values())

    def _generate_proc_groups(self, proc_grouping):
        proc_groupings = {}
        for dest in self._dest_channels:
            for group in proc_grouping:
                for dest_pattern in group:
                    sub_dict = parse.parse(dest_pattern, dest)
                    if sub_dict is not None:
                        proc_groupings[dest] = tuple(pattern.format(**sub_dict.named) for pattern in group)

        self.proc_groupings = proc_groupings

    def get_groups_bydest(self, dests):
        """
        Given a set of destination channels, returns a set of tuples indicating the processor cores used to 
        control those channels

        Parameters
        ----------
            dests: set
                set of firmware output channels (e.g. {'Q0.qdrv', 'Q1.rdlo'})
        Returns
        -------
            set
                set of tuples that index all of the proc cores needed to control all of the channels in 'dests'
        """
        groups = set()
        for dest in dests:
            groups.add(self.proc_groupings[dest])

        return groups

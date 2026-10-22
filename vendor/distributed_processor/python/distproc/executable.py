from attrs import define, field, asdict
from typing import Dict, List, Tuple
from xmlrpc.client import Binary
import json

@define(unsafe_hash=True)
class ResultChannel:
    """
    Stores metadata for resultumulated buffer channel. 
    """
    mem_name: str
    board: str = ''
    reads_per_shot: int = 1
    dtype: str = 's11'

class Executable:
    """
    Stores the compiled QubiC program.

    Attributes
    ----------
    program_binaries: Dict[str, bytes]
        compiled program data; including both instruction
        memory and waveform/frequency memory. Formatted as 
        a dictionary keyed by the name of the memory to write
        (referenced to the bram.json found in the release tarball)
    result_channels: Dict[str, ResultChannel]
        resultumulated buffer channels to read (i.e. list of single-shot 
        IQ values). 
    boards: List[str]
    """

    def __init__(self, 
                 program_binaries: Dict[str, bytes | Binary] = None, 
                 write_registers: Dict[str, int] = None,
                 result_channels: Dict[str, ResultChannel] = None):

        if program_binaries is not None:
            self.program_binaries = {}
            for name, prog in program_binaries.items():
                if isinstance(prog, Binary):
                    self.program_binaries[name] = prog.data
                elif isinstance(prog, bytes):
                    self.program_binaries[name] = prog
                else:
                    raise Exception(f'Binary {name} has unexpected type: {type(prog)}')
        else:
            self.program_binaries = {}

        if write_registers is not None:
            self.write_registers = write_registers
        else:
            self.write_registers = {}

        self.result_channels = result_channels if result_channels is not None else {}
    
    def add_mem_buffer(self, name: str, board: str = '', data: bytes = None) -> None:
        """
        Add program (write) memory to the executable.

        Parameters
        ----------
        name: str
            name of memory to write
        board: str
            name of board to write (only required for multi-board server mode)
        data: bytes
            data to write
        """
        mem_name = f'{board}:{name}'
        if mem_name in self.program_binaries.keys():
            raise Exception(f'Memory {mem_name} already exists!')
        self.program_binaries[mem_name] = data

    def add_write_register(self, name: str, board: str = '', value: int = None) -> None:
        """
        Add program (write) register to the executable.

        Parameters
        ----------
        name: str
            name of memory to write
        board: str
            name of board to write (only required for multi-board server mode)
        value: int 
            value to write
        """
        reg_name = f'{board}:{name}'
        if reg_name in self.write_registers.keys():
            raise Exception(f'Memory {reg_name} already exists!')
        self.write_registers[reg_name] = value

    def add_result_chan(self, chan_name: str, mem_name: str, board: str = '', reads_per_shot: int = 1, dtype: str = 's11') -> None:
        if chan_name in self.result_channels:
            raise Exception(f'Channel {chan_name} already exists!')
        self.result_channels[chan_name] = ResultChannel(mem_name, board, reads_per_shot, dtype)

    def get_binaries_fromboard(self, board: str = None) -> Dict[str, bytes]:
        """
        Returns a dictionary of program write memories corresponding to the 
        specified board.

        Parameters
        ----------
        board: str
        """
        if board is None:
            return {memname.split(':')[1]: prog for memname, prog in self.program_binaries.items()}
        else:
            return {memname.split(':')[1]: prog for memname, prog 
                    in self.program_binaries.items() if memname.split(':')[0] == board}

    def get_registers_fromboard(self, board: str = None) -> Dict[str, bytes]:
        """
        Returns a dictionary of program write memories corresponding to the 
        specified board.

        Parameters
        ----------
        board: str
        """
        if board is None:
            return {regname.split(':')[1]: prog for regname, prog in self.write_registers.items()}
        else:
            return {regname.split(':')[1]: prog for regname, prog 
                    in self.write_registers.items() if regname.split(':')[0] == board}

    def get_board_executable(self, board: str):
        """
        Slices out a single board from the executable.

        Parameters
        ----------
        board: str

        Returns
        -------
        Executable
        """
        return Executable({memname: prog for memname, prog in self.program_binaries.items() if memname.split(':')[0] == board},
                          {regname: value for regname, value in self.write_registers.items() if regname.split(':')[0] == board},
                          {channame: chan for channame, chan in self.result_channels.items() if chan.board == board})

    @property
    def boards(self) -> List[str]:
        return list(set(memname.split(':')[0] for memname in self.program_binaries.keys()))

    def __add__(self, other):
        if len(set(self.program_binaries.keys()).intersection(set(other.program_binaries.keys()))) != 0:
            raise Exception(f'Collision in program memory names: '
                            f'{set(self.program_binaries.keys()).intersection(set(other.program_binaries.keys()))}')
        if len(set(self.write_registers.keys()).intersection(set(other.write_registers.keys()))) != 0:
            raise Exception(f'Collision in write register names: '
                            f'{set(self.write_registers.keys()).intersection(set(other.write_registers.keys()))}')
        if len(set(self.result_channels.keys()).intersection(set(other.result_channels.keys()))) != 0:
            raise Exception(f'Collision in result channels: '
                            f'{set(self.result_channels.keys()).intersection(set(other.result_channels.keys()))}')
        return Executable({**self.program_binaries, **other.program_binaries}, 
                          {**self.write_registers, **other.write_registers},
                          {**self.result_channels, **other.result_channels})

    def to_dict(self) -> Dict[str, Dict]:
        return {'program_binaries': self.program_binaries, 
                'write_registers': self.write_registers,
                'result_channels': {channame: asdict(chan) for channame, chan in self.result_channels.items()}}

    #todo: consider making this class immutable
    def __hash__(self):
        hash_str = json.dumps(self.program_binaries, cls=_ExeEncoder, sort_keys=True)
        hash_str += json.dumps(self.result_channels, cls=_ExeEncoder, sort_keys=True)
        return hash(hash_str)


def executable_from_dict(progdict):
    return Executable(progdict['program_binaries'], 
                      progdict['write_registers'],
                      {channame: ResultChannel(**chandict) for channame, chandict in progdict['result_channels'].items()})


class _ExeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes) or isinstance(obj, ResultChannel):
            return hash(obj)
        else:
            return json.JSONEncoder.default(self, obj)


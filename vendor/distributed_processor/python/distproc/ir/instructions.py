from attrs import define, field, cmp_using
from typing import Dict, List, Set, Tuple
import attrs
from abc import ABC, abstractmethod, abstractproperty
import numpy as np

class _PhaseTracker(ABC):
    pass

@define
class _NamedPhaseTracker:
    qubit: str = field(default=None)
    _freq: str | float = field(default=None)
    _default_qubit_freq = field(init=False, default='freq')

    """
    Class for phase-tracker name resolution (stored in freq attribute)

    Attributes
    ----------
        freq: name of phase tracker
        qubit: (optional) associated qubit name

    Rules for name resolution (return value of obj.freq):
        if only freq is given:
            return f'{freq}' # freq can be float or str
        if qubit is given, freq is None:
            return f'{qubit}.freq'
        if qubit and freq are both given:
            return f'{qubit}.{freq}'
    """

    def __attrs_post_init__(self):
        if isinstance(self.qubit, list) or isinstance(self.qubit, tuple):
            assert len(self.qubit) == 1
            self.qubit = self.qubit[0]
        assert isinstance(self.qubit, str) or self.qubit is None

    @property
    def freq(self):
        if self.qubit is not None:
            if isinstance(self._freq, str):
                return f'{self.qubit}.{self._freq}'
            elif self._freq is None:
                return f'{self.qubit}.{self._default_qubit_freq}'
            else:
                return self._freq
        else:
            return self._freq

    def to_dict(self) -> Dict[str, str]:
        """
        This preserves inputs; need to decide whether to just
        return resolved freq instead
        """
        jsondict = {}
        if self.qubit is not None:
            jsondict.update({'qubit': self.qubit})
        if self._freq is not None:
            jsondict.update({'freq': self.freq})

        return jsondict

def normalize_func_id(func_id):
    if isinstance(func_id, list):
        return tuple(func_id)
    else:
        assert isinstance(func_id, str | tuple | int)
        return func_id


def _normalize_scope(scope): 
    if scope is None or isinstance(scope, set):
        return scope
    if isinstance(scope, str):
        return set([scope])
    elif isinstance(scope, list) or isinstance(scope, tuple):
        return set(scope) 
    else:
        raise TypeError(f'Invalid type {type(scope)} for scope: {scope}')


@define(frozen=True)
class _FrameComponent:
    name: str
    coefficient: float = 1

@define
class DerivePhaseTracker:
    components: List[tuple[str]] # these should be name-resolved frequencies, not qubits
    _qubit: str = None
    _freq: str | float = None
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    _phase_tracker: _NamedPhaseTracker = field(init=False, default=None)
    name: str = field(default='derive_phase_tracker')

    def __attrs_post_init__(self):
        self._phase_tracker = _NamedPhaseTracker(self._qubit, self._freq)
        self.components = [_FrameComponent(*component) for component in self.components]

    @property
    def qubit(self):
        return self._phase_tracker.qubit

    @property
    def freq(self):
        return self._phase_tracker.freq


@define
class _BlockStart:
    name: str = field(default='block_start')
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)


@define
class _BlockEnd:
    name: str = field(default='block_end')


@define
class Block:
    body: list
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='block')


@define
class Gate:
    name: str = field(validator=attrs.validators.instance_of(str))
    _qubit: List[str] | str = field()
    modi: dict = None
    start_time: int = None
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)

    @_qubit.validator
    def _typecheck_qubit(self, attribute, value):
        if isinstance(value, list) or isinstance(value, tuple):
            all(isinstance(qb, str) for qb in value)
        else:
            assert isinstance(value, str)

    @property
    def qubit(self):
        if isinstance(self._qubit, list):
            return self._qubit
        elif isinstance(self._qubit, tuple):
            return list(self._qubit)
        elif isinstance(self._qubit, str):
            return [self._qubit]
        else:
            raise TypeError

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'qubit': self.qubit}
        if self.modi is not None:
            instr_dict.update({'modi': self.modi})
        if self.start_time is not None:
            instr_dict.update({'start_time': self.start_time})
        if self.scope is not None:
            instr_dict.update({'scope': self.scope})

        return instr_dict

@define
class Pulse:
    freq: str | float
    twidth: float
    env: np.ndarray | dict = field(eq=cmp_using(np.array_equal)) # Otherwise equality checks between pulses fail
    dest: str
    phase: str | float = 0
    amp: str | float = 1
    start_time: int = None
    tag: str = None
    save_result: bool = None
    name: str = field(default='pulse')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'freq': self.freq, 'twidth': self.twidth,
                      'dest': self.dest, 'phase': self.phase, 'amp': self.amp}
        if isinstance(self.env, np.ndarray):
            instr_dict.update({'env': list(self.env)})
        else:
            instr_dict.update({'env': self.env})
        if self.tag is not None:
            instr_dict.update({'tag': self.tag})
        if self.start_time is not None:
            instr_dict.update({'start_time': self.start_time})

        return instr_dict

@define
class VirtualZ:
    phase: float
    name: str = field(default='virtual_z')
    _qubit: str = None
    _freq: str | float = None
    _phase_tracker: _NamedPhaseTracker = field(init=False, default=None)
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)

    def __attrs_post_init__(self):
        self._phase_tracker = _NamedPhaseTracker(self._qubit, self._freq)

    @property
    def qubit(self):
        return self._phase_tracker.qubit

    @property
    def freq(self):
        return self._phase_tracker.freq

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'phase': self.phase}
        instr_dict.update(self._phase_tracker.to_dict())
        if self.scope is not None:
            instr_dict.update({'scope': self.scope})

        return instr_dict

@define
class DeclareFreq:
    freq: float
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='declare_freq')
    freqname: str = None
    freq_ind: int = None

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'freq': self.freq, 'scope': self.scope}
        if self.freqname is not None:
            instr_dict['freqname'] = self.freqname
        if self.freq_ind is not None:
            instr_dict['freq_ind'] = self.freq_ind
        return instr_dict

@define
class BindPhase:
    var: str
    _qubit: str = None
    _freq: str | float = None
    _phase_tracker: _NamedPhaseTracker = field(init=False, default=None)
    name: str = field(default='bind_phase')
    scope: List[str] | Set[str] | Tuple[str] = None

    def __attrs_post_init__(self):
        self._phase_tracker = _NamedPhaseTracker(self._qubit, self._freq)

    @property
    def qubit(self):
        return self._phase_tracker.qubit

    @property
    def freq(self):
        return self._phase_tracker.freq
    
    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'var': self.var}
        instr_dict.update(self._phase_tracker.to_dict())
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class Barrier:
    name: str = field(default='barrier')
    qubit: list = None
    scope: List[str] | Set[str] | Tuple[str] = None

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name}
        if self.qubit is not None:
            instr_dict['qubit'] = self.qubit
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class Delay:
    t: float
    name: str = field(default='delay')
    qubit: list = None
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 't': self.t}
        if self.qubit is not None:
            instr_dict['qubit'] = self.qubit
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class Idle:
    end_time: int
    name: str = field(default='idle')
    qubit: list = None
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'end_time': self.end_time}
        if self.qubit is not None:
            instr_dict['qubit'] = self.qubit
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class Hold:
    """
    HOLD execution at this point until it has been 
    nclks since the end of the last pulse on channels
    ref_chans. Gets resolved into Idle. 
    """
    nclks: int
    ref_chans: list | tuple | set = None
    qubit: list = None
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='hold')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'nclks': self.nclks}
        if self.qubit is not None:
            instr_dict['qubit'] = self.qubit
        if self.ref_chans is not None:
            instr_dict['ref_chans'] = self.ref_chans
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class Loop:
    cond_lhs: int | str
    alu_cond: str
    cond_rhs: str
    body: list
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='loop')

    def to_dict(self) -> Dict:
        return {'name': self.name, 'cond_lhs': self.cond_lhs,
                'alu_cond': self.alu_cond, 'cond_rhs': self.cond_rhs,
                'scope': self.scope, 'body': [instr.to_dict() for instr in self.body]}

@define
class JumpFproc:
    alu_cond: str
    cond_lhs: int | str
    func_id: int | str | Tuple[str] = field(converter=normalize_func_id)
    jump_label: str
    jump_type: str = None
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='jump_fproc')

    def to_dict(self) -> Dict:
        instr_dict =  {'name': self.name, 'cond_lhs': self.cond_lhs,
                       'alu_cond': self.alu_cond, 'func_id': self.func_id,
                       'scope': self.scope, 'jump_label': self.jump_label}

        if self.jump_type is not None:
            instr_dict['jump_type'] = self.jump_type

        return instr_dict

@define
class BranchFproc:
    alu_cond: str
    cond_lhs: int | str
    func_id: int | str | Tuple[str] = field(converter=normalize_func_id)
    true: list
    false: list
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='branch_fproc')

    def to_dict(self) -> Dict:
        return {'name': self.name, 'cond_lhs': self.cond_lhs,
                'alu_cond': self.alu_cond, 'func_id': self.func_id,
                'scope': self.scope, 
                'true': 
                        [instr.to_dict() for instr in self.true], 
                'false':
                        [instr.to_dict() for instr in self.false]}

@define
class ReadFproc:
    func_id: int | str | Tuple[str] = field(converter=normalize_func_id)
    var: str
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='read_fproc')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'func_id': self.func_id, 'var': self.var}
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class AluFproc:
    func_id: int | str | Tuple[str] = field(converter=normalize_func_id)
    lhs: int | str
    op: str
    out: str
    scope: List[str] | Set[str] | Tuple[str] = None
    name: str = field(default='alu_fproc')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'func_id': self.func_id, 'lhs': self.lhs,
                      'op': self.op, 'out': self.out}
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class JumpLabel:
    label: str
    scope: List[str] | Set[str] | Tuple[str] = field(converter=_normalize_scope)
    name: str = field(default='jump_label')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'label': self.label}
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define 
class JumpCond:
    cond_lhs: int | str
    alu_cond: str
    cond_rhs: str
    jump_label: str
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    jump_type: str = None
    name: str = field(default='jump_cond')
    def to_dict(self) -> Dict:
        instr_dict =  {'name': self.name, 'cond_lhs': self.cond_lhs,
                       'alu_cond': self.alu_cond, 'cond_rhs': self.cond_rhs,
                       'scope': self.scope, 'jump_label': self.jump_label}

        if self.jump_type is not None:
            instr_dict['jump_type'] = self.jump_type

        return instr_dict

@define 
class BranchVar:
    cond_lhs: int | str
    alu_cond: str
    cond_rhs: str
    true: list
    false: list
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='branch_var')

    def to_dict(self) -> Dict:
        return {'name': self.name, 'cond_lhs': self.cond_lhs,
                'alu_cond': self.alu_cond, 'cond_rhs': self.cond_rhs,
                'scope': self.scope, 
                'true': 
                        [instr.to_dict() for instr in self.true], 
                'false':
                        [instr.to_dict() for instr in self.false]}

@define
class JumpI:
    scope: List[str] | Set[str] | Tuple[str] = field(converter=_normalize_scope)
    jump_label: str
    jump_type: str = None
    name: str = field(default='jump_i')

    def to_dict(self) -> Dict:
        instr_dict =  {'name': self.name, 'scope': self.scope, 
                       'jump_label': self.jump_label}

        if self.jump_type is not None:
            instr_dict['jump_type'] = self.jump_type

        return instr_dict

@define
class Declare:
    var: str
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    dtype: str = 'int' # 'int', 'phase', or 'amp'
    name: str = field(default='declare')

    def to_dict(self) -> Dict:
        return {'name': self.name, 'var': self.var,
                'scope': self.scope, 'dtype': self.dtype}

@define
class LoopEnd:
    scope: List[str] | Set[str] | Tuple[str] = field(converter=_normalize_scope)
    loop_label: str
    name: str = field(default='loop_end')

    def to_dict(self) -> Dict:
        return {'name': self.name, 'loop_label': self.loop_label,
                'scope': self.scope}

@define
class Alu:
    op: str
    lhs: str | int | float
    rhs: str
    out: str
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='alu')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'lhs': self.lhs, 'rhs': self.rhs,
                      'op': self.op, 'out': self.out}
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class SetVar:
    value: int | float
    var: str
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='set_var')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name, 'var': self.var,
                      'value': self.value}
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

@define
class Halt:
    scope: List[str] | Set[str] | Tuple[str] = field(default=None, converter=_normalize_scope)
    name: str = field(default='halt')

    def to_dict(self) -> Dict:
        instr_dict = {'name': self.name}
        if self.scope is not None:
            instr_dict['scope'] = self.scope
        return instr_dict

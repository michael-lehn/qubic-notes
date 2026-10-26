"""Physical processor cores, and the mapping from QD objects (qubits, channels) to them.

QubiC's core identity, as verified in vendor/distributed_processor/python/distproc:

- Each output channel is configured by hwconfig.ChannelConfig (hwconfig.py:109-149):
  core_ind, elem_ind, elem_type, elem_params, core_name (default None), board_name
  (default ''), and templates for its waveform/result memory names.
- A core's program is written to the instruction memory '{core_name}_command{core_ind}',
  or 'command{core_ind}' when core_name is '' or None, on board board_name
  (assembler.py:453-459; Executable keys memories as 'board:name', executable.py:15).
- SingleCoreAssembler requires every channel of one core program to share core_ind,
  core_name and board_name (assembler.py:95-108).

A physical core is therefore identified by (board_name, core_name, core_ind). core_name
is a core *type*: many cores share it. None and '' name the same core (same instruction
memory); a configuration that spells one core both ways is rejected, because QubiC's
assembler would treat the two spellings as different cores.

QubiC itself validates none of this when loading a configuration, and its grouping helper
proc_grouping_from_channelconfig keys cores by string concatenation (compiler.py:303), which
can merge distinct cores. QD therefore validates the configuration here and builds the
processor grouping from CoreId tuples.

QD names for cores (used by `place`):

    BOARD.coreN          the core with core_ind N on BOARD
    BOARD.TYPE.coreN     the same, naming its core type (core_name); required when
                         several core types on BOARD have core_ind N

BOARD is the configuration's board_name. Channels without board_name are on the board
QubiC leaves unnamed (''); QD calls it 'board0'. A board_name that is not a QD
identifier, or 'board0' in a configuration that also has unnamed channels, cannot be
written in QD.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

import distproc.ir.ir as qir

N_ELEMENTS = 4      # cfg[1:0] selects the element (gateware/top/src/dsp_coregen.py:183);
                    # rf_mix uses cfg bit 2 for save_result (software/qubic/rfsoc/hwconfig.py:375-379)
MEMORY_KINDS = ('env_mem_name', 'freq_mem_name', 'acc_mem_name')
REQUIRED = {'core_ind': int, 'elem_ind': int, 'elem_type': str, 'elem_params': dict}
OPTIONAL = {'core_name': (str, type(None)), 'board_name': str,
            'env_mem_name': (str, type(None)), 'freq_mem_name': (str, type(None)),
            'acc_mem_name': (str, type(None))}
UNNAMED_BOARD = 'board0'                        # QD name of board_name ''
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_CORE = re.compile(r'core(0|[1-9][0-9]*)')


@dataclass(frozen=True, order=True)
class CoreId:
    """One physical distributed-processor core."""
    board_name: str
    core_name: str          # core type; '' when the configuration gives none
    core_ind: int

    def __str__(self) -> str:
        name = f'{self.core_name or "core"}/{self.core_ind}'
        return f'{self.board_name}:{name}' if self.board_name else name

    @property
    def instr_mem(self) -> tuple[str, str]:
        """(board, memory) receiving this core's program, as the assembler names it."""
        name = f'{self.core_name}_command{self.core_ind}' if self.core_name else f'command{self.core_ind}'
        return (self.board_name, name)


class PlacementError(Exception):
    """A QD core name does not denote exactly one configured core."""

    def __init__(self, msg: str, hint: str | None = None):
        super().__init__(msg)
        self.msg, self.hint = msg, hint


class ConfigError(Exception):
    """The channel configuration is malformed or ambiguous."""

    def __init__(self, path: str, problems: list[str]):
        super().__init__('\n'.join(problems))
        self.path = path
        self.problems = problems

    def __str__(self) -> str:
        return '\n'.join(f'{self.path}: error: {p}' for p in self.problems)


class _ConfigQubitScoper(qir.QubitScoper):
    """QubiC qubit -> channels mapping taken from the channel configuration.

    QubiC's default (QubitScoperFromTup) derives channels from the name pattern
    '{qubit}.qdrv/.rdrv/.rdlo' instead. Names that are not qubits are channels and map to
    themselves, as with QubiC's default."""

    def __init__(self, qubit_channels: dict[str, tuple[str, ...]]):
        super().__init__()
        self._map = qubit_channels

    def get_scope(self, qubits) -> set[str]:
        if isinstance(qubits, str):
            qubits = [qubits]
        scope = set()
        for q in qubits:
            scope |= set(self._map.get(q, (q,)))
        return scope


@dataclass
class CoreModel:
    """Channels, qubits and physical cores of one hardware configuration.

    User-level objects are qubits ('Q0') and channels ('Q0.qdrv'); a channel belongs to the
    qubit named before its first '.'. C(o) = cores_of(o)."""
    channel_core: dict[str, CoreId]
    core_channels: dict[CoreId, tuple[str, ...]]
    qubit_channels: dict[str, tuple[str, ...]]
    notes: list[str] = field(default_factory=list)
    measuring: frozenset[str] = frozenset()                     # rf_mix (readout) channels
    fproc_board_problem: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------ queries
    @property
    def cores(self) -> tuple[CoreId, ...]:
        return tuple(self.core_channels)

    def is_channel(self, name: str) -> bool:
        return name in self.channel_core

    def is_qubit(self, name: str) -> bool:
        return name in self.qubit_channels

    def core_of_channel(self, channel: str) -> CoreId:
        return self.channel_core[channel]

    def channels_of_core(self, core: CoreId) -> tuple[str, ...]:
        return self.core_channels[core]

    def channels_of_qubit(self, qubit: str) -> tuple[str, ...]:
        return self.qubit_channels[qubit]

    def qubits_of_core(self, core: CoreId) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_qubit_of(c) for c in self.core_channels[core] if _qubit_of(c)))

    def cores_of(self, *objects: str) -> frozenset[CoreId]:
        """C(o1, ..., on): the cores of every channel of every object."""
        cores = set()
        for o in objects:
            if o in self.channel_core:
                cores.add(self.channel_core[o])
            elif o in self.qubit_channels:
                cores |= {self.channel_core[c] for c in self.qubit_channels[o]}
            else:
                raise KeyError(f"'{o}' is neither a configured qubit nor a configured channel")
        return frozenset(cores)

    def proc_grouping(self) -> list[tuple[str, ...]]:
        """QubiC proc_grouping: one tuple of channel names per physical core."""
        return [chans for chans in self.core_channels.values()]

    def qubit_scoper(self) -> qir.QubitScoper:
        return _ConfigQubitScoper(self.qubit_channels)

    # ------------------------------------------------------------ QD core names
    def boards(self) -> dict[str, str]:
        """QD board name -> board_name, for every board that QD can name."""
        names = {c.board_name for c in self.core_channels}
        out = {}
        for b in sorted(names):
            qd = b or UNNAMED_BOARD
            if _IDENT.fullmatch(qd) and not (b == UNNAMED_BOARD and '' in names):
                out[qd] = b
        return out

    def core_label(self, core: CoreId) -> str:
        """The QD name of a core: BOARD.coreN, or BOARD.TYPE.coreN if coreN is ambiguous."""
        board = core.board_name or UNNAMED_BOARD
        same_ind = [c for c in self.core_channels if c.board_name == core.board_name and c.core_ind == core.core_ind]
        if len(same_ind) > 1 and core.core_name:
            return f'{board}.{core.core_name}.core{core.core_ind}'
        return f'{board}.core{core.core_ind}'

    def resolve_core(self, board: str, core: str, core_type: str | None = None) -> CoreId:
        """The core named BOARD.coreN or BOARD.TYPE.coreN. Raises PlacementError."""
        boards = self.boards()
        if board not in boards:
            hint = None
            if board == UNNAMED_BOARD and UNNAMED_BOARD in {c.board_name for c in self.core_channels}:
                hint = (f"the configuration has unnamed channels and a board named '{UNNAMED_BOARD}'; "
                        f"QD cannot tell them apart")
            raise PlacementError(f"no board '{board}' in the channel configuration",
                                 hint or 'boards: ' + (', '.join(boards) or 'none that QD can name'))
        bname = boards[board]
        on_board = sorted(c for c in self.core_channels if c.board_name == bname)
        known = ', '.join(dict.fromkeys(self.core_label(c) for c in on_board))
        m = _CORE.fullmatch(core)
        if not m:
            raise PlacementError(f"'{core}' is not a core name; cores are written coreN (N = core_ind)",
                                 f'cores on {board}: {known}')
        ind = int(m.group(1))
        cands = [c for c in on_board if c.core_ind == ind and (core_type is None or c.core_name == core_type)]
        what = f'{board}.{core_type}.{core}' if core_type else f'{board}.{core}'
        if not cands:
            raise PlacementError(f"no core {what} in the channel configuration", f'cores on {board}: {known}')
        if len(cands) > 1:
            raise PlacementError(f'{what} is ambiguous: core types '
                                 f"{', '.join(repr(c.core_name) for c in cands)} all have core_ind {ind}",
                                 'write ' + ' or '.join(self.core_label(c) for c in cands))
        return cands[0]

    def fproc_problem(self, qubit: str, readers: frozenset[CoreId] = frozenset()) -> str | None:
        """Why measurement feedback on this qubit, read by these cores, could address the wrong
        result, or None.

        QubiC addresses the result of 'Qn.meas' by the core_ind of 'Qn.rdlo'
        (distproc/hwconfig.py:101-103). The gateware numbers results per board, over the
        rf_mix generators of each core type in turn (gateware/top/src/dsp_build.py:437-452).
        The two agree only if one core type measures on that board, with one rf_mix channel
        per core, and every reading core is on that board (each board has its own FPROC)."""
        rdlo = f'{qubit}.rdlo'
        if rdlo not in self.channel_core:
            return f"{qubit} has no configured '{rdlo}' channel to measure with"
        if rdlo not in self.measuring:
            return f"'{rdlo}' is not an rf_mix channel, so it delivers no result to FPROC"
        core = self.channel_core[rdlo]
        if core.board_name in self.fproc_board_problem:
            return self.fproc_board_problem[core.board_name]
        away = sorted(c for c in readers if c.board_name != core.board_name)
        if away:
            return (f"{qubit} is measured on board '{core.board_name}', but {', '.join(map(str, away))} "
                    f'would read the FPROC of another board')
        return None

    # ------------------------------------------------------------ construction
    @classmethod
    def from_config(cls, raw, path: str = '<channel config>') -> CoreModel:
        """Build and validate the model from a raw (JSON-decoded) channel configuration."""
        problems: list[str] = []
        if not isinstance(raw, dict):
            raise ConfigError(path, ['the channel configuration must be a JSON object'])
        clk = raw.get('fpga_clk_freq')
        if isinstance(clk, bool) or not isinstance(clk, (int, float)):
            problems.append("missing or non-numeric 'fpga_clk_freq' (required by distproc/hwconfig.py:157)")

        channels = {}
        for name, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            ok = True
            for key, typ in REQUIRED.items():
                if key not in cfg:
                    problems.append(f"channel '{name}': missing '{key}'")
                    ok = False
                elif isinstance(cfg[key], bool) or not isinstance(cfg[key], typ):
                    problems.append(f"channel '{name}': '{key}' must be {typ.__name__}, got {cfg[key]!r}")
                    ok = False
            for key, typ in OPTIONAL.items():
                if key in cfg and not isinstance(cfg[key], typ):
                    problems.append(f"channel '{name}': '{key}' has invalid value {cfg[key]!r}")
                    ok = False
            unknown = sorted(set(cfg) - set(REQUIRED) - set(OPTIONAL))
            if unknown:
                problems.append(f"channel '{name}': unknown field(s) {', '.join(unknown)} "
                                '(hwconfig.ChannelConfig would reject them)')
                ok = False
            if ok and cfg['core_ind'] < 0:
                problems.append(f"channel '{name}': negative core_ind {cfg['core_ind']}")
                ok = False
            if ok:
                channels[name] = cfg
        if problems:
            raise ConfigError(path, problems)

        channel_core: dict[str, CoreId] = {}
        spellings: dict[CoreId, set] = defaultdict(set)
        for name, cfg in channels.items():
            core = CoreId(cfg.get('board_name', ''), cfg.get('core_name') or '', cfg['core_ind'])
            channel_core[name] = core
            spellings[core].add(cfg.get('core_name'))
        for core, names in spellings.items():
            if None in names and '' in names:
                problems.append(f'core {core}: core_name is given both as null and as "" — the instruction '
                                f'memory is the same, but the assembler treats them as two cores '
                                f'(distproc/assembler.py:100-103); use one spelling')

        core_channels: dict[CoreId, list[str]] = defaultdict(list)
        for name, core in channel_core.items():
            core_channels[core].append(name)

        # memory names, formatted exactly as ChannelConfig does (hwconfig.py:135-149)
        mems: dict[str, dict[str, str]] = {}
        for name, cfg in channels.items():
            mems[name] = {}
            for kind in MEMORY_KINDS:
                if cfg.get(kind) is None:
                    continue
                try:
                    mems[name][kind] = cfg[kind].format(core_ind=cfg['core_ind'], core_name=cfg.get('core_name'))
                except (KeyError, IndexError, ValueError) as e:
                    problems.append(f"channel '{name}': cannot format {kind} {cfg[kind]!r}: {e!r}")

        # element index: unique per core, unless the channels are aliases of one element
        # (same type and memories), and decodable by the signal-generator glue
        notes = []
        element: dict[str, tuple] = {}
        for core, chans in core_channels.items():
            by_elem = defaultdict(list)
            for c in chans:
                by_elem[channels[c]['elem_ind']].append(c)
                element[c] = (core, channels[c]['elem_ind'])
            for elem, cs in sorted(by_elem.items()):
                if len({(channels[c]['elem_type'], tuple(sorted(mems[c].items()))) for c in cs}) > 1:
                    problems.append(f'core {core}: channels {", ".join(cs)} share elem_ind {elem} '
                                    f'but differ in elem_type or memories')
                elif len(cs) > 1:
                    notes.append(f'core {core}: {", ".join(cs)} are aliases of element {elem}; '
                                 f'one program may use only one of them (executable.py:71-72)')
                if not 0 <= elem < N_ELEMENTS:
                    problems.append(f'core {core}: elem_ind {elem} of {", ".join(cs)} is outside 0..{N_ELEMENTS - 1}: '
                                    f'the gateware selects elements with cfg[1:0] '
                                    f'(gateware/top/src/dsp_coregen.py:183), and rf_mix channels use cfg '
                                    f'bit 2 for save_result')

        # instruction memories: one per physical core
        instr = defaultdict(list)
        for core in core_channels:
            instr[core.instr_mem].append(core)
        for (board, mem), cores in instr.items():
            if len(cores) > 1:
                problems.append(f"cores {', '.join(map(str, cores))} would all be programmed through "
                                f"instruction memory '{board}:{mem}'")

        # waveform and result memories: one element each
        writers = defaultdict(list)
        for name, cfg in channels.items():
            for kind, mem in mems[name].items():
                writers[(cfg.get('board_name', ''), mem)].append((element[name], f'{name}.{kind}'))
        for (board, mem), uses in sorted(writers.items()):
            users = [u for _, u in uses]
            if len({e for e, _ in uses}) > 1:
                problems.append(f"memory '{board}:{mem}' is used by {', '.join(users)} "
                                '(the assembler would fail with "already exists", executable.py:71-72)')

        if problems:
            raise ConfigError(path, problems)

        model = cls(channel_core, {k: tuple(v) for k, v in core_channels.items()}, {}, notes)
        qubit_channels: dict[str, list[str]] = defaultdict(list)
        for name in channel_core:
            q = _qubit_of(name)
            if q:
                qubit_channels[q].append(name)
            else:
                model.notes.append(f"channel '{name}' has no qubit prefix; it is usable only by channel name")
        model.qubit_channels = {q: tuple(cs) for q, cs in qubit_channels.items()}

        # non-fatal: QubiC's own helper would merge these cores (QD does not use it)
        keys = defaultdict(set)
        for core in model.core_channels:
            keys[core.board_name + core.core_name + str(core.core_ind)].add(core)
        for key, cores in sorted(keys.items()):
            if len(cores) > 1:
                model.notes.append(f"distproc.compiler.proc_grouping_from_channelconfig would merge cores "
                                   f"{', '.join(map(str, sorted(cores)))} (key '{key}'); QD groups by CoreId")
        # FPROC: where core_ind is not the gateware's result index (see fproc_problem)
        model.measuring = frozenset(n for n, cfg in channels.items() if cfg['elem_type'] == 'rf_mix')
        per_board = defaultdict(lambda: defaultdict(set))           # board -> core -> rf_mix elements
        for name in model.measuring:
            core, elem = element[name]
            per_board[core.board_name][core].add(elem)
        for board, cores in sorted(per_board.items()):
            types = sorted({c.core_name for c in cores})
            multi = sorted(str(c) for c, elems in cores.items() if len(elems) > 1)
            if len(types) > 1:
                why = f"core types {', '.join(repr(t) for t in types)} all measure"
            elif multi:
                why = f"core(s) {', '.join(multi)} have more than one rf_mix element"
            else:
                continue
            model.fproc_board_problem[board] = (
                f"on board '{board}', {why}: the gateware then numbers results differently from the "
                f'core_ind that QubiC uses as FPROC address (gateware/top/src/dsp_build.py:437-452, '
                f'distproc/hwconfig.py:101-103)')
            model.notes.append(f'measurement feedback is unavailable: {model.fproc_board_problem[board]}')
        return model


def _qubit_of(channel: str) -> str | None:
    return channel.split('.', 1)[0] if '.' in channel else None

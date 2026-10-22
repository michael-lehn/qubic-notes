"""What the front end needs to know about the machine: calibrations and hardware limits."""
from __future__ import annotations

import inspect
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import distproc.compiler  # noqa: F401  (loads importlib.metadata, which qubitconfig needs)
import distproc.hwconfig as dhw
import qubitconfig.qchip as qc
import qubitconfig.envelope_pulse as envelope_pulse

QUBIC_ROOT = os.environ.get('QUBIC_ROOT', str(Path(__file__).resolve().parents[1] / 'vendor'))
DEFAULT_QCHIP = f'{QUBIC_ROOT}/software/examples/qubitcfg.json'
DEFAULT_CHANNELS = f'{QUBIC_ROOT}/software/examples/channel_config.json'

N_REGS = 16                 # distproc/assembler.py:60, hdl/reg_file.v
INSTR_MEM_WORDS = 8192      # gateware/top/zcu216_14_2/dsp_config.yaml:50
CHANNELS = ('qdrv', 'rdrv', 'rdlo')
DEFAULT_FREQ = {'qdrv': 'freq', 'rdrv': 'readfreq', 'rdlo': 'readfreq'}


@dataclass
class Target:
    qchip_path: str = DEFAULT_QCHIP
    channels_path: str = DEFAULT_CHANNELS
    fpga: dhw.FPGAConfig = field(default_factory=dhw.FPGAConfig)

    def __post_init__(self):
        self.qchip = qc.QChip(self.qchip_path)
        self.channel_configs = dhw.load_channel_configs(self.channels_path)
        self._vz_cache: dict[str, bool] = {}
        self.envelopes = {
            name: [p for p in inspect.signature(fn).parameters if p not in ('twidth', 'dt')]
            for name, fn in inspect.getmembers(envelope_pulse, inspect.isfunction)
            if {'twidth', 'dt'} <= set(inspect.signature(fn).parameters)}

    def has_qubit(self, q: str) -> bool:
        return q in self.qchip.qubits and f'{q}.qdrv' in self.channel_configs

    def qubit_attrs(self, q: str) -> list[str]:
        return [a for a in vars(self.qchip.qubits[q]) if not a.startswith('_')]

    def has_gate(self, name: str, qubits: list[str]) -> bool:
        return ''.join(qubits) + name in self.qchip.gates

    def gate_has_virtual_z(self, name: str, qubits: list[str]) -> bool:
        key = ''.join(qubits) + name
        if key not in self._vz_cache:
            gate = self.qchip.gates[key].get_updated_copy({})
            gate.dereference()
            self._vz_cache[key] = any(isinstance(p, qc.VirtualZ) for p in gate.get_pulses())
        return self._vz_cache[key]

    def gates_for(self, qubits: list[str]) -> list[str]:
        prefix = ''.join(qubits)
        return sorted(g[len(prefix):] for g in self.qchip.gates
                      if g.startswith(prefix) and not re.match(r'Q\d', g[len(prefix):]))

    def core_of(self, q: str) -> int:
        return self.channel_configs[f'{q}.qdrv'].core_ind

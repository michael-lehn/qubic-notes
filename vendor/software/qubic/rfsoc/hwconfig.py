import inspect
import logging
import json
from typing import Dict, List, Tuple

from distproc.hwconfig import ChannelConfig, ElementConfig, \
    FPGAConfig, load_channel_configs
import distproc.command_gen as cg
from typing import List, Dict

try:
    import ipdb
except ImportError:
    pass
import numpy as np


def elemconfig_classfactory(elem_type):
    if elem_type.lower() == 'dc':
        return DCOffsetCfg
    elif elem_type.lower() == 'rf':
        return RFSoCElementCfg
    elif elem_type.lower() == 'rf_mix':
        return RFMixElementCfg


class DCOffsetCfg(ElementConfig):
    """
    ElementConfig implementation for DC offset channels 
    (i.e. no amplitude modulation envelope)
    """
    def __init__(self):
        super().__init__(2.e-9, 0)

    @property
    def has_env(self):
        return False

    @property
    def has_freq(self):
        return False

    def add_env(self, env):
        if env is not None:
            if isinstance(env, np.ndarray) or env != 0:
                raise Exception('cannot add envelope to DC offset channel!')

    def add_freq(self, freq, freq_ind=None):
        if freq is not None and freq != 0:
            raise Exception('cannot add frequency to DC offset channel!')

    def compile_envs(self) -> bytes | Dict:
        return None, {None: 0, 0: 0}

    def compile_freqs(self) -> bytes | Dict:
        return None, {None: 0, 0: 0}

    def get_cfg_word(self, elem_ind: int, mode_bits: int = None) -> int:
        if mode_bits is not None:
            raise Exception('mode not implemented')
        return elem_ind


class RFSoCElementCfg(ElementConfig):
    """
    ElementConfig implementation for RF sig gens on QubiC 2.0 on ZCU216.
    """

    def __init__(self, samples_per_clk: int = 16, interp_ratio: int = 1):
        self.env_n_bits = 16
        self.freq_n_bits = 32
        self.interp_ratio = interp_ratio
        self._env_dict = {}
        self._freq_list = []
        super().__init__(2.e-9, samples_per_clk)

    @property
    def has_env(self):
        return True

    @property
    def has_freq(self):
        return True

    def add_env(self, env: np.ndarray | Dict | str):
        """
        Adds a new envelope to the envelope buffer. This involves hashing the provided 
        envelope, checking if it has already been registered, then adding it to the 
        envelope library. 

        Parameters
        ----------
        env: np.ndarray | Dict
            If `np.ndarray`, assumed to be a time-domain list of samples
            If `Dict`, assumed to specify an envelope function in the pulse library
            Can be `str` to specify the `'cw'` key

        Returns
        -------
        str
            Hash of the provided envelope, corresponding to the key in the 
            env dict.
        """
        if isinstance(env, np.ndarray):
            if np.any((np.abs(np.real(env)) > 1) | (np.abs(np.imag(env)) > 1)):
                raise Exception('env must be < 1')
            envkey = _hash_env(self._get_env_buffer(env))
            if envkey not in self._env_dict:
                self._env_dict[envkey] = env
        elif isinstance(env, dict):
            envkey = _hash_env(self._get_env_buffer(env))
            if envkey not in self._env_dict:
                self._env_dict[envkey] = env
        elif isinstance(env, str):
            envkey = env
            if envkey not in self._env_dict:
                if envkey == 'cw':
                    self._env_dict[envkey] = 'cw'
                else:
                    raise Exception(f'Envelope not found: {envkey}')
        else:
            raise Exception('env must be string, dict, or np array')

        return envkey

    def freq_registered(self, freq) -> bool:
        """
        Checks if the provided `freq` has been added to the frequency list.
        freq: float
            frequency in Hz
        """
        if freq in self._freq_list:
            return True
        else: 
            return False

    def add_freq(self, freq: float, freq_ind: int = None) -> None:
        """
        Registers a new frequency for this sig gen (i.e. adds it to the freq buffer).

        Parameters
        ----------
        freq: float
            frequency in Hz
        freq_ind: int
            optional frequency index (useful for on-the-fly parameterization)
        """
        if not self.freq_registered(freq):
            if freq_ind is None:
                self._freq_list.append(freq)
            elif freq_ind >= len(self._freq_list):
                for i in range(len(self._freq_list) - freq_ind):
                    self._freq_list.append(None)
                self._freq_list.append(freq)
            else:
                if self._freq_list[freq_ind] is None:
                    raise ValueError('ind {} is already occupied!'.format(freq_ind))
                self._freq_list[freq_ind] = freq

    def compile_envs(self) -> Tuple[bytes, Dict]:
        """
        Computes the raw envelope buffer along with a dictionary of indices. Address
        is computed later by hwconfig

        Returns
        -------
        env_raw : bytes 
            packed byte array of the raw envelope buffer. Each sample is a 
            32-bit word, with a signed 16-bit I value LSB followed by
            a signed 16-bit Q value MSB
        env_addr_map : dict
            dictionary of envelope addresses, to be used by pulse commands.
            Keys are the same as used by self._env_dict.
            The process element hardware module (element.v) has four separate
            memory banks for the envelope, with one output value per-clock 
            (so 4x250 MHz = 1 GHz). Addresses index these buffers, so 
            the address here is the envelope start index in env_raw divided
            by four.
        """
        cur_env_ind = 0
        env_word_map = {}

        env_raw = np.empty(0).astype(np.uint32)

        for envkey, env in self._env_dict.items():
            env = self._get_env_buffer(env)
            if envkey == 'cw':
                env_word_map[envkey] = self.get_cw_env_word(cur_env_ind)
            else:
                env_word_map[envkey] = self.get_env_word(cur_env_ind, len(env))
            cur_env_ind += len(env)
            env_raw = np.append(env_raw, env)

        return env_raw.astype(np.uint32).tobytes(), env_word_map

    def compile_freqs(self) -> Tuple[bytes, Dict[float, int]]:
        """
        Converts the list of frequencies to a buffer, where each frequency 
        has 16 elements:

          - `[0]` is a 32-bit freq word, encoding phase increment per clock cycle
          - `[1:15]` are 16 bit I MSB + 16 bit Q LSB, encoding 15 phase offsets for 
                each sample (except 0) within a clock cycle

        16-element arrays for each frequency are concatenated into a single 1D numpy array.
        Returns the full raw freq buffer + index map

        Returns
        -------
        bytes:
            Frequency buffer: packed array of concatenated 16-element frequency lists
        Dict[float, int]:
            Dictionary mapping the frequency in Hz to its location in the freq buffer
        """
        freq_buffer = self._get_freq_buffer(self._freq_list)
        freq_ind_map = {f: self._freq_list.index(f) for f in self._freq_list}
        return freq_buffer, freq_ind_map

    def get_cfg_word(self, elem_ind: int, mode_bits: int = None) -> int:
        if mode_bits is not None:
            raise Exception('mode not implemented')
        return elem_ind

    def _get_freq_buffer(self, freqs: list | np.ndarray) -> bytes:
        """
        Converts a list of frequencies (in Hz) to a buffer, where each frequency 
        has 16 elements:

          - `[0]` is a 32-bit freq word, encoding phase increment per clock cycle
          - `[1:15]` are 16 bit I MSB + 16 bit Q LSB, encoding 15 phase offsets for 
                each sample (except 0) within a clock cycle
        16-element arrays for each frequency are concatenated into a single 1D numpy array.

        Parameters
        ----------
        freqs: list | np.ndarray
            List of frequencies, in Hz

        Returns
        -------
        bytes:
            Frequency buffer: packed array of concatenated 16-element frequency lists
        """
        freq_buffer = np.empty(0, dtype=np.uint32)
        scale = 2 ** (self.freq_n_bits / 2 - 1) - 1
        for freq in freqs:
            cur_freq_buffer = np.zeros(self.samples_per_clk)
            if freq is not None:
                cur_freq_buffer[0] = int(freq * 2 ** self.freq_n_bits / self.fpga_clk_freq) & (
                        2 ** self.freq_n_bits - 1)
                for i in range(1, self.samples_per_clk):
                    i_mult = int(round(np.cos(2 * np.pi * freq * i * self.sample_period) * scale) % (
                            2 ** (self.freq_n_bits / 2)))
                    q_mult = int(round(np.sin(2 * np.pi * freq * i * self.sample_period) * scale) % (
                            2 ** (self.freq_n_bits / 2)))
                    cur_freq_buffer[i] = (i_mult << (self.freq_n_bits // 2)) + q_mult

            freq_buffer = np.append(freq_buffer, cur_freq_buffer)

        return freq_buffer.astype(np.uint32).tobytes()

    def get_env_word(self, env_ind: int, length_nsamples: int) -> int:
        """
        Returns the envelope word stored in the pulse command, which encodes the
        starting address and length of the pulse envelope.

        Parameters
        ----------
        env_ind: int
            starting index of the envelope in the envelope buffer
        length_nsamples: int
            length of the envelope in samples (could be the same as the
            pulse length in samples, or lower if interpolating). Note that
            this is the length in _envelope_ samples, not DAC samples.
        Returns
        -------
        int:
            env_word
        """
        return int(np.ceil(env_ind / int(self.samples_per_clk / self.interp_ratio))) \
            + (int(np.ceil(self.interp_ratio * length_nsamples / self.samples_per_clk)) << 12)

    def get_cw_env_word(self, env_ind: int) -> int:
        """
        Returns the envelope word for a CW pulse. `env_ind` is required 
        since the CW pulse requires a single clock cycle of envelope
        data to be stored.

        Parameters
        ----------
        env_ind: int
            starting index of the envelope in the envelope buffer
        Returns
        -------
        int:
            env_word
        """
        return int(np.ceil(env_ind / int(self.samples_per_clk / self.interp_ratio)))

    def _get_env_buffer(self, env: np.ndarray | list | dict):
        """
        Converts env to a list of samples to write to the env buffer memory.

        Parameters
        ----------
        env : np.ndarray, list, or dict
            if np.ndarray or list this is interpreted as a list of samples. Samples
            should be normalized to 1.

            if dict, a function in the qubitconfig.envelope_pulse library is used to
            calculate the envelope samples. env['env_func'] should be the name of the function,
            and env['paradict'] is a dictionary of attributes to pass to env_func. The 
            set of attributes varies according to the function but should include the 
            pulse duration twidth

        Returns
        -------
        np.ndarray:
            buffer of envelope data

        """
        if isinstance(env, np.ndarray) or isinstance(env, list):
            env_samples = np.asarray(env)
        elif isinstance(env, dict):
            dt = self.interp_ratio * self.sample_period

            if isinstance(env['env_func'], str):
                from qubic.pulse_factory import PulseShapeFactory
                pulse_shape_factory = PulseShapeFactory()
                env_func = pulse_shape_factory.get_pulse_shape_function(env['env_func'])
            else:
                raise TypeError('env_func must be a string')

            _, env_samples = env_func(dt=dt, **env['paradict'])
        elif env == 'cw':
            env_samples = np.ones(self.samples_per_clk // self.interp_ratio)
        else:
            raise TypeError(f'env {env} must be dict or array')

        env_samples = np.pad(env_samples, (0, (self.samples_per_clk // self.interp_ratio - len(env_samples) 
                                               % (self.samples_per_clk // self.interp_ratio)) 
                                           % (self.samples_per_clk // self.interp_ratio)))

        return (cg.twos_complement(np.real(env_samples * (2 ** (self.env_n_bits - 1) - 1)).astype(int),
                                   nbits=self.env_n_bits) << self.env_n_bits) \
            + cg.twos_complement(np.imag(env_samples * (2 ** (self.env_n_bits - 1) - 1)).astype(int),
                                 nbits=self.env_n_bits)

    def length_nclks(self, tlength: float) -> int:
        """
        Converts pulse length in seconds to integer number of clock cycles.

        Parameters
        ----------
        tlength: float
            time in seconds

        Returns
        -------
        int:
            time in clocks
        """
        return int(np.ceil(tlength / self.fpga_clk_period))

class RFMixElementCfg(RFSoCElementCfg):
    """
    Override RFSoCElementCfg for rdlo/downconversion channels. Currently the 
    only difference is a `save_result` switch is supported for the `cfg_word` 
    parameter.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_cfg_word(self, elem_ind: int, save_result: bool = True) -> int:
        if save_result is None:
            save_result = True
        return elem_ind + (int(save_result) << 2)


def _hash_env(env):
    if isinstance(env, np.ndarray):
        return str(hash(env.astype(np.uint32).tobytes()))
    raise Exception('{} not supported!'.format(type(env)))


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        # If the object is callable (like a function), return its name
        if callable(obj):
            return obj.__name__

        # If the object is not serializable, let the base class raise the TypeError
        return json.JSONEncoder.default(self, obj)


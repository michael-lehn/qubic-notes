import numpy as np
from pynq import Overlay
import xrfclk
import xrfdc
import json
import time
import os
import glob
import logging
from qubic.rfsoc.bram import BramCfgs, vsign32, get_value16
from distproc.executable import Executable, ResultChannel
from qubic.results.primitives import get_result_class
from typing import List, Dict, Tuple

POLL_INTERVAL = 0.001
DAC_NYQUIST_DEFAULT = 2

def vector(val):
    if isinstance(val,list) or isinstance(val,tuple) or isinstance(val, np.ndarray):
        vout = val
    else:
        vout = np.array([val])
    return vout

class PLInterface:
    """
    This class is a low level interface to RFSoC PL, and is intended to be run on the RFSoC 
    ZYNQ ARM core, configured with pyq 3.0. Uses a pynq overlay for PS-PL communication.
    """
    def __init__(self, 
                 commit_hash: str,
                 dac_current_values: Dict[tuple, int] = None,
                 dac_nyquist_zone: Dict[tuple, int] = None,
                 adc_nyquist_zone: int = 1,
                 lmk_freq: float = 500.18,
                 load_xsa: bool = True):
        """
        Parameters
        ----------
        commit_hash : str
            first 6 digits of gateware commit hash used to compile
            the XSA to load. xsa files (along with bram and reg json files)
            should be in rfsoc/bits/commit_hash.
        """
        commit_dir = os.path.join(os.path.dirname(__file__), 'bits', commit_hash)
        self.bram_cfgs = BramCfgs(os.path.join(commit_dir, 'bram.json'))
        with open(os.path.join(commit_dir, 'cfgregs.json')) as bjfp:
            self.cfgregs_cfg = json.load(bjfp)
        with open(os.path.join(commit_dir, 'dspregs.json')) as jfp:
            self.dspregs_cfg = json.load(jfp)
        with open(os.path.join(commit_dir, 'rfdc.json')) as fjson:
            self.rfdc_cfg = json.load(fjson)
        self.overlay = None
        self.fmem = {}
        self.nproc = len([name for name in self.bram_cfgs.keys() if name[:7] == 'command'])
        self.commit_dir = commit_dir

        self.refclks(lmk_freq=lmk_freq)
        logging.getLogger(__name__).info(f'loading bitfile: {commit_hash}')
        self.load_overlay(download=load_xsa)
        logging.getLogger(__name__).info(f'mts: {self.mts()}')

        if dac_nyquist_zone is None:
            dac_nyquist_zone = {'default': 2}
        for tile, block in self.rfdc_cfg['dactilechan']:
            if (tile, block) in dac_nyquist_zone.keys():
                self.dacnyquist(tile, block, dac_nyquist_zone[(tile, block)])
            else:
                self.dacnyquist(tile, block, dac_nyquist_zone['default'])

        self.adcnyquist(adc_nyquist_zone)

        if dac_current_values is not None:
            for tileblock, current in dac_current_values.items():
                self.dacvop(tileblock[0], tileblock[1], current)

        if 'use_sync' in self.dspregs_cfg:
            self.write_reg('use_sync', 0)

        self.write_reg('dspreset', 0)
        self.write_reg("mixbb1sel", 0)
        self.write_reg("mixbb2sel", 0)
        self.write_reg("shift", 12)

    def config_mts(self,
                   dactiles: int = 0xf,
                   adctiles: int = 0xf,
                   daclatency: int = -1,
                   adclatency: int = -1) -> None:
    # Set which RF tiles use MTS and turn MTS off
        self.rfdc.mts_dac_config.RefTile = 2  # tile 0 is the main reference - refer to restrictions
        self.rfdc.mts_adc_config.RefTile = 2
        self.rfdc.mts_dac_config.Target_Latency = daclatency
        self.rfdc.mts_adc_config.Target_Latency = adclatency
        self.rfdc.mts_dac_config.Tiles = 0xf #bitmask over tiles
        self.rfdc.mts_adc_config.Tiles = 0xf
        self.rfdc.mts_dac_config.SysRef_Enable = 1
        self.rfdc.mts_adc_config.SysRef_Enable = 1

    def mts(self, daclatency: int = 260, adclatency: int = 60):
        self.config_mts()
        self.rfdc.mts_dac()
        self.rfdc.mts_adc()
        dacmeaslatency=np.array([self.rfdc.mts_dac_config.Latency[i] for i in range(4)])
        adcmeaslatency=np.array([self.rfdc.mts_adc_config.Latency[i] for i in range(4)])
        logging.getLogger(__name__).debug(f'dac mts before: {dacmeaslatency}')
        logging.getLogger(__name__).debug(f'adc mts before: {adcmeaslatency}')
        
        if ((all(dacmeaslatency-dacmeaslatency[0]==0) and dacmeaslatency[0]<=daclatency) 
                and (all(adcmeaslatency-adcmeaslatency[0]==0) and adcmeaslatency[0]<=adclatency)):
            self.config_mts(daclatency=daclatency,adclatency=adclatency)
            self.rfdc.mts_dac()
            self.rfdc.mts_adc()
            dacmeaslatency=np.array([self.rfdc.mts_dac_config.Latency[i] for i in range(4)])
            adcmeaslatency=np.array([self.rfdc.mts_adc_config.Latency[i] for i in range(4)])
            logging.getLogger(__name__).debug(f'dac mts after: {dacmeaslatency}')
            logging.getLogger(__name__).debug(f'adc mts after: {adcmeaslatency}')
        return 0 if all(dacmeaslatency==daclatency) and all(adcmeaslatency==adclatency) else 1

    def adcnyquist(self,n=1):
        """
        Set nyquist zone to use for ADC configuration
        """
        logging.getLogger(__name__).info(f'Setting ADC Nyquist zone to {n}')
        if self.overlay is not None:
            rfdc = self.overlay.rf_data_converter
            for tile,block in self.rfdc_cfg['adctilechan']:
                rfdc.adc_tiles[tile].blocks[block].NyquistZone = n

    def dacnyquist(self, tile: int, block: int, n: int = 2):
        """
        Set nyquist zone to use for DAC configuration
        """
        logging.getLogger(__name__).info(f'Setting DAC Nyquist zone to {n}'
                                         f' on block {block} tile {tile}.')
        rfdc = self.overlay.rf_data_converter
        rfdc.dac_tiles[tile].blocks[block].NyquistZone = n

    def dacvop(self, tile: int, block: int, uAcurr: int) -> None:
        """
        Set the max DAC current on the specified tile and block.
        default uAcurr is 20000

        Parameters
        ----------
        tile: int
            tile index (starts from 0)
        block: int
            block (channel) index
        uAcurr: int
            max current in uA
        """
        logging.getLogger(__name__).info(f'Setting DAC current to {uAcurr} uA'
                                         f' on block {block} tile {tile}.')
        self.rfdc.dac_tiles[tile].blocks[block].SetDACVOP(uAcurr)

    def load_overlay(self, xsafile: str = None, download: bool = True) -> None:
        """
        Load gateware into FPGA PL

        Parameters
        ----------
        xsafile: str
            name of XSA file to load. If None (default), searches for the XSA file 
            given by the commit hash passed into `__init__`.
        download: True
            If True, loads the bitstream into the PL
        """
        if xsafile is None:
            xsafile = glob.glob(os.path.join(self.commit_dir, 'psbd*.xsa'))[0]
        self.overlay = Overlay(xsafile, download=download)
        self.rfdc = self.overlay.rf_data_converter

    def refclks(self, lmk_freq, lmx_freq=None) -> None:
        if lmx_freq is None:
            xrfclk.set_ref_clks(lmk_freq=lmk_freq)
            logging.getLogger(__name__).info(f'Setting LMK freq to {lmk_freq}')
        else:
            xrfclk.set_ref_clks(lmk_freq=lmk_freq, lmx_freq=lmx_freq)
            logging.getLogger(__name__).info(f'Setting LMK freq to {lmk_freq}'
                                             f'LMX freq to {lmx_freq}')

    def read(self, name: str, start_addr: int = 0, stop_addr: int = None) -> int | np.ndarray:
        """
        Read value from register or memory

        Parameters
        ----------
        name : str
            name of entity to read from, referenced to names in
            bram.json, cfgregs.json, and dspregs.json
        start_addr : int
            if BRAM, starting address to read from relative to base address
        stop_addr : int
            if BRAM, last address to read from 

        Returns
        -------
        val : int or np array
            if bram, returns a numpy array
            if reg, returns int
        """
        if name in self.bram_cfgs.keys():
            if self.bram_cfgs[name].access != 'read':
                raise Exception('BRAM {} does not have read access!'.format(name))

            start_addr += self.bram_cfgs[name].address
            if stop_addr is None:
                stop_addr = self.bram_cfgs[name].length
            else:   
                if stop_addr > self.bram_cfgs[name].length:
                    raise Exception('Cannot read {} values from {} word \
                            memory'.format(stop_addr, self.bram_cfgs[name].length))
            stop_addr += self.bram_cfgs[name].address


            val = self.overlay.bramctrl.mmio.array[start_addr:stop_addr]
 
        elif name in self.dspregs_cfg.keys():
            val = self.overlay.dspregs.mmio.read(self.dspregs_cfg[name]['base_addr']*4)
 
        elif name in self.cfgregs_cfg.keys():

            val = self.overlay.cfgregs.mmio.read(self.cfgregs_cfg[name]['base_addr']*4)
        else:
            raise ValueError('could not find {}'.format(name))

        return val
    
    def set_default_regs(self):
        """
        Set dsp/cfg registers back to defaults.
        Currently checks for:
            `sd_sw` (reset to 0)
        """
        if 'sd_sw' in self.dspregs_cfg.keys() or 'sd_sw' in self.cfgregs_cfg.keys():
            self.write_reg('sd_sw', 0)

    def write_mem_buf(self, name: str, mem_vals: np.ndarray, start_addr: int = 0) -> None:
        """
        General function for BRAM writes.

        Parameters
        ----------
        name : str
            name of BRAM (referenced to bram.json)
        mem_vals : np.ndarray
            list of values to write
        start_addr : int
            start write addr relative to base_addr
        """
        #start_addr += self.bram_cfgs[name].address
        #self.overlay.bramctrl.mmio.array[start_addr : start_addr + len(mem_vals)] = mem_vals
        addr = start_addr
        dt = np.dtype(np.uint32)
        dt = dt.newbyteorder('little')
        mem_vals = np.frombuffer(mem_vals, dtype=dt)
        memIP = self.overlay.bramctrl.mmio
        if not self.bram_cfgs[name].access == 'write':
            raise RuntimeError('buffer {name} is readonly!')

        max_mem_val = 2**self.bram_cfgs[name].paradict['Awidth']
        if not np.all(mem_vals < max_mem_val):
            raise RuntimeError(f'memory buffer {name}: max word size of {max_mem_val} exceeded!')
        mem_addr = self.bram_cfgs[name].address
        if not(start_addr + len(mem_vals) <= self.bram_cfgs[name].length):
            raise RuntimeError(f'memory buffer {name}: max length of {self.bram_cfgs[name].length} exceeded!')
        for i, val in enumerate(mem_vals):
            memIP.write((mem_addr + addr)*4, int(val))
            addr += 1


    def write_reg(self, name: str, value: int):
        """
        General function for writing registers.

        Parameters
        ----------
        name : str
            name of reg to write
        value : int
            value to write
        """
        
        if name in self.cfgregs_cfg.keys():
            self.overlay.cfgregs.mmio.write(self.cfgregs_cfg[name]['base_addr']*4, int(value))
        elif name in self.dspregs_cfg.keys():
            self.overlay.dspregs.mmio.write(self.dspregs_cfg[name]['base_addr']*4, int(value))
        else:
            raise ValueError('register {} not found'.format(name))

    def start_program(self, nshots: int, clock_count=None):
        # TODO: add clock count stuff here
        self.write_reg('nshot', nshots)
        self.write_reg('dspreset', 0)
        self.write_reg("resetacc", 1)
        time.sleep(POLL_INTERVAL)
        self.write_reg("resetacc", 0)
        time.sleep(POLL_INTERVAL)
        self.write_reg('start', 0)

    def get_mem_size(self, mem_name) -> int:
        """
        size in 32-bit words
        """
        return self.bram_cfgs[mem_name].length

    def wait_and_readback(self, 
                          result_chans: Dict[str, ResultChannel],
                          nshots: int,
                          timeout_per_shot: float = 8):

        max_wait_iters = timeout_per_shot/POLL_INTERVAL
        wait_iters = 0
        shotcntlast = 0
        results = {}
        while self.read('lastshotdone') == 0:
            time.sleep(POLL_INTERVAL)
            procdone = self.read('procdone')
            shotcnt = self.read('shotcnt')
            nshot_reg = self.read('nshot')
            core2_acc = self.read('addr_accbuf_mon2')
            core1_acc = self.read('addr_accbuf_mon1')
            logging.getLogger(__name__).debug(f'procdone: {bin(procdone)}')
            logging.getLogger(__name__).debug(f'shotcnt/nshot: {shotcnt}/{nshot_reg}')
            logging.getLogger(__name__).debug(f'core2_acc_addr: {core2_acc}')
            logging.getLogger(__name__).debug(f'core1_acc_addr: {core1_acc}')

            if shotcnt == shotcntlast:
                wait_iters += 1
            else:
                wait_iters = 0
                shotcntlast = shotcnt

            if wait_iters > max_wait_iters:
                logging.getLogger(__name__).error(f'Timeout: max wait time of {timeout_per_shot} exceeded on single shot!')
                raise Exception(f'Timeout: max wait time of {timeout_per_shot} exceeded on single shot!')
            else:
                logging.getLogger(__name__).debug(f'wait_iters/max_wait_iters: {wait_iters}/{max_wait_iters}')

        for channame, chan in result_chans.items():
            nreads = nshots * chan.reads_per_shot * get_result_class(chan.dtype).word_size()
            
            # PS-PL MMIO reads must be 64-bit aligned (even number of 32-bit words)
            # If nreads is odd, read one extra word and discard it
            nreads_aligned = nreads if nreads % 2 == 0 else nreads + 1
            
            readval = self.read(chan.mem_name, 0, nreads_aligned).astype(np.uint32)
            
            # Trim to actual requested size if we read extra for alignment
            if nreads_aligned > nreads:
                readval = readval[:nreads]
            
            results[channame] = readval.tobytes()

        return results

    def get_program_memories(self, core_inds: list = None):
        mem_names = [memname for memname in self.bram_cfgs.keys() if 'command' in memname]
        if core_inds is not None:
            return [memname for memname in mem_names if int(memname.split('command')[-1]) in core_inds]
        else:
            return mem_names

 
    def run_prog_acq(self, 
                     n_total_shots: int, 
                     nsamples: int = 8192, 
                     acq_chans: Dict = {'0': 0, '1': 1}, 
                     result_chans: Dict[str, ResultChannel] = None, 
                     delay_nclks: int = 0, 
                     decimator: int = 0, 
                     timeout: int = 10) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Runs the currently loaded program in ACQ (trace acquisition) mode. 

        Parameters
        ----------
        n_total_shots: int
        nsamples: int 
            Number of samples to save per shot
        acq_chans: Dict
            ACQ channels to capture; key is channel being saved to ('0' and '1' are available),
            value is source of ACQ trace (0 is ADC 0, 1 is ADC 1)
        result_chans: Dict
            Optional dictionary of ACC channels to read data from, alongside ACQ data
        delay_nclks: int
            delay (in clocks) of acquisition trigger relative to program start
        decimator: int = 0
            decimation factor (e.g. 0 is full sample rate, 1 is every other sample, etc)
        timeout: int = 10

        Returns
        -------
        Dict, Dict
            First value is a dictionary of ACQ data, keyed by the provided `acq_chans`
            Second value is a dictionary of ACC data, keyed by the provided `acc_read_channels`

        """
        self.write_reg('nshot', 1)
        self.write_reg('dspreset', 0)
        self.write_reg("decimator", decimator)
        for k,v in acq_chans.items():
            self.write_reg("acqchansel%s"%k, int(v))
            print('acqchansel',k,v)
        self.write_reg("delayaftertrig", delay_nclks)
        acq_data = {ch: np.zeros((n_total_shots, nsamples), dtype=np.int32) for ch in acq_chans}
        acc_data = {ch: np.zeros(n_total_shots, dtype=np.complex128) for ch in result_chans.keys()}
        for i in range(n_total_shots):
            self.write_reg("acqbufreset",1)
            time.sleep(0.05)
            self.write_reg("acqbufreset", 0)

            self.write_reg("resetacc", 1)
            time.sleep(0.05)
            self.write_reg("resetacc", 0)

            self.write_reg("start", 0) 

            max_wait_iters = timeout/POLL_INTERVAL
            wait_iters = 0
            while self.read('lastshotdone') == 0:
                time.sleep(POLL_INTERVAL)
                if wait_iters > max_wait_iters:
                    logging.getLogger(__name__).error(f'Timeout: max wait time of {timeout} exceeded!')
                    raise Exception(f'Timeout: max wait time of {timeout} exceeded!')
                wait_iters += 1

            for ch in acq_chans:
                buf_read = self.read(f'acqbuf{ch}', 0, nsamples//2)
                acq_data[ch][i] = get_value16(buf_read)

            if result_chans is not None:
                for channame, chan in result_chans.items():
                    readval = vsign32(self.read(chan.mem_name, 0, 2).astype(int))
                    acc_data[channame] = 1j*readval[0] + readval[1]


        return acq_data, acc_data

class PLInterfaceSync(PLInterface):
    """
    Modified PLInterface class for boards utilizing sync-enabled gateware. Overrides 
    the `start_program` method, adds 64b register read/write.
    """
    
    def __init__(self, 
                 commit_hash: str,
                 dac_current_values: Dict[str, int] = None,
                 dac_nyquist_zone: int = 2,
                 adc_nyquist_zone: int = 1,
                 lmk_freq: float = 500.18,
                 load_xsa: bool = True):
        super().__init__(commit_hash, dac_current_values, dac_nyquist_zone, adc_nyquist_zone, lmk_freq, load_xsa)
        self.write_reg('start', 1)
        time.sleep(0.1)
        self.write_reg('start', 1)
        time.sleep(0.1)
        if 'use_sync' in self.dspregs_cfg:
            self.write_reg('use_sync', 1)

    def start_program(self, nshots: int, clock_count: int) -> None:
        """
        Issue trigger to start the currently loaded executable.
        TODO: handle case of clock_count = None
        
        Parameters
        ----------
        nshots: int
        clock_count: int
            timestamp to trigger program start -- should be the current
            clock_count + offset 
        """
        self.write_reg('nshot', nshots)
        self.write_reg('dspreset', 0)
        self.write_reg("resetacc", 1)
        time.sleep(POLL_INTERVAL)
        self.write_reg("resetacc", 0)
        time.sleep(POLL_INTERVAL)

        if clock_count is None:
            self.write_reg('use_sync', 0)
            time.sleep(POLL_INTERVAL)
            logging.getLogger(__name__).debug(f'starting program with clock_count {clock_count}')
            self.write_reg('start', 0)
            time.sleep(POLL_INTERVAL)
            self.write_reg('use_sync', 1)

        else:
            logging.getLogger(__name__).debug(f'starting program with clock_count {clock_count}')
            self.write_reg('start', 0)
            self.write_64b('copper_clkcnt_trig', clock_count)
            logging.getLogger(__name__).debug(f'actual clock count {self.read_64b("copper_dspclkcnt")}')
 
    def write_64b(self, reg, value) -> None:
        """
        Writes a 64-bit value to a "register". Since the gateware only 
        supports 32-bit values, the value is split into MSB and LSB and 
        written to two corresponding registers.

        Parameters
        ----------
        reg: str
            name of register
        value: int
            value to write
        """
        value_h = (int(value)>>32)&0xffffffff
        value_l = int(value)&0xffffffff
        self.write_reg(reg+'_h', value_h)
        self.write_reg(reg+'_l', value_l)

    def read_64b(self, reg) -> int:
        """
        Read a 64-bit value from a "register" (split into two 32-bit
        registers) 

        Parameters
        ----------
        reg: str

        Returns
        -------
        int: register value
        """
        clkcnt_h = self.read(reg+'_h')
        clkcnt_l = self.read(reg+'_l')
        clkcnt = int(clkcnt_h)*2**32+int(clkcnt_l)
        return clkcnt


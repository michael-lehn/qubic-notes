"""Run a QD-compiled multi-core program on N cores + fproc_meas + shot sequencer.

Environment:
  QD_BIN     JSON from `python -m qdsl FILE --emit-bin OUT.json` (all cores + memories)
  QD_NSHOT   number of shots (default 1)
  QD_ADC     per-shot ADC values per core, shots separated by ';', cores by ',',
             e.g. "1,-1,1;-1,-1,1" (default 1 for every core); the last entry repeats
  QD_MEAS    force measurement bits instead of the demodulated sign, per core and in order
             of measurement, e.g. "0:1,1,0" or "0:1,0;2:1" (the last bit repeats)
  QD_OUT     write the event record as JSON here
  QD_MAX     give up after this many clocks (default 5,000,000)

Besides strobes, measurements and FPROC requests, the record has one 'issue' event per timed
instruction (pulse_write_trig, idle): the core's qclk when it starts waiting, the timestamp t,
and slack = t - qclk. A negative slack is a late trigger: the instruction never fires.
"""
import json
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Edge, First, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

N = 3
CLK_NS = 2
MEMS = {'qdrv_env': (0, 4), 'qdrv_freq': (1, 16), 'rdrv_env': (2, 1),     # mem_sel, 32-bit words per entry
        'rdrv_freq': (3, 16), 'rdlo_env': (4, 1), 'rdlo_freq': (5, 4)}


def cycle():
    return int(get_sim_time('ns') // CLK_NS)


@cocotb.test()
async def run_shots(dut):
    blob = json.load(open(os.environ['QD_BIN']))
    nshot = int(os.environ.get('QD_NSHOT', '1'))
    adc = [[int(v) for v in shot.split(',')] for shot in os.environ.get('QD_ADC', ','.join(['1'] * N)).split(';')]
    max_cycles = int(os.environ.get('QD_MAX', 5_000_000))
    force = {int(k): [int(b) for b in bits.split(',')]
             for k, bits in (c.split(':') for c in os.environ.get('QD_MEAS', '').split(';') if c)}

    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit='ns').start())
    dut.reset.value, dut.stb_start.value, dut.nshot.value = 1, 0, nshot
    dut.cmd_write_enable.value, dut.mem_we.value, dut.acc_shift.value = 0, 0, 0
    dut.meas_force_en.value = sum(1 << k for k in force)
    forced = {k: 0 for k in force}                      # measurements seen per forced core

    def set_force():
        dut.meas_force_bit.value = sum(bits[min(forced[k], len(bits) - 1)] << k for k, bits in force.items())
    set_force()
    await RisingEdge(dut.clk)

    for k in range(N):                                  # load programs and waveform memories
        dut.core_sel.value = k
        for a, w in enumerate(blob.get(f'qubit_command{k}', [])):
            dut.cmd_write_addr.value, dut.cmd_write.value, dut.cmd_write_enable.value = a, int(w, 16), 1
            await RisingEdge(dut.clk)
        dut.cmd_write_enable.value = 0
        for name, (sel, per) in MEMS.items():
            words = [int(w, 16) for w in blob['memories'].get(f'qubit_{name}{k}', [])]
            for a in range(0, len(words), per):
                packed = sum(w << (32 * j) for j, w in enumerate(words[a:a + per]))
                dut.mem_sel.value, dut.mem_addr.value, dut.mem_data.value, dut.mem_we.value = sel, a // per, packed, 1
                await RisingEdge(dut.clk)
        dut.mem_we.value = 0

    def set_adc(shot):
        vals = adc[min(shot, len(adc) - 1)]
        vals = (vals + [vals[-1]] * N)[:N]
        dut.adc_samples.value = sum((v & 0xffff) << (16 * k) for k, v in enumerate(vals))

    events = []
    cores = [dut.core[k].q for k in range(N)]

    async def watch_strobes(k):
        pr = cores[k].dpr.pulsereg
        while True:
            await RisingEdge(pr.cstrobe)
            await ReadOnly()
            events.append(dict(cycle=cycle(), kind='strobe', core=k, qclk=int(cores[k].dpr.qclk_out.value),
                               cfg=int(pr.cfg.value), amp=int(pr.amp.value)))

    async def watch_fproc(k):
        ctu = cores[k].dpr.ctu
        while True:
            await RisingEdge(ctu.fproc_enable)
            await ReadOnly()
            events.append(dict(cycle=cycle(), kind='fproc_request', core=k, qclk=int(cores[k].dpr.qclk_out.value),
                               meas_reg=int(dut.fproc.meas_reg.value)))

    async def watch_meas(k):
        q = cores[k]
        while True:
            await RisingEdge(q.meas_valid)
            await ReadOnly()
            events.append(dict(cycle=cycle(), kind='meas_valid', core=k, qclk=int(q.dpr.qclk_out.value),
                               bit=int(q.meas_bit.value)))
            if k in forced:
                await RisingEdge(dut.clk)                       # fproc_meas has latched this bit
                forced[k] += 1
                set_force()

    async def watch_issue(k):
        dpr = cores[k].dpr
        while True:
            await RisingEdge(dpr.ctu.qclk_trig_enable)
            await ReadOnly()
            q, t = int(dpr.qclk_out.value), int(dpr.pulse_cmd_time.value)
            slack = (t - q + (1 << 31)) % (1 << 32) - (1 << 31)     # qclk wraps (inc_qclk -delta); == compare
            events.append(dict(cycle=cycle(), kind='issue', core=k, qclk=q, t=t, slack=slack))

    async def watch_shots():
        shot = 0
        while True:
            await FallingEdge(dut.procreset_d)                  # cores leave reset: a shot starts
            set_adc(shot)
            events.append(dict(cycle=cycle(), kind='shot_start', shot=shot))
            shot += 1

    for k in range(N):
        cocotb.start_soon(watch_strobes(k))
        cocotb.start_soon(watch_fproc(k))
        cocotb.start_soon(watch_meas(k))
        cocotb.start_soon(watch_issue(k))
    cocotb.start_soon(watch_shots())

    set_adc(0)
    await ClockCycles(dut.clk, 2)
    dut.reset.value = 0
    await ClockCycles(dut.clk, 2)
    dut.stb_start.value = 1
    await RisingEdge(dut.clk)
    dut.stb_start.value = 0
    await First(RisingEdge(dut.done), ClockCycles(dut.clk, max_cycles))
    finished = bool(dut.done.value)

    shot = -1
    for e in sorted(events, key=lambda e: e['cycle']):
        if e['kind'] == 'shot_start':
            shot = e['shot']
        e['shot'] = shot
        if e['kind'] == 'issue':
            continue
        if e['kind'] != 'shot_start':
            extra = ' '.join(f'{k}={e[k]}' for k in ('cfg', 'amp', 'bit', 'meas_reg') if k in e)
            dut._log.info(f"EVENT shot {shot} cycle {e['cycle']:8d} core {e['core']} qclk {e['qclk']:7d} "
                          f"{e['kind']:13s} {extra}")
        else:
            dut._log.info(f"EVENT shot {shot} cycle {e['cycle']:8d} shot_start")
    issues = [e for e in events if e['kind'] == 'issue']
    if issues:
        worst = min(issues, key=lambda e: e['slack'])
        dut._log.info(f"SLACK min {worst['slack']} (core {worst['core']}, t={worst['t']}), "
                      f"{sum(e['slack'] < 0 for e in issues)} late of {len(issues)} timed instructions")
    dut._log.info(f'DONE {finished}')
    if os.environ.get('QD_OUT'):
        json.dump(dict(done=finished, events=sorted(events, key=lambda e: e['cycle'])), open(os.environ['QD_OUT'], 'w'))
    assert finished, 'shots did not complete'

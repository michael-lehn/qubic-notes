"""Run one core's QD-compiled program on the processor RTL (sim_modules/toplevel_sim.sv).

Environment:
  QD_BIN         JSON from `python -m qdsl FILE --emit-bin OUT.json`
  QD_CORE        which core's program to run (default: the first)
  QD_MEAS        comma-separated measurement bits, one per FPROC request (default: 0)
  QD_MAX_CYCLES  give up after this many clocks (default 2,000,000)
  QD_OUT         write the recorded strobes as JSON here

FPROC is modelled as fproc_meas: ready 2 clocks after a request (rtl/fproc_tb).
Every strobe is recorded with the real clock cycle since reset and the core's qclk."""
import json
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, First, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

CLK_NS = 2


@cocotb.test()
async def run_program(dut):
    progs = json.load(open(os.environ['QD_BIN']))
    core = os.environ.get('QD_CORE') or next(iter(progs))
    words = [int(w, 16) for w in progs[core]]
    meas = [int(x) for x in os.environ.get('QD_MEAS', '0').split(',')]
    max_cycles = int(os.environ.get('QD_MAX_CYCLES', 2_000_000))

    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit='ns').start())
    dut.reset.value = 1
    dut.sync_ready.value = 0
    dut.fproc_ready.value = 0
    dut.fproc_data.value = 0
    await RisingEdge(dut.clk)
    for addr, w in enumerate(words):
        dut.cmd_write.value, dut.cmd_write_addr.value, dut.cmd_write_enable.value = w, addr, 1
        await RisingEdge(dut.clk)
    dut.cmd_write_enable.value = 0
    await ClockCycles(dut.clk, 2)
    dut.reset.value = 0
    t0 = get_sim_time('ns')

    requests = []

    async def fproc():                      # fproc_meas model
        while True:
            await RisingEdge(dut.fproc_en_out)
            bit = meas[min(len(requests), len(meas) - 1)]
            requests.append((int((get_sim_time('ns') - t0) / CLK_NS), bit))
            await ClockCycles(dut.clk, 2)
            dut.fproc_data.value = bit
            dut.fproc_ready.value = 1
            await RisingEdge(dut.clk)
            dut.fproc_ready.value = 0

    cocotb.start_soon(fproc())

    strobes = []

    async def watch():
        while True:
            await RisingEdge(dut.cstrobe_out)
            await ReadOnly()
            strobes.append({'cycle': int((get_sim_time('ns') - t0) / CLK_NS), 'qclk': int(dut.dpr.qclk_out.value),
                            'cfg': int(dut.cfg.value), 'amp': int(dut.amp.value)})

    cocotb.start_soon(watch())
    await First(RisingEdge(dut.done_gate), ClockCycles(dut.clk, max_cycles))
    done = bool(dut.done_gate.value)
    for s in strobes:
        dut._log.info(f"STROBE cycle={s['cycle']:8d} qclk={s['qclk']:8d} cfg={s['cfg']} amp={s['amp']}")
    for c, bit in requests:
        dut._log.info(f'FPROC  cycle={c:8d} -> {bit}')
    dut._log.info(f'DONE {done} after {int((get_sim_time("ns") - t0) / CLK_NS)} cycles, {len(strobes)} strobes')
    if os.environ.get('QD_OUT'):
        json.dump({'core': core, 'done': done, 'strobes': strobes, 'fproc': requests}, open(os.environ['QD_OUT'], 'w'))
    assert done, 'program did not finish'

import cocotb
import random
import ipdb
import numpy as np
from cocotb.triggers import Timer, RisingEdge
import distproc.command_gen as cg

CLK_CYCLE = 5
N_CLKS = 500

async def generate_clock(dut):
    for i in range(N_CLKS):
        dut.clk.value = 0
        await Timer(CLK_CYCLE, units='ns')
        dut.clk.value = 1
        await Timer(CLK_CYCLE, units='ns')
    dut._log.debug("clk cycle {}".format(i))

@cocotb.test()
async def single_meas_test(dut):
    cocotb.start_soon(generate_clock(dut))
    dut.reset = 1
    await RisingEdge(dut.clk)
    dut.reset = 0
    dut.fproc_enable.value = 1
    dut.fproc_id[0].value = 0
    await RisingEdge(dut.clk)
    dut.fproc_enable.value = 0
    dut.meas.value = 1
    dut.meas_valid.value = 1
    await RisingEdge(dut.clk)
    assert dut.fproc_ready.value == 1
    assert dut.fproc_data[0].value == 1

@cocotb.test()
async def syndrome_lut_test(dut):
    core_ind = 2
    cocotb.start_soon(generate_clock(dut))
    dut.reset = 1
    await RisingEdge(dut.clk)
    dut.reset = 0
    dut.fproc_enable.value = 1 << core_ind
    dut.fproc_id[core_ind].value = 1
    await RisingEdge(dut.clk)
    dut.fproc_enable.value = 0
    dut.meas.value = 1
    dut.meas_valid.value = 1
    await RisingEdge(dut.clk)
    dut.meas.value = 0
    dut.meas_valid.value = 2
    await RisingEdge(dut.clk)
    assert dut.fproc_ready.value == (1 << core_ind)
    assert dut.fproc_data[core_ind].value == 1

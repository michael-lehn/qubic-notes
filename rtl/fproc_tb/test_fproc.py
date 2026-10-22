"""fproc_meas behaviour (distributed_processor/hdl/fproc_meas.sv). My testbench, cocotb 2.x."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


async def request(dut, core, mid, maxwait=20):
    """Pulse enable for one cycle on `core` with id `mid`; return (latency, data) when ready."""
    await RisingEdge(dut.clk)
    dut.fproc_id[core].value = mid
    dut.fproc_enable.value = 1 << core
    await RisingEdge(dut.clk)
    dut.fproc_enable.value = 0
    for k in range(1, maxwait):
        await ReadOnly()
        if (int(dut.fproc_ready.value) >> core) & 1:
            return k, int(dut.fproc_data[core].value)
        await RisingEdge(dut.clk)
    return None, None


async def measure(dut, idx, bit):
    await RisingEdge(dut.clk)
    dut.meas.value = bit << idx
    dut.meas_valid.value = 1 << idx
    await RisingEdge(dut.clk)
    dut.meas_valid.value = 0


@cocotb.test()
async def stale_result(dut):
    cocotb.start_soon(Clock(dut.clk, 2, unit='ns').start())
    dut.reset.value = 1
    dut.meas.value = 0
    dut.meas_valid.value = 0
    dut.fproc_enable.value = 0
    for i in range(5):
        dut.fproc_id[i].value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.reset.value = 0

    lat0, d0 = await request(dut, 0, 0)
    dut._log.info(f'RESULT f1: request before any measurement -> ready after {lat0} clks, data={d0:#x}')
    await measure(dut, 0, 1)
    lat1, d1 = await request(dut, 0, 0)
    dut._log.info(f'RESULT f2: after meas=1 -> ready after {lat1} clks, data={d1:#x}')
    for _ in range(50):
        await RisingEdge(dut.clk)
    lat2, d2 = await request(dut, 0, 0)
    dut._log.info(f'RESULT f3: 50 clks later, no new measurement -> ready after {lat2} clks, data={d2:#x} (stale value returned, no wait)')
    await measure(dut, 0, 0)
    _, d3 = await request(dut, 0, 0)
    dut._log.info(f'RESULT f4: after meas=0 -> data={d3:#x}')
    await measure(dut, 2, 1)
    _, d4 = await request(dut, 1, 2)
    dut._log.info(f'RESULT f5: core 1 asking for measurement index 2 (=1) -> data={d4:#x} (any core can read any qubit)')

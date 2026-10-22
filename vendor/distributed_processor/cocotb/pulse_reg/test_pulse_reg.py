import cocotb
import random
import ipdb
import numpy as np
from cocotb.triggers import Timer, RisingEdge, ReadWrite
import distproc.command_gen as cg

PHASE_WIDTH = 17
AMP_WIDTH = 16
FREQ_WIDTH=9
N_CLKS = 100
CLK_CYCLE = 4

async def generate_clock(dut):
    for i in range(N_CLKS):
        dut.clk.value = 0
        await Timer(CLK_CYCLE, units='ns')
        dut.clk.value = 1
        await Timer(CLK_CYCLE, units='ns')
    dut._log.debug("clk cycle {}".format(i))

@cocotb.test()
async def test_ival_write(dut):
    cocotb.start_soon(generate_clock(dut))
    phase = np.pi/2
    freq = 0x45
    env_start_addr = 10
    amplitude = 0.9
    cfg = 0b01

    phase_word = int(phase*2**PHASE_WIDTH/(2*np.pi))
    amp_word = int(amplitude*(2**AMP_WIDTH - 1))

    cmd = cg.pulse_i(freq, phase_word, amp_word, env_start_addr, cfg, 0)
    pulse_i_cmd = (cmd >> 37) & (2**79 - 1) #pulse reg sliced out of cmd

    dut.pulse_cmd_in.value = pulse_i_cmd
    dut.pulse_write_en.value = 1

    await(RisingEdge(dut.clk))
    await(ReadWrite())
    phase_out = int(dut.phase.value)
    freq_out = int(dut.freq.value)
    env_word_out = int(dut.env_word.value)
    amp_out = int(dut.amp.value)
    cfg_out = int(dut.cfg.value)


    assert phase_out == int(phase*2**PHASE_WIDTH/(2*np.pi))
    assert freq_out == freq
    assert env_word_out == env_start_addr
    assert amp_out == amp_word
    assert cfg_out == cfg

@cocotb.test()
async def test_ival_persist(dut):
    cocotb.start_soon(generate_clock(dut))
    phase = np.pi/2
    freq = 0x45
    env_start_addr = 10
    amplitude = 0.9
    cfg = 0b01

    phase_word = int(phase*2**PHASE_WIDTH/(2*np.pi))
    amp_word = int(amplitude*(2**AMP_WIDTH - 1))

    cmd = cg.pulse_i(freq, phase_word, amp_word, env_start_addr, cfg, 0)
    pulse_i_cmd = (cmd >> 37) & (2**79 - 1) #pulse reg sliced out of cmd

    dut.pulse_cmd_in.value = pulse_i_cmd
    dut.pulse_write_en.value = 1

    await(RisingEdge(dut.clk))
    dut.pulse_write_en = 0
    cmd = cg.pulse_i(freq+1, phase_word+1, amp_word+1, env_start_addr+1, cfg+1, 0)
    pulse_i_cmd = (cmd >> 37) & (2**79 - 1) #pulse reg sliced out of cmd
    dut.pulse_cmd_in = pulse_i_cmd
    await(RisingEdge(dut.clk))
    await(ReadWrite())
    phase_out = int(dut.phase.value)
    freq_out = int(dut.freq.value)
    env_word_out = int(dut.env_word.value)
    amp_out = int(dut.amp.value)
    cfg_out = int(dut.cfg.value)


    assert phase_out == int(phase*2**PHASE_WIDTH/(2*np.pi))
    assert freq_out == freq
    assert env_word_out == env_start_addr
    assert amp_out == amp_word
    assert cfg_out == cfg

@cocotb.test()
async def test_rval_write(dut):
    cocotb.start_soon(generate_clock(dut))
    phase = np.pi/2
    freq = 0x45
    env_start_addr = 10
    amplitude = 0.9
    cfg = 0b01

    phase_word = int(phase*2**PHASE_WIDTH/(2*np.pi))
    amp_word = int(amplitude*(2**AMP_WIDTH - 1))

    cmd = cg.pulse_cmd(freq_word=freq, phase_regaddr=1, amp_word=amp_word, env_word=env_start_addr, cfg_word=cfg, cmd_time=0)
    pulse_i_cmd = (cmd >> 37) & (2**79 - 1) #pulse reg sliced out of cmd

    dut.pulse_cmd_in.value = pulse_i_cmd
    dut.reg_in = phase_word
    dut.pulse_write_en.value = 1

    await(RisingEdge(dut.clk))
    dut.pulse_write_en = 0
    cmd = cg.pulse_i(freq+1, phase_word+1, amp_word+1, env_start_addr+1, cfg+1, 0)
    pulse_i_cmd = (cmd >> 37) & (2**79 - 1) #pulse reg sliced out of cmd
    dut.pulse_cmd_in = pulse_i_cmd
    await(RisingEdge(dut.clk))
    await(ReadWrite())
    phase_out = int(dut.phase.value)
    freq_out = int(dut.freq.value)
    env_word_out = int(dut.env_word.value)
    amp_out = int(dut.amp.value)
    cfg_out = int(dut.cfg.value)


    assert phase_out == int(phase*2**PHASE_WIDTH/(2*np.pi))
    assert freq_out == freq
    assert env_word_out == env_start_addr
    assert amp_out == amp_word
    assert cfg_out == cfg

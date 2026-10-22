import cocotb
import random
import ipdb
import numpy as np
from cocotb.triggers import Timer, RisingEdge
import distproc.command_gen as cg

CLK_CYCLE = 5
N_CLKS = 500

MEM_READ_LATENCY = 3
RESET_LATENCY = 1
QCLK_RST_DELAY = 4
PULSE_INSTR_TIME = max(MEM_READ_LATENCY, 1)
ALU_INSTR_TIME = max(MEM_READ_LATENCY, 4)
COND_JUMP_INSTR_TIME = ALU_INSTR_TIME + MEM_READ_LATENCY
#JUMP_INSTR_TIME = 2 + MEM_READ_LATENCY
JUMP_INSTR_TIME = 2 + MEM_READ_LATENCY
CSTROBE_DELAY = 2

async def generate_clock(dut):
    for i in range(N_CLKS):
        dut.clk.value = 0
        await Timer(CLK_CYCLE, units='ns')
        dut.clk.value = 1
        await Timer(CLK_CYCLE, units='ns')
    dut._log.debug("clk cycle {}".format(i))

async def load_commands(dut, cmd_list, start_addr=0):
    addr = start_addr
    for cmd in cmd_list:
        dut.cmd_write.value = cmd
        dut.cmd_write_addr.value = addr
        dut.cmd_write_enable.value = 1
        await RisingEdge(dut.clk)
        addr += 1

    dut.cmd_write_enable.value = 0

@cocotb.test()
async def cmd_mem_out_test(dut):
    """
    write some stuff to the command memory, trigger,
    and make sure they come out sequentially. Note:
    set opcodes to 00001 to keep in proper state, and
    make sure execution doesn't stop
    """
    n_cmd = 20
    cmd_list = []

    for i in range(n_cmd):
        cmd_list.append(random.randint(0,2**120-1) + (1<<124))
    
    await cocotb.start(generate_clock(dut))

    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + RESET_LATENCY):
        await RisingEdge(dut.clk)

    cmd_read_list = []
    qclk_val = []
    for i in range(n_cmd):
        cmd_read_list.append(dut.dpr.cmd_buf_out.value)
        qclk_val.append(dut.dpr.qclk_out.value)
        #print('i ' + str(i))
        #print('qclk_val ' + str(dut.qclk_out))
        #print('qclk_rst ' + str(dut.myclk.rst))
        for j in range(ALU_INSTR_TIME):
            await RisingEdge(dut.clk)

    for i in range(n_cmd):
        dut._log.debug('cmd_in {}'.format(int(cmd_list[i])))
        dut._log.debug('cmd_out {}'.format(int(cmd_read_list[i])))
        dut._log.debug('qclk: {}'.format(qclk_val[i]))
        dut._log.debug ('..........................')
        assert hex(int(cmd_read_list[i])) == hex(cmd_list[i])

    #dut._log.info("clk val {}".format(dut.clk))

@cocotb.test()
async def pulse_freq_trig_test(dut):
    """
    run a series of commands to write freq val to cmd reg, then clock them out
    """
    cmd_list = []
    freq_word_list = []
    pulse_time_list = [3, 6, 11, 15, 18, 22]
    n_cmd = len(pulse_time_list)
    pulse_i_opcode = 0b10010000

    for i in range(n_cmd):
        freq_word = random.randint(0, 2**9 - 1)
        freq_word_list.append(freq_word)
        cmd_list.append((pulse_i_opcode << 120) + ((freq_word + 2**10) << 60) + (pulse_time_list[i] << (5)))
    
    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(QCLK_RST_DELAY + RESET_LATENCY):
        await RisingEdge(dut.clk)

    freq_read_list = []
    freq_read_times = []
    for i in range(26):
        if(dut.cstrobe_out.value == 1):
            freq_read_list.append(dut.freq.value)
            freq_read_times.append(dut.dpr.qclk_out.value)
        await RisingEdge(dut.clk)

    dut._log.debug('command in: {}'.format(freq_word_list))
    dut._log.debug('command time in: {}'.format(pulse_time_list))
    dut._log.debug('command out: {}'.format(freq_read_list))
    dut._log.debug('command time out: {}'.format(freq_read_times))
    for i in range(n_cmd):
        assert freq_word_list[i] == freq_read_list[i]
        assert pulse_time_list[i] == freq_read_times[i] - CSTROBE_DELAY
    #assert np.all(np.asarray(cmd_body_list) == np.asarray(cmd_read_list).astype(int))
    #assert np.all(np.asarray(cmd_time_list) == np.asarray(cmd_read_times).astype(int))

@cocotb.test()
async def pulse_i_test(dut):
    cmd_list = []
    freq_word_list = []
    phase_word_list = []
    env_word_list = []
    pulse_time_list = [3, 6, 11, 15, 18, 22]
    n_cmd = len(pulse_time_list)

    for i in range(n_cmd):
        freq_word = random.randint(0, 2**9-1)
        phase_word = random.randint(0, 2**17-1)
        env_word = random.randint(0, 2**24-1)
        amp_word = random.randint(0, 2**16-1)
        cfg_word = random.randint(0, 2**4-1)
        freq_word_list.append(freq_word)
        phase_word_list.append(phase_word)
        env_word_list.append(env_word)
        cmd_list.append(cg.pulse_i(freq_word, phase_word, amp_word, env_word, cfg_word, pulse_time_list[i]))
    
    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    freq_read_list = []
    phase_read_list = []
    env_read_list = []
    pulse_read_times = []

    for i in range(30):
        if(dut.cstrobe_out.value == 1):
            freq_read_list.append(dut.freq.value)
            phase_read_list.append(dut.phase.value)
            env_read_list.append(dut.env_word.value)
            pulse_read_times.append(dut.dpr.qclk_out.value)
        await RisingEdge(dut.clk)

    for i in range(n_cmd):
        assert freq_word_list[i] == freq_read_list[i]
        assert phase_word_list[i] == phase_read_list[i]
        assert env_word_list[i] == env_read_list[i]
        assert pulse_time_list[i] == pulse_read_times[i] - CSTROBE_DELAY

@cocotb.test()
async def regwrite_i_test(dut):
    reg_addr = random.randint(0,15)
    reg_val = random.randint(0, 2**32-1)

    cmd = (0b00010000 << 120) + (reg_val << 88) + (reg_addr << 80)

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, [cmd])

    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + ALU_INSTR_TIME + RESET_LATENCY):
        await RisingEdge(dut.clk)

    reg_read = dut.dpr.regs.data[reg_addr].value

    assert(reg_read == reg_val)

@cocotb.test()
async def reg_i_test(dut):
    """
    Write a value to a random register. Then, perform an operation
    on that register and an intermediate value, and store in another register. 
    Try this 100 times w/ random values and ops.
    """
    for i in range(100):
        cmd_list = []
        reg_addr0 = random.randint(0,15)
        reg_addr1 = random.randint(0,15)
        #reg_val = random.randint(0, 2**32-1)
        #ival = random.randint(0, 2**32-1)
        reg_val = random.randint(-2**31, 2**31-1)
        ival = random.randint(-2**31, 2**31-1)
        op = random.choice(['add', 'sub', 'le', 'ge', 'eq'])
        
        cmd_list.append(cg.alu_cmd('reg_alu', 'i', reg_val, 'id0', 0, reg_addr0))
        cmd_list.append(cg.alu_cmd('reg_alu', 'i', ival, op, reg_addr0, reg_addr1))

        dut._log.debug('cmd 0 in: {}'.format(bin(cmd_list[0])))
        dut._log.debug('cmd 1 in: {}'.format(bin(cmd_list[1])))

        await cocotb.start(generate_clock(dut))
        await load_commands(dut, cmd_list)

        dut.reset.value = 1
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)
        dut.reset.value = 0
        for i in range(MEM_READ_LATENCY + 2*ALU_INSTR_TIME + RESET_LATENCY):
            await RisingEdge(dut.clk)

        reg_read_val = dut.dpr.regs.data[reg_addr1].value

        correct_val = int(evaluate_alu_exp(ival, op, reg_val))

        dut._log.debug('reg val in: {}'.format(reg_val))
        dut._log.debug('i val in: {}'.format(ival))
        dut._log.debug('op: {}'.format(op))
        dut._log.debug('val out: {}'.format(reg_read_val.signed_integer))
        dut._log.debug('correct val out: {}'.format(correct_val))

        assert reg_read_val.integer == correct_val 

@cocotb.test()
async def pulse_reg_test(dut):
    n_cmd = 3
    cmd_list = []
    freq_word_list = []
    phase_word_list = []
    amp_word_list = []
    env_word_list = []
    cfg_word_list = []
    pulse_time_list = [9, 15, 18]

    reg_word = 0x000000a3
    reg_addr = 2

    cmd_list.append(cg.alu_cmd('reg_alu', 'i', reg_word, 'id0', 0, write_reg_addr=reg_addr))

    for i in range(n_cmd):
        freq_word = random.randint(0, 2**9-1)
        phase_word = random.randint(0, 2**17-1)
        amp_word = random.randint(0, 2**16-1)
        cfg_word = random.randint(0,3)
        env_word = random.randint(0, 2**24-1)
        if i==0:
            freq_word = reg_word
            cmd_list.append(cg.pulse_cmd(freq_regaddr=reg_addr, phase_word=phase_word, \
                    amp_word=amp_word, env_word=env_word, cfg_word=cfg_word, cmd_time=pulse_time_list[i]))
        elif i==1:
            phase_word = reg_word
            cmd_list.append(cg.pulse_cmd(freq_word=freq_word, phase_regaddr=reg_addr, \
                    amp_word=amp_word, env_word=env_word, cfg_word=cfg_word, cmd_time=pulse_time_list[i]))
        elif i==2:
            env_word = reg_word
            cmd_list.append(cg.pulse_cmd(freq_word=freq_word, phase_word=phase_word, \
                    amp_word=amp_word, env_regaddr=reg_addr, cfg_word=cfg_word, cmd_time=pulse_time_list[i]))
        elif i==3:
            amp_word = reg_word
            cmd_list.append(cg.pulse_cmd(freq_word=freq_word, phase_word=phase_word, \
                    amp_regaddr=reg_addr, env_word=env_word, cfg_word=cfg_word, cmd_time=pulse_time_list[i]))

        phase_word_list.append(phase_word)
        freq_word_list.append(freq_word)
        amp_word_list.append(amp_word)
        env_word_list.append(env_word)
        cfg_word_list.append(cfg_word)
    
    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + RESET_LATENCY):
        await RisingEdge(dut.clk)

    freq_read_list = []
    phase_read_list = []
    amp_read_list = []
    cfg_read_list = []
    env_read_list = []
    pulse_read_times = []

    for i in range(25):
        if(dut.cstrobe_out.value == 1):
            freq_read_list.append(dut.freq.value)
            phase_read_list.append(dut.phase.value)
            amp_read_list.append(dut.amp.value)
            env_read_list.append(dut.env_word.value)
            cfg_read_list.append(dut.cfg.value)
            pulse_read_times.append(dut.dpr.qclk_out.value)
        await RisingEdge(dut.clk)

    for i in range(n_cmd):
        assert freq_word_list[i] == freq_read_list[i]
        assert phase_word_list[i] == phase_read_list[i]
        assert amp_word_list[i] == amp_read_list[i]
        assert env_word_list[i] == env_read_list[i]
        assert cfg_word_list[i] == cfg_read_list[i]
        assert pulse_time_list[i] == pulse_read_times[i] - CSTROBE_DELAY

@cocotb.test()
async def jump_i_test(dut):
    cmd_list = []
    jump_addr = random.randint(0, 2**8-1)
    cmd_list.append(cg.jump_i(jump_addr))
    for i in range(1, 2**8):
        cmd_list.append(random.randint(0,2**32))
    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)

    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + JUMP_INSTR_TIME):
        await RisingEdge(dut.clk)

    read_command = dut.dpr.cmd_buf_out.value

    dut._log.debug('jump addr: {}'.format(jump_addr))
    dut._log.debug('cmd_in: {}'.format(cmd_list[jump_addr]))
    dut._log.debug('cmd_read: {}'.format(read_command.integer))

    assert read_command == cmd_list[jump_addr]

@cocotb.test()
async def jump_i_cond_test(dut):
    cmd_list = []
    jump_addr = random.randint(0, 2**8-1)

    #register, reg_val, ival, and op used for conditional jump
    reg_addr0 = random.randint(0,15)
    reg_val = random.randint(-2**31, 2**31-1) 
    ival = random.randint(-2**31, 2**31-1)
    op = random.choice(['le', 'ge', 'eq'])
    
    cmd_list.append(cg.alu_cmd('reg_alu', 'i', reg_val, 'id0', 0, reg_addr0))
    cmd_list.append(cg.alu_cmd('jump_cond', 'i', ival, op, reg_addr0, jump_cmd_ptr=jump_addr))

    for i in range(2, 2**8):
        cmd_list.append(random.randint(0,2**32))

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)

    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + COND_JUMP_INSTR_TIME + ALU_INSTR_TIME):
        await RisingEdge(dut.clk)

    read_command = dut.dpr.cmd_buf_out.value

    if evaluate_alu_exp(ival, op, reg_val):
        correct_cmd = cmd_list[jump_addr]
    else:
        correct_cmd = cmd_list[2]


    dut._log.debug('jump addr: {}'.format(jump_addr))
    dut._log.debug('cmd_in: {}'.format(cmd_list[jump_addr]))
    dut._log.debug('cmd_read: {}'.format(read_command.integer))
    dut._log.debug('jump condition: {}'.format(evaluate_alu_exp(ival, op, reg_val)))

    assert read_command == correct_cmd

@cocotb.test()
async def inc_qclk_i_test(dut):
    cmd_list = []
    cmd_wait_range = 25
    qclk_inc_val = random.randint(-2**31, 2**31-1-cmd_wait_range)
    qclk_wait_t = random.randint(0, cmd_wait_range-1)

    cmd_list.append(cg.pulse_i(10, 0, 4, 2, 1, qclk_wait_t))
    cmd_list.append(cg.alu_cmd('inc_qclk', 'i', qclk_inc_val))

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0

    for i in range(cmd_wait_range + PULSE_INSTR_TIME + ALU_INSTR_TIME + MEM_READ_LATENCY + RESET_LATENCY + 1):
        await RisingEdge(dut.clk)
    
    qclk_read_val = dut.dpr.qclk_out.value
    qclk_correct_val = evaluate_alu_exp(qclk_inc_val, 'add', cmd_wait_range + PULSE_INSTR_TIME \
            + ALU_INSTR_TIME + MEM_READ_LATENCY - QCLK_RST_DELAY)

    dut._log.debug('qclk_read_val: {}'.format(qclk_read_val))
    dut._log.debug('qclk_inc_val: {}'.format(qclk_inc_val))
    dut._log.debug('qclk_correct_val: {}'.format(qclk_correct_val))

    assert int(qclk_read_val) == qclk_correct_val

@cocotb.test()
async def read_fproc_test(dut):
    cmd_list = []
    fproc_min_t = 1
    fproc_max_t = 10

    read_reg_addr = random.randint(0, 15)
    fproc_rval = random.randint(0, 2**32-1)
    cmd_list.append(cg.read_fproc(0, read_reg_addr))

    fproc_ready_t = random.randint(fproc_min_t, fproc_max_t)

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + RESET_LATENCY):
        await RisingEdge(dut.clk)

    for i in range(fproc_ready_t):
        await RisingEdge(dut.clk)
    
    dut.fproc_ready.value = 1
    dut.fproc_data.value = fproc_rval

    await RisingEdge(dut.clk)
    dut.fproc_ready.value = 0
    dut.fproc_data.value = 0
    for i in range(COND_JUMP_INSTR_TIME):
        await RisingEdge(dut.clk)
    reg_rval_read = dut.dpr.regs.data[read_reg_addr].value

    assert reg_rval_read == fproc_rval

@cocotb.test()
async def jump_fproc_i_test(dut):
    cmd_list = []
    fproc_max_t = 20
    jump_addr = random.randint(0, 2**8-1)

    fproc_rval = random.randint(-2**31, 2**31-1)
    cmp_ival = random.randint(-2**31, 2**31-1)
    #regwrite_addr = 3
    #cmd_list.append(cg.alu_cmd('reg_alu', 'i', cmp_ival, 'id0', 0, regwrite_addr))
    op = random.choice(['le', 'ge', 'eq'])
    cmd_list.append(cg.alu_cmd('jump_fproc', 'i', cmp_ival, op, jump_cmd_ptr=jump_addr))

    fproc_ready_t = random.randint(0, fproc_max_t)

    for i in range(1, 2**8):
        cmd_list.append(random.randint(0,2**32))

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + ALU_INSTR_TIME):
        await RisingEdge(dut.clk)

    for i in range(fproc_ready_t):
        await RisingEdge(dut.clk)
    
    dut.fproc_ready.value = 1
    dut.fproc_data.value = fproc_rval

    await RisingEdge(dut.clk)
    dut.fproc_ready.value = 0
    dut.fproc_data.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    read_command = dut.dpr.cmd_buf_out.value

    if evaluate_alu_exp(cmp_ival, op, fproc_rval):
        correct_cmd = cmd_list[jump_addr]
    else:
        correct_cmd = cmd_list[1]

    dut._log.debug('jump addr: {}'.format(jump_addr))
    dut._log.debug('cmd_in: {}'.format(cmd_list[jump_addr]))
    dut._log.debug('cmd_read: {}'.format(read_command.integer))
    dut._log.debug('jump condition: {}'.format(evaluate_alu_exp(cmp_ival, op, fproc_rval)))

@cocotb.test()
async def done_gate_test(dut):
    cmd_list = []
    cmd_list.append(cg.alu_cmd('reg_alu', 'i', 1, 'id0', write_reg_addr=0))
    cmd_list.append(cg.alu_cmd('reg_alu', 'i', 1, 'id0', write_reg_addr=0))
    cmd_list.append(cg.alu_cmd('reg_alu', 'i', 1, 'id0', write_reg_addr=0))
    cmd_list.append(cg.done_cmd())

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + RESET_LATENCY + 3*ALU_INSTR_TIME + 2):
        await(RisingEdge(dut.clk))

    donegate = dut.done_gate.value
    assert donegate == 1
    await(RisingEdge(dut.clk))
    donegate = dut.done_gate.value
    assert donegate == 1

@cocotb.test()
async def pulse_reset_test(dut):
    cmd_list = []
    cmd_list.append(cg.pulse_reset())

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(MEM_READ_LATENCY + RESET_LATENCY + 1):
        await(RisingEdge(dut.clk))

    rst = dut.pulse_reset.value
    assert rst == 1
    await(RisingEdge(dut.clk))
    rst = dut.pulse_reset.value
    assert rst == 0 

@cocotb.test()
async def pulse_sync_test(dut):
    cmd_list = []
    freq_word_list = []
    phase_word_list = []
    env_word_list = []
    pulse_time_list = [3, 6, 11, 15, 18, 22, 4]
    n_cmd = len(pulse_time_list)

    for i in range(n_cmd):
        freq_word = random.randint(0, 2**9-1)
        phase_word = random.randint(0, 2**17-1)
        env_word = random.randint(0, 2**24-1)
        amp_word = random.randint(0, 2**16-1)
        cfg_word = random.randint(0, 2**4-1)
        freq_word_list.append(freq_word)
        phase_word_list.append(phase_word)
        env_word_list.append(env_word)
        cmd_list.append(cg.pulse_i(freq_word, phase_word, amp_word, env_word, cfg_word, pulse_time_list[i]))
    
    cmd_list.insert(-1, cg.sync(0))
    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    freq_read_list = []
    phase_read_list = []
    env_read_list = []
    pulse_read_times = []

    for i in range(45):
        if(dut.cstrobe_out.value == 1):
            freq_read_list.append(dut.freq.value)
            phase_read_list.append(dut.phase.value)
            env_read_list.append(dut.env_word.value)
            pulse_read_times.append(dut.dpr.qclk_out.value)
        await RisingEdge(dut.clk)
        if i == 30:
            dut.sync_ready.value = 1
        elif i == 31:
            dut.sync_ready.value = 0


    for i in range(n_cmd):
        assert freq_word_list[i] == freq_read_list[i]
        assert phase_word_list[i] == phase_read_list[i]
        assert env_word_list[i] == env_read_list[i]
        assert pulse_time_list[i] == pulse_read_times[i] - CSTROBE_DELAY

@cocotb.test()
async def idle_test(dut):
    cmd_list = []
    cmd_list.append(cg.idle(100))
    cmd_list.append(cg.done_cmd())

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(105 + MEM_READ_LATENCY + RESET_LATENCY + 3*ALU_INSTR_TIME + 2):
        await(RisingEdge(dut.clk))
        if dut.done_gate.value == 1:
            done_qclk_time = int(dut.dpr.qclk_out.value)
            break

    dut._log.debug(f'qclk_done_time: {done_qclk_time}')
    assert done_qclk_time > 100

@cocotb.test()
async def idle_pulse_test(dut):
    cmd_list = []
    cmd_list.append(cg.idle(100))
    cmd_list.append(cg.pulse_i(10, 3, 1, 0, 0, 103))
    cmd_list.append(cg.done_cmd())

    await cocotb.start(generate_clock(dut))
    await load_commands(dut, cmd_list)
    dut.reset.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.reset.value = 0
    for i in range(105 + MEM_READ_LATENCY + RESET_LATENCY + 3*ALU_INSTR_TIME + 2 + 100):
        await(RisingEdge(dut.clk))


def evaluate_alu_exp(in0, op, in1):
    if op == 'add':
        return (cg.twos_complement(in1) + cg.twos_complement(in0)) % 2**32
    elif op == 'sub':
        return (cg.twos_complement(in0) + cg.twos_complement(-in1)) % 2**32
    elif op == 'ge':
        return in0 > in1
    elif op == 'le':
        return in0 < in1
    elif op == 'eq':
        return in1 == in0
    elif op == 'id0':
        return in0
    elif op == 'id1':
        return in1

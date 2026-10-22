"""Cycle-level checks of the distributed processor core (distributed_processor/hdl/proc.sv)
via sim_modules/toplevel_sim.sv. My testbench (cocotb 2.x), not part of QubiC.

Each test prints a RESULT line; assertions encode the claim being checked."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

import distproc.command_gen as cg

DECODE = 1


def alu(op, imm_or_reg, in0, aluop, in1=0, out=None, jump=None, func_id=None):
    return cg.alu_cmd(op, imm_or_reg, in0, aluop, in1, out, jump, func_id)


async def setup(dut, prog, fproc_latency=2, fproc_data=0, sync_ready=0):
    """Load program, reset, start an FPROC responder that raises ready `fproc_latency`
    cycles after enable (fproc_meas behaviour, checked separately in test_fproc_meas)."""
    cocotb.start_soon(Clock(dut.clk, 2, unit='ns').start())
    dut.reset.value = 1
    dut.sync_ready.value = sync_ready
    dut.fproc_ready.value = 0
    dut.fproc_data.value = fproc_data
    dut.cmd_write_enable.value = 0
    await RisingEdge(dut.clk)
    for addr, word in enumerate(prog):
        dut.cmd_write.value = word
        dut.cmd_write_addr.value = addr
        dut.cmd_write_enable.value = 1
        await RisingEdge(dut.clk)
    dut.cmd_write_enable.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    async def fproc_responder():
        pipe = [0] * fproc_latency
        while True:
            await RisingEdge(dut.clk)
            en = int(dut.fproc_en_out.value)
            pipe = pipe[1:] + [en]
            dut.fproc_ready.value = pipe[0]
    cocotb.start_soon(fproc_responder())
    dut.reset.value = 0


async def trace(dut, ncycles):
    """Per-cycle samples after reset release."""
    rows = []
    for cyc in range(ncycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        rows.append(dict(cyc=cyc,
                         state=int(dut.dpr.ctu.state.value),
                         pc=int(dut.dpr.instr.cur_val.value),
                         qclk=int(dut.dpr.qclk_out.value),
                         cstrobe=int(dut.cstrobe_out.value),
                         amp=int(dut.amp.value),
                         fproc_en=int(dut.fproc_en_out.value),
                         sync_en=int(dut.sync_enable.value),
                         done=int(dut.done_gate.value),
                         instr=int(dut.dpr.local_cmd.value)))
    return rows


def decode_entries(rows):
    """Cycle at which each instruction enters DECODE (one entry per executed instruction)."""
    out, prev = [], None
    for r in rows:
        if r['state'] == DECODE and prev != DECODE:
            out.append(r)
        prev = r['state']
    return out


def opname(word):
    return {v: k for k, v in cg.opcodes.items()}.get((word >> 123) & 0x1f) or \
        {v: k for k, v in cg.opcodes.items()}.get((word >> 120) >> 3, '?')


@cocotb.test()
async def t1_cycle_costs(dut):
    """Cycles per instruction class = distance between consecutive DECODE entries."""
    prog = [
        alu('reg_alu', 'i', 5, 'id0', 0, 1),                    # 0 reg_alu_i
        alu('reg_alu', 'i', 1, 'add', 1, 1),                    # 1 reg_alu_i
        alu('inc_qclk', 'i', 0, None),                          # 2 inc_qclk_i (+0)
        cg.jump_i(4),                                           # 3 jump_i -> 4
        alu('jump_cond', 'i', 0, 'ge', 1, jump=7),              # 4 jump_cond_i NOT taken (0 > 6 false)
        alu('jump_cond', 'i', 9, 'ge', 1, jump=6),              # 5 jump_cond_i taken (9 > 6) -> 6
        cg.pulse_cmd(amp_word=100, cfg_word=0),                 # 6 pulse_write (no trigger)
        cg.pulse_cmd(amp_word=200, cfg_word=0),                 # 7 pulse_write
        alu('alu_fproc', 'i', 0, 'id1', out=2, func_id=0),      # 8 alu_fproc_i (read_fproc)
        alu('jump_fproc', 'i', 1, 'eq', jump=10, func_id=0),    # 9 jump_fproc_i taken (fproc_data=1) -> 10
        cg.done_cmd(),                                          # 10 done
    ]
    await setup(dut, prog, fproc_data=1)
    rows = await trace(dut, 120)
    ent = decode_entries(rows)
    costs = []
    for a, b in zip(ent, ent[1:]):
        costs.append((a['pc'], opname(a['instr']), b['cyc'] - a['cyc']))
    for c in costs:
        dut._log.info(f'RESULT t1 cost: addr~{c[0]} {c[1]:18s} {c[2]} clks')
    names = [c[1] for c in costs]
    got = {}
    for (pc, n, k) in costs:
        got.setdefault(n, []).append(k)
    dut._log.info(f'RESULT t1 summary: {got}')


@cocotb.test()
async def t2_timed_trigger(dut):
    """pulse_write_trig fires when qclk == cmd_time: report qclk at the cstrobe edge."""
    prog = [alu('reg_alu', 'i', 1, 'id0', 0, 0),
            cg.pulse_cmd(amp_word=1234, cfg_word=0, cmd_time=100),
            cg.done_cmd()]
    await setup(dut, prog)
    rows = await trace(dut, 200)
    hits = [r for r in rows if r['cstrobe']]
    assert hits, 'no cstrobe'
    dut._log.info(f"RESULT t2: cstrobe first seen at qclk={hits[0]['qclk']} (cmd_time=100), amp={hits[0]['amp']}")


@cocotb.test()
async def t3_late_trigger_hangs(dut):
    """A trigger time already in the past never fires: core stays in DECODE."""
    prog = [alu('reg_alu', 'i', 1, 'id0', 0, 0)] * 4 + \
           [cg.pulse_cmd(amp_word=1, cfg_word=0, cmd_time=3), cg.done_cmd()]
    await setup(dut, prog)
    rows = await trace(dut, 3000)
    strobes = sum(r['cstrobe'] for r in rows)
    last = rows[-1]
    dut._log.info(f"RESULT t3: cstrobes={strobes}, final state={last['state']} (1=DECODE), "
                  f"qclk={last['qclk']}, done={last['done']}")
    assert strobes == 0 and last['state'] == DECODE and last['done'] == 0


@cocotb.test()
async def t4_inc_qclk(dut):
    """inc_qclk immediate and register forms: qclk jump measured around the instruction."""
    prog = [alu('reg_alu', 'i', -250, 'id0', 0, 3),   # r3 = -250
            alu('inc_qclk', 'i', 1000, None),           # qclk += 1000
            alu('inc_qclk', 'r', 3, None),              # qclk += r3
            cg.done_cmd()]
    await setup(dut, prog)
    rows = await trace(dut, 60)
    jumps = [(rows[i]['cyc'], rows[i - 1]['qclk'], rows[i]['qclk']) for i in range(1, len(rows))
             if rows[i]['qclk'] != (rows[i - 1]['qclk'] + 1) % 2**32]
    for c, a, b in jumps:
        delta = ((b - a + 2**31) % 2**32) - 2**31
        dut._log.info(f'RESULT t4: cycle {c}: qclk {a} -> {b}  (step {delta}, i.e. in0 {delta - 1} beyond a normal tick)')


@cocotb.test()
async def t5_strict_compare(dut):
    """jump_cond ge: taken iff in0 > in1 (strict). r1 = 5."""
    prog = [alu('reg_alu', 'i', 5, 'id0', 0, 1),               # 0 r1 = 5
            alu('jump_cond', 'i', 5, 'ge', 1, jump=3),         # 1 5 > 5 ? -> 3
            alu('reg_alu', 'i', 111, 'id0', 0, 2),             # 2 r2 = 111 (fallthrough marker)
            alu('jump_cond', 'i', 6, 'ge', 1, jump=5),         # 3 6 > 5 ? -> 5
            alu('reg_alu', 'i', 222, 'id0', 0, 2),             # 4 r2 = 222 (should be skipped)
            alu('jump_cond', 'i', 5, 'le', 1, jump=7),         # 5 5 < 5 ? -> 7
            alu('reg_alu', 'i', 333, 'id0', 0, 4),             # 6 r4 = 333 (fallthrough marker)
            cg.done_cmd()]                                     # 7
    await setup(dut, prog)
    await trace(dut, 80)
    regs = dut.dpr.regs.data
    r2, r4 = int(regs[2].value), int(regs[4].value)
    dut._log.info(f'RESULT t5: after "5 ge 5" fell through -> r2={r2} (111 expected, 222 would mean 6>5 not taken); '
                  f'"5 le 5" fell through -> r4={r4} (333 expected)')
    assert r2 == 111 and r4 == 333


@cocotb.test()
async def t6_amp_truncation(dut):
    """amp 0.5 + (-0.1 encoded as 16-bit word 62259): pulse sees low 16 bits, compare sees 32 bits."""
    prog = [alu('reg_alu', 'i', cg.get_amp_word(0.5), 'id0', 0, 0),     # r0 = 16383
            alu('reg_alu', 'i', cg.get_amp_word(-0.1), 'add', 0, 0),    # r0 += 62259
            cg.pulse_cmd(amp_regaddr=0, cfg_word=0, cmd_time=60),        # amp from r0
            alu('jump_cond', 'i', cg.get_amp_word(1.0), 'ge', 0, jump=5),  # 32767 > r0 ?  -> 5
            alu('reg_alu', 'i', 999, 'id0', 0, 7),                      # r7 = 999 if NOT taken
            cg.done_cmd()]
    await setup(dut, prog)
    rows = await trace(dut, 150)
    hit = [r for r in rows if r['cstrobe']][0]
    r0, r7 = int(dut.dpr.regs.data[0].value), int(dut.dpr.regs.data[7].value)
    dut._log.info(f'RESULT t6: r0={r0} (32-bit), pulse amp word={hit["amp"]} '
                  f'(={hit["amp"]/32767:.3f}), "1.0 > amp" taken? {"no" if r7 == 999 else "yes"}')


@cocotb.test()
async def t7_sync_without_ready(dut):
    """sync with sync.ready never asserted (as in the generated gateware) -> core never reaches done."""
    prog = [cg.sync(0), cg.done_cmd()]
    await setup(dut, prog, sync_ready=0)
    rows = await trace(dut, 500)
    dut._log.info(f"RESULT t7: state after 500 clks={rows[-1]['state']} (6=SYNC_WAIT), done={rows[-1]['done']}")


@cocotb.test()
async def t8_zero_word_is_done(dut):
    """Running off the end of the program (all-zero words) halts like done."""
    prog = [alu('reg_alu', 'i', 1, 'id0', 0, 0)]
    await setup(dut, prog)
    rows = await trace(dut, 40)
    dut._log.info(f"RESULT t8: state={rows[-1]['state']} (9=DONE), done_gate={rows[-1]['done']}")

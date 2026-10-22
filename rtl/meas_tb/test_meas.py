"""Measurement-feedback timing on RTL: processor + fproc_meas + rdlo element/mixer.

Environment:
  QD_BIN    JSON from `python -m qdsl FILE --emit-bin OUT.json` (program + memories)
  QD_ADC    constant ADC sample (signed int, default 1); its sign sets the measured bit
  QD_SHIFT  accumulator shift (default 0)
  QD_OUT    write the event report as JSON here
"""
import json
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

import distproc.command_gen as cg

DECODE = 1
OPC = {v: k for k, v in cg.opcodes.items()}


def sig(h):
    return int(h.value)


@cocotb.test()
async def feedback_timing(dut):
    blob = json.load(open(os.environ['QD_BIN']))
    words = [int(w, 16) for w in blob['qubit_command0']]
    env = [int(w, 16) for w in blob['memories'].get('qubit_rdlo_env0', [])]
    freq = [int(w, 16) for w in blob['memories'].get('qubit_rdlo_freq0', [])]
    adc = int(os.environ.get('QD_ADC', '1'))

    cocotb.start_soon(Clock(dut.clk, 2, unit='ns').start())
    dut.reset.value = 1
    for name in ('cmd_write_enable', 'env_write_enable', 'freq_write_enable'):
        getattr(dut, name).value = 0
    dut.adc_sample.value = adc & 0xffff
    dut.acc_shift.value = int(os.environ.get('QD_SHIFT', '0'))
    await RisingEdge(dut.clk)
    for a, w in enumerate(words):
        dut.cmd_write_addr.value, dut.cmd_write.value, dut.cmd_write_enable.value = a, w, 1
        await RisingEdge(dut.clk)
    dut.cmd_write_enable.value = 0
    for a, w in enumerate(env):
        dut.env_write_addr.value, dut.env_write.value, dut.env_write_enable.value = a, w, 1
        await RisingEdge(dut.clk)
    dut.env_write_enable.value = 0
    for a in range(0, len(freq), 4):                      # 4 x 32-bit words -> one 128-bit entry, word 0 in the LSBs
        packed = sum(w << (32 * k) for k, w in enumerate(freq[a:a + 4]))
        dut.freq_write_addr.value, dut.freq_write.value, dut.freq_write_enable.value = a // 4, packed, 1
        await RisingEdge(dut.clk)
    dut.freq_write_enable.value = 0
    await ClockCycles(dut.clk, 2)
    dut.reset.value = 0

    rows = []
    for cyc in range(4000):
        await RisingEdge(dut.clk)
        await ReadOnly()
        cmd = sig(dut.dpr.local_cmd)
        rows.append(dict(
            cyc=cyc, qclk=sig(dut.dpr.qclk_out), state=sig(dut.dpr.ctu.state), pc=sig(dut.dpr.instr.cur_val),
            op=OPC.get(cmd >> 123) or OPC.get(cmd >> 123 & 0x1e), cmd_time=(cmd >> 5) & 0xffffffff,
            cstrobe=sig(dut.dpr.pulsereg.cstrobe), cfg=sig(dut.dpr.pulsereg.cfg),
            cmdstb=sig(dut.rdlo_elem.cmdstb), valid_r=sig(dut.rdlo_elem.valid_r),
            accvalid=sig(dut.accvalid), dvalid=sig(dut.fproc_data_valid_r),
            meas_valid=sig(dut.fproc_meas_valid), meas_in=sig(dut.fproc_meas_input),
            meas_reg=sig(dut.fproc.meas_reg), fen=sig(dut.dpr.ctu.fproc_enable),
            fready=sig(dut.dpr.ctu.fproc_ready), done=sig(dut.done_gate)))
        if rows[-1]['done']:
            break

    def first(pred, after=0):
        return next((r for r in rows if r['cyc'] >= after and pred(r)), None)

    rdlo = first(lambda r: r['cstrobe'] and (r['cfg'] & 3) == 2)
    cmdstb = first(lambda r: r['cmdstb'])
    gate_on = first(lambda r: r['valid_r'])
    gate_off = first(lambda r: not r['valid_r'], gate_on['cyc'])
    accv = first(lambda r: r['accvalid'])
    mvalid = first(lambda r: r['meas_valid'])
    mreg = next((r for r, p in zip(rows[1:], rows) if r['meas_reg'] != p['meas_reg']), None)
    fen = first(lambda r: r['fen'])
    fready = first(lambda r: r['fready'])
    decodes = [r for r, p in zip(rows[1:], rows) if r['state'] == DECODE and p['state'] != DECODE
               and r['op'] in ('pulse_write_trig', 'idle')]
    strobes = [(r['qclk'], r['cfg']) for r, p in zip(rows[1:], rows) if r['cstrobe'] and not p['cstrobe']]

    log = dut._log.info
    log(f'ADC sample {adc}: accumulated sign bit -> meas_reg {rows[-1]["meas_reg"]}')
    log(f"rdlo strobe            qclk {rdlo['qclk']}")
    log(f"rdlo element cmdstb    qclk {cmdstb['qclk']}")
    log(f"rdlo gate (valid_r)    qclk {gate_on['qclk']} .. {gate_off['qclk'] - 1}  ({gate_off['qclk'] - gate_on['qclk']} clks)")
    log(f"accvalid (stbout)      qclk {accv['qclk']}")
    log(f"fproc_meas_valid       qclk {mvalid['qclk']}")
    log(f"meas_reg updated       qclk {mreg['qclk'] if mreg else 'unchanged (same bit as reset value)'}")
    log(f"FPROC request (enable) qclk {fen['qclk']}   ready qclk {fready['qclk']}")
    for r in decodes:
        log(f"DECODE {r['op']:16s} pc={r['pc']:3d} at qclk {r['qclk']:5d}  cmd_time {r['cmd_time']:5d}  "
            f"slack {r['cmd_time'] - r['qclk']:4d}")
    log(f'strobes (qclk, cfg): {strobes}')
    report = dict(adc=adc, rdlo_strobe=rdlo['qclk'], cmdstb=cmdstb['qclk'], gate=[gate_on['qclk'], gate_off['qclk']],
                  accvalid=accv['qclk'], meas_valid=mvalid['qclk'], meas_reg_update=mreg['qclk'] if mreg else None,
                  fproc_enable=fen['qclk'], fproc_ready=fready['qclk'], meas_bit=rows[-1]['meas_reg'],
                  decodes=[(r['op'], r['qclk'], r['cmd_time']) for r in decodes], strobes=strobes,
                  done=bool(rows[-1]['done']))
    if os.environ.get('QD_OUT'):
        json.dump(report, open(os.environ['QD_OUT'], 'w'))
    assert report['done'], 'program did not finish'

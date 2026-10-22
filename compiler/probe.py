"""Probe edge cases claimed in Part B (my tooling)."""
import contextlib, io
import run_examples as r
import distproc.command_gen as cg

print('get_amp_word(-0.1) =', cg.get_amp_word(-0.1), ' get_amp_word(0.1) =', cg.get_amp_word(0.1))
print('32-bit immediate field for -0.1 amp after alu_cmd twos_complement:',
      cg.twos_complement(cg.get_amp_word(-0.1)))

prog = [{'name': 'declare', 'var': 'amp', 'scope': ['Q0'], 'dtype': 'amp'},
        {'name': 'set_var', 'var': 'amp', 'value': 0.5},
        {'name': 'alu', 'op': 'add', 'lhs': -0.1, 'rhs': 'amp', 'out': 'amp'},
        {'name': 'pulse', 'dest': 'Q0.qdrv', 'freq': 'Q0.freq', 'phase': 0, 'amp': 'amp', 'twidth': 32e-9,
         'env': {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25}}}]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r.run('neg amp', prog, show_ir=False)
print('\n'.join(l for l in buf.getvalue().splitlines() if 'reg_alu' in l))

regs = [{'name': 'declare', 'var': f'v{i}', 'scope': ['Q0'], 'dtype': 'int'} for i in range(17)]
regs += [{'name': 'set_var', 'var': f'v{i}', 'value': i} for i in range(17)]
try:
    with contextlib.redirect_stdout(io.StringIO()):
        r.run('17 regs', regs, show_ir=False)
    print('17 regs: OK')
except Exception as e:
    print('17 regs ->', type(e).__name__, e)

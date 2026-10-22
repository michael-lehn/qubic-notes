"""Print a compact view of the IR after each compiler pass (my tooling, not QubiC's)."""
import copy, sys
import distproc.compiler as cm
from run_examples import EX, FPGA_CFG, QCHIP

def short(ins):
    n = ins.name
    if n == 'pulse':
        return f"pulse({ins.dest}, amp={ins.amp if isinstance(ins.amp,str) else round(ins.amp,3)}, t={ins.start_time})"
    if n in ('loop', 'branch_fproc', 'branch_var'):
        return f"{n}(...)"
    if hasattr(ins, 'qubit') and n not in ('delay', 'barrier') and type(ins).__name__ == 'Gate':
        return f"Gate:{n}{ins.qubit}"
    extra = {k: getattr(ins, k) for k in ('var', 'label', 'jump_label', 't', 'end_time', 'nclks', 'func_id') if getattr(ins, k, None) is not None}
    return f"{n}{extra if extra else ''}"

title, prog = EX[sys.argv[1]]
comp = cm.Compiler(copy.deepcopy(prog))
print('INPUT:', [short(i) for i in comp.ir_prog.blocks['block_0']['instructions']])
for p in cm.get_passes(FPGA_CFG, QCHIP):
    p.run_pass(comp.ir_prog)
    print(f'--- after {type(p).__name__}')
    for b in comp.ir_prog.blocknames_by_ind:
        blk = comp.ir_prog.blocks[b]
        sc = sorted(blk.get('scope', [])) if 'scope' in blk else '-'
        print(f'   [{b}] scope={sc if len(str(sc))<60 else "..."} edges->{list(comp.ir_prog.control_flow_graph.successors(b))}')
        print('       ', ', '.join(short(i) for i in blk['instructions']))

"""Hand-written assembly fed straight to GlobalAssembler (bypasses the IR compiler). My tooling."""
import distproc.compiler as cm
import distproc.assembler as am
import qubic.rfsoc.hwconfig as rfhw
import run_examples as r

CORE = ('Q0.qdrv', 'Q0.rdrv', 'Q0.rdlo')
ENV = {'env_func': 'cos_edge_square', 'paradict': {'ramp_fraction': 0.25, 'twidth': 32e-9}}

def assemble(title, prog):
    print('===', title)
    try:
        exe = am.GlobalAssembler(cm.CompiledProgram({CORE: prog}), r.CHAN_CFG,
                                 rfhw.elemconfig_classfactory).get_assembled_program()
        buf = exe.program_binaries[':qubit_command0'] if ':qubit_command0' in exe.program_binaries \
            else exe.program_binaries['qubit_command0']
        for a in range(0, len(buf), 16):
            w = int.from_bytes(buf[a:a + 16], 'little')
            print(f'   @{a // 16:<3d} {w:032x}  {r.decode(w)}')
    except Exception as e:
        print('   !!', type(e).__name__, e)

assemble('A: pulse with amp AND phase from registers (assembler splits)', [
    {'op': 'declare_reg', 'name': 'a', 'dtype': 'amp'},
    {'op': 'declare_reg', 'name': 'p', 'dtype': 'phase'},
    {'op': 'reg_alu', 'in0': 0.5, 'in1_reg': 'a', 'alu_op': 'id0', 'out_reg': 'a'},
    {'op': 'reg_alu', 'in0': 1.0, 'in1_reg': 'p', 'alu_op': 'id0', 'out_reg': 'p'},
    {'op': 'pulse', 'freq': 4.46e9, 'phase': 'p', 'amp': 'a', 'env': ENV, 'start_time': 100, 'dest': 'Q0.qdrv'},
    {'op': 'done_stb'}])

assemble('B: runtime-variable delay via register-sourced inc_qclk (ISA allows, compiler never emits)', [
    {'op': 'declare_reg', 'name': 'tau', 'dtype': 'int'},
    {'op': 'reg_alu', 'in0': -250, 'in1_reg': 'tau', 'alu_op': 'id0', 'out_reg': 'tau'},
    {'op': 'pulse', 'freq': 4.46e9, 'phase': 0.0, 'amp': 0.5, 'env': ENV, 'start_time': 50, 'dest': 'Q0.qdrv'},
    {'op': 'inc_qclk', 'in0': 'tau'},
    {'op': 'pulse', 'freq': 4.46e9, 'phase': 0.0, 'amp': 0.5, 'env': ENV, 'start_time': 100, 'dest': 'Q0.qdrv'},
    {'op': 'done_stb'}])

assemble('C: frequency from a register (int index into freq table)', [
    {'op': 'declare_reg', 'name': 'fi', 'dtype': 'int'},
    {'op': 'declare_freq', 'freq': 4.46e9, 'channel': 'Q0.qdrv', 'freq_ind': 0},
    {'op': 'declare_freq', 'freq': 4.47e9, 'channel': 'Q0.qdrv', 'freq_ind': 1},
    {'op': 'reg_alu', 'in0': 1, 'in1_reg': 'fi', 'alu_op': 'id0', 'out_reg': 'fi'},
    {'op': 'pulse', 'freq': 'fi', 'phase': 0.0, 'amp': 0.5, 'env': ENV, 'start_time': 100, 'dest': 'Q0.qdrv'},
    {'op': 'done_stb'}])

assemble('D: sync opcode', [{'op': 'sync', 'barrier_id': 0}, {'op': 'done_stb'}])

assemble('E: jump_cond with non-compare alu_op (add) - assembler check?', [
    {'op': 'declare_reg', 'name': 'x', 'dtype': 'int'},
    {'op': 'jump_cond', 'in0': 1, 'alu_op': 'add', 'in1_reg': 'x', 'jump_label': 'L'},
    {'op': 'jump_label', 'dest_label': 'L'},
    {'op': 'done_stb'}])

assemble('F: alu_fproc add (count measurement outcomes)', [
    {'op': 'declare_reg', 'name': 'n', 'dtype': 'int'},
    {'op': 'alu_fproc', 'in0': 'n', 'alu_op': 'add', 'out_reg': 'n', 'func_id': 0},
    {'op': 'done_stb'}])

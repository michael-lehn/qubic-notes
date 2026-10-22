import numpy as np
#from instr_params.vh
#TODO: consider refactoring this into fewer functions,
#      since many ALU instructions have the same structure
#      UPDATE: consider depracating more specific cg functions
alu_opcodes = {'id0' : 0b000,
               'id1' : 0b110,
               'add' : 0b001,
               'sub' : 0b010,
               'eq' : 0b011,
               'le' : 0b100,
               'ge' : 0b101,
               'zero' : 0b111}

opcodes = {'pulse_write' : 0b10000,
           'pulse_write_trig' : 0b10010,
           'reg_alu_i' : 0b00010, #|opcode[8]|cmd_value[32]|reg_addr[4]|reg_write_addr[4]
           'reg_alu' : 0b00011, #|opcode[8]|reg_addr[4]|resrv[28]|reg_addr[4]|reg_write_addr[4]
           'jump_i' : 0b00100, #|opcode[8]|cmd_value[32]|reg_addr[4]
           'jump_cond_i' : 0b00110, #|opcode[8]|cmd_value[32]|reg_addr[4]|instr_ptr_addr[8]
           'jump_cond' : 0b00111, #jump address is always immediate
           'alu_fproc' : 0b01001,
           'alu_fproc_i' : 0b01000,
           'jump_fproc_i' : 0b01010,
           'jump_fproc' : 0b01011,
           'inc_qclk_i' : 0b01100,
           'inc_qclk' : 0b01101,
           'sync' : 0b01110,
           'done' : 0b10100,
           'pulse_reset' : 0b10110,
           'idle' : 0b11000}

#pulse parameters
pulse_field_widths = {
        'cmd_time' : 32,
        'cfg' : 4,
        'amp' : 16,
        'freq' : 9,
        'phase' : 17,
        'env_word' : 24}

pulse_field_pos = {'cmd_time' : 5}
pulse_field_pos['cfg'] = pulse_field_pos['cmd_time'] + pulse_field_widths['cmd_time']
pulse_field_pos['amp'] = pulse_field_pos['cfg'] + pulse_field_widths['cfg'] + 1
pulse_field_pos['freq'] = pulse_field_pos['amp'] + pulse_field_widths['amp'] + 2
pulse_field_pos['phase'] = pulse_field_pos['freq'] + pulse_field_widths['freq'] + 2
pulse_field_pos['env_word'] = pulse_field_pos['phase'] + pulse_field_widths['phase'] + 2


def pulse_i(freq_word, phase_word, amp_word, env_word, cfg_word, cmd_time):
    """
    Simplest type of pulse: pulse parameters and trigger time
    are all immediate values.

    Parameters
    ----------
        freq_word : int
            word encoding the pulse carrier frequency 
            (usually (f/sample_rate)*2**NBITS)
        phase_word: int
            word encoding initial carrier phase 
        env_word : int
            word describing env address and duration
            (initial version is 12 bit MSB ...)
        amp_word: int
        cfg_word: int
        cmd_time: int

    """
    #freq_int = int((freq/1.e9) * 2**24)
    #phase_int = int((phase/(2*np.pi) * 2**14))
    ##cmd_word = (env_start_addr << 50) + (env_length << 38) + (phase_int << 24) + freq_int
    #if env_length % 4 != 0:
    #    raise Exception('length of envelope must be a multiple of 4!')
    return pulse_cmd(freq_word=freq_word, phase_word=phase_word, 
            amp_word=amp_word, env_word=env_word, cfg_word=cfg_word, cmd_time=cmd_time)

def pulse_cmd(freq_word=None, freq_regaddr=None, phase_word=None, phase_regaddr=None,
        amp_word=None, amp_regaddr=None, cfg_word=None, env_word=None, env_regaddr=None, cmd_time=None):
    """
    General form for a pulse command. This instruction can execute the following actions
    (in one instruction cycle):
        1. Load parameters into pulse register. All parameters can be loaded simultaneosly, 
           with up to one parameter at a time coming from a proc register.
        2. Independently of (1), trigger pulse according to cmd_time. Triggered pulse
           will always have the most recently loaded parameters.

    The phase, freq, and env words to load should in general be provided by an HWConfig 
    instance, but can be found manually.

    TODO: consider refactoring to not have hardcoded parameter widths/positions...
    i.e. if different siggen blocks needed more/less bits

    Parameters
    ----------
        freq_word : int
            word encoding the pulse carrier frequency 
            (usually (f/sample_rate)*2**NBITS)
        phase : float
            word encoding initial carrier phase 
        env_start_addr : int
            start address of pulse envelope
        env_word : int
            word describing env address and duration
            (initial version is 12 bit MSB ...)

    """
    cmd = 0
    if cfg_word is not None:
        assert 0 <= cfg_word < 2**pulse_field_widths['cfg']
        cmd += (int(cfg_word) + 2**4) << pulse_field_pos['cfg']
    if amp_word is not None:
        assert amp_regaddr is None
        assert 0 <= amp_word < 2**pulse_field_widths['amp']
        cmd += (int(amp_word) + 2**17) << pulse_field_pos['amp']
    if freq_word is not None:
        assert freq_regaddr is None
        assert 0 <= freq_word < 2**pulse_field_widths['freq']
        cmd += (int(freq_word) + 2**10) << pulse_field_pos['freq']
    if phase_word is not None:
        assert phase_regaddr is None
        assert 0 <= phase_word < 2**pulse_field_widths['phase']
        cmd += (int(phase_word) + 2**18) << pulse_field_pos['phase']
    if env_word is not None:
        assert env_regaddr is None
        assert 0 <= env_word < 2**pulse_field_widths['env_word']
        cmd += (int(env_word) + 2**25) << pulse_field_pos['env_word']
    if freq_regaddr is not None:
        assert phase_regaddr is None and env_regaddr is None and amp_regaddr is None
        assert 0 <= freq_regaddr < 16
        cmd += int(freq_regaddr) << 116
        cmd += 0b11 << pulse_field_pos['freq'] + pulse_field_widths['freq'] #(37 + 5 + 18 + 9) #enable write + reg_mux
    if phase_regaddr is not None:
        assert freq_regaddr is None and env_regaddr is None and amp_regaddr is None
        assert 0 <= phase_regaddr < 16
        cmd += int(phase_regaddr) << 116
        cmd += 0b11 << pulse_field_pos['phase'] + pulse_field_widths['phase'] #(37 + 5 + 18 + 9) #enable write + reg_mux
    if amp_regaddr is not None:
        assert freq_regaddr is None and env_regaddr is None and phase_regaddr is None
        assert 0 <= amp_regaddr < 16
        cmd += int(amp_regaddr) << 116
        cmd += 0b11 << pulse_field_pos['amp'] + pulse_field_widths['amp'] #(37 + 5 + 18 + 9) #enable write + reg_mux
    if env_regaddr is not None:
        assert freq_regaddr is None and phase_regaddr is None and amp_regaddr is None
        assert 0 <= env_regaddr < 16
        cmd += int(env_regaddr) << 116
        cmd += 0b11 << pulse_field_pos['env_word'] + pulse_field_widths['env_word'] #(37 + 5 + 18 + 9) #enable write + reg_mux

    if cmd_time is not None:
        cmd += int(cmd_time) << pulse_field_pos['cmd_time']
        assert 0 <= cmd_time < 2**pulse_field_widths['cmd_time']
        opcode = opcodes['pulse_write_trig']
    else:
        opcode = opcodes['pulse_write']

    cmd += (opcode << 123)
    return cmd


def reg_alu_i(value, alu_op, reg_addr, reg_write_addr):
    """
    Returns 128-bit command corresponding to:
        *reg_write_addr = value <alu_op> *reg_addr
    
    Parameters
    ----------
        value : int (max 32 bit, signed or unsigned)
        alu_op : str
            one of: 'id', 'add', 'sub', 'eq', 'le', 'ge'
        reg_addr : int (unsigned, max 4 bit)
        reg_write_addr : int (unsigned, max 4 bit)

    Returns
    -------
        cmd : int
            128 bit command
    """
    opcode = (opcodes['reg_alu_i'] << 3) + alu_opcodes[alu_op]
    #print('reg_fn_opcode:', bin(opcode))
    return (opcode << 120) + (twos_complement(value) << 88) + (reg_addr << 84) + (reg_write_addr << 80)

def reg_alu(reg_addr0, alu_op, reg_addr1, reg_write_addr):
    """
    Returns 128-bit command corresponding to:
        *reg_write_addr = *reg_addr0 <alu_op> *reg_addr1
    
    Parameters
    ----------
        reg_addr0 : int (unsigned, max 4 bit)
        alu_op : str
            one of: 'id', 'add', 'sub', 'eq', 'le', 'ge'
        reg_addr1 : int (unsigned, max 4 bit)
        reg_write_addr : int (unsigned, max 4 bit)

    Returns
    -------
        cmd : int
            128 bit command
    """
    opcode = (opcodes['reg_alu_i'] << 3) + alu_opcodes[alu_op]
    return (opcode << 120) + (reg_addr0 << 116) + (reg_addr1 << 84) + (reg_write_addr << 80)

def jump_i(instr_ptr_addr):
    opcode = opcodes['jump_i'] << 3
    return (opcode << 120) + (instr_ptr_addr << 68)

def jump_cond_i(value, alu_op, reg_addr, instr_ptr_addr):
    """
    Returns 128-bit command corresponding to a conditional
        jump to instr_ptr_addr if:
            value <alu_op> *reg_addr1 evaluates to true
    
    Parameters
    ----------
        value : int (max 32 bit, signed or unsigned)
        alu_op : str
            one of: 'eq', 'le', 'ge'
        reg_addr : int (unsigned, max 4 bit)
        reg_write_addr : int (unsigned, max 4 bit)
        instr_ptr_addr : int (unsigned max 8 bit)

    Returns
    -------
        cmd : int
            128 bit command
    """
    assert alu_op == 'eq' or alu_op == 'le' or alu_op == 'ge'
    opcode = (opcodes['jump_cond_i'] << 3) + alu_opcodes[alu_op]
    return (opcode << 120) + (twos_complement(value) << 88) + (reg_addr << 84) + (instr_ptr_addr << 68)

def jump_cond(reg_addr0, alu_op, reg_addr1, instr_ptr_addr):
    """
    Returns 128-bit command corresponding to a conditional
        jump to instr_ptr_addr if:
            value <alu_op> *reg_addr1 evaluates to true
    
    Parameters
    ----------
        reg_addr : int (unsigned, max 4 bit)
        alu_op : str
            one of: 'eq', 'le', 'ge'
        reg_addr : int (unsigned, max 4 bit)
        reg_write_addr : int (unsigned, max 4 bit)
        instr_ptr_addr : int (unsigned max 8 bit)

    Returns
    -------
        cmd : int
            128 bit command
    """
    assert alu_op == 'eq' or alu_op == 'le' or alu_op == 'ge'
    opcode = (opcodes['jump_cond_i'] << 3) + alu_opcodes[alu_op]
    return (opcode << 120) + (reg_addr0 << 116) + (reg_addr1 << 84) + (instr_ptr_addr << 68)

def inc_qclk_i(inc_val):
    opcode = (opcodes['inc_qclk_i'] << 3) + alu_opcodes['add']
    return (opcode << 120) + (twos_complement(inc_val) << 88)

def inc_qclk(inc_reg_addr):
    opcode = (opcodes['inc_qclk'] << 3) + alu_opcodes['add']
    return (opcode << 120) + (inc_reg_addr << 116)

def alu_fproc(func_id, alu_reg_addr, alu_op, write_reg_addr):
    opcode = (opcodes['alu_fproc'] << 3) + alu_opcodes[alu_op]
    return (opcode << 120) + (alu_reg_addr << 116) + (write_reg_addr << 80) + (func_id << 52)

def read_fproc(func_id, write_reg_addr):
    """
    This is an alias of alu_fproc
    """
    return alu_fproc(func_id, 0, 'id1', write_reg_addr)

def jump_fproc(func_id, alu_reg_addr, alu_op, instr_ptr_addr):
    opcode = (opcodes['jump_fproc'] << 3) + alu_opcodes[alu_op]
    return (opcode << 120) + (alu_reg_addr << 116) + (instr_ptr_addr << 76) + (func_id << 52)

def jump_fproc_i(func_id, value, alu_op, instr_ptr_addr):
    opcode = (opcodes['jump_fproc_i'] << 3) + alu_opcodes[alu_op]
    return (opcode << 120) + (value << 88) + (instr_ptr_addr << 76) + (func_id << 52)

def alu_cmd(optype, im_or_reg, alu_in0, alu_op=None, alu_in1=0, write_reg_addr=None, jump_cmd_ptr=None, func_id=None):
    """
    This is a general function for generating the following types of instructions:
        reg_(i)alu, jump_cond(i), alu_fproc(i), jump_fproc(i), inc_qclk(i)

    Parameters
    ----------
        optype : str
            one of: reg_alu, jump_cond, alu_fproc, jump_fproc
        im_or_reg : str
            'i' for immediate instruction and 'r' for register based
        alu_in0 : int
            if immediate, value; if register, reg addr
        alu_op : str
            alu opcode
        alu_in1 : int
            alu reg addr
        write_reg_addr : int
            reg address to write alu output
        jump_cmd_ptr : int
        func_id : int
    """
    cmd = 0
    if optype in ['reg_alu', 'jump_cond']: #these have alu_in1 from reg
        cmd += alu_in1 << 84
    if optype in ['alu_fproc', 'jump_fproc']:
        if func_id is not None:
            cmd += func_id << 52
    if optype in ['jump_cond', 'jump_fproc']:
        cmd += jump_cmd_ptr << 68
    if optype in ['reg_alu', 'alu_fproc']:
        cmd += write_reg_addr << 80
    if optype == 'inc_qclk':
        assert alu_op is None or alu_op == 'add'
        alu_op = 'add'

    if im_or_reg == 'i':
        opkey = optype + '_i'
        cmd += twos_complement(alu_in0) << 88
    else:
        opkey = optype
        cmd += alu_in0 << 116

    opcode = (opcodes[opkey] << 3) + alu_opcodes[alu_op]
    cmd += opcode << 120

    return cmd

def idle(cmd_time):
    cmd = cmd_time << pulse_field_pos['cmd_time']
    assert cmd_time < 2**pulse_field_widths['cmd_time']
    cmd += opcodes['idle'] << 123
    return cmd

def done_cmd():
    return opcodes['done'] << 123

def pulse_reset():
    return opcodes['pulse_reset'] << 123

def sync(barrier_id):
    return (opcodes['sync'] << 123) + (barrier_id << 112)

def get_phase_word(phase: float) -> int:
    """
    Converts phase to 17 bit unsigned int, normalized to 2*pi
    (i.e. 2*pi -> 2**17)
    Parameters
    ----------
    phase: float
        input phase (in radians)

    Returns
    -------
    int:
        17-bit phase word
    """
    phase = int(((phase % (2 * np.pi)) / (2 * np.pi)) * 2 ** pulse_field_widths['phase'])
    return phase % 2 ** pulse_field_widths['phase']

def get_amp_word(amplitude: float) -> int:
    """
    Converts amplitude (normalized to 1) into command word for FPGA

    Parameters
    ----------
    amplitude: float

    Returns
    -------
    int:
        amplitude word
        
    """
    return int(twos_complement(amplitude * (2 ** (pulse_field_widths['amp'] - 1) - 1), nbits=pulse_field_widths['amp']))

def twos_complement(value, nbits=32):
    """
    Returns the nbits twos complement value of a standard signed python 
    integer or list of ints

    Parameters
    ----------
        value : int or list of ints
        nbits : int (positive)

    Returns
    -------
        int or list of ints
    """
    if isinstance(value, list) or isinstance(value, np.ndarray):
        value_array = np.array(value)
    else:
        value_array = np.array([value])

    if np.any((value_array > (2**(nbits-1) - 1)) | (value_array < (-2**(nbits-1)))):
        raise Exception('{} out of range'.format(value))

    posmask = value_array >= 0
    negmask = value_array < 0

    value_array[negmask] = 2**nbits + value_array[negmask]

    if np.any(value_array) < 0:
        raise Exception('Overflow, probably related to input dtype')

    if not (isinstance(value, list) or isinstance(value, np.ndarray)):
        return int(value_array[0])
    else:
        return value_array



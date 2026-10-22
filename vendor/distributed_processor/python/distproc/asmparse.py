import numpy
from distproc.command_gen import pulse_field_pos
def signval(v,width=16):
    return int(v-2**width) if (v>>(width-1))&1 else v
def sign16(v):
    #return int(v-65536) if (v>>15)&1 else v
    return signval(v,16)
def sign32(v):
    return signval(v,32)
vsign16=numpy.vectorize(sign16)
vsign32=numpy.vectorize(sign32)
def cmdparse(cmdbuf):
    """
    Parse cmd buffer generated from the assembler

    Parameters
    ----------
        cmdbuf: bytes
            compiled command buffer
    Returns
    ----------
        list of str

    """
    dt=numpy.dtype(numpy.uint32)
    dt=dt.newbyteorder('little')
    cmd=numpy.frombuffer(cmdbuf,dtype=dt)
    parsed_cmds=[]
    for i in range(len(cmd)//4):
        cmd128=0xffffffffffffffffffffffffffffffff
        for j in [3,2,1,0]:
            cmd128=((cmd128<<32)&0xffffffffffffffffffffffffffffffff)+cmd[i*4+j]
        opcode=(cmd128>>123)&0x1f
        cmdtime=(cmd128>>pulse_field_pos['cmd_time'])&0xffffffff
        cfg=(cmd128>>pulse_field_pos['cfg'])&0xf
        amp=(cmd128>>pulse_field_pos['amp'])&0xffff
        freq=(cmd128>>pulse_field_pos['freq'])&0x1ff
        phase=(cmd128>>pulse_field_pos['phase'])&0x1ffff
        env_word=(cmd128>>pulse_field_pos['env_word'])&0xffffff
        env_start=(env_word>>0)&0xfff
        env_length=(env_word>>12)&0xfff
        parsed_cmds.append({'opcode': opcode, 'cmdtime': cmdtime, 'amp': amp, 'freq': freq, 'phase': phase, 'env_start': env_start, 'env_length': env_length, 'cfg': cfg})
        #(f"{opcode=:05b},{cmdtime=:08x},{cfg=:01x},{amp=:04x},{freq=:05x},{phase=:05x},{env_start=:03x},{env_length=:03x}")
    return parsed_cmds

def envparse(envbuf):
    """
    Parse envelope buffer generated from the assembler

    Parameters
    ----------
        cmdbuf: bytes
            compiled envelope buffer
    Returns
    ----------
        complex numpy array
    """
    dt=numpy.dtype(numpy.uint32)
    dt=dt.newbyteorder('little')
    env=numpy.frombuffer(envbuf,dtype=dt)
    envr=vsign16(env>>16)
    envi=vsign16(env&0xffff)
    return envr+1j*envi
def freqparse(freqbuf,fsamp=500e6):
    """
    Parse frequency buffer generated from the assembler

    Parameters
    ----------
        freqbuf: bytes
            compiled frequency buffer
        fsamp: float
            Sampling frequency
    Returns
    ----------
        Dictionary with two keys:
            freq: float frequency
            iq15: numpy array for the 15 i/q offset
    """
    dt=numpy.dtype(numpy.uint32)
    dt=dt.newbyteorder('little')
    freq16=numpy.frombuffer(freqbuf,dtype=dt).reshape([-1,16])
    freq=freq16[:,0]/2**32*fsamp
    iq15r=vsign16((freq16[:,1:]>>16)&0xffff)
    iq15i=vsign16(freq16[:,1:].astype(numpy.int32)&0xffff)
    return dict(freq=freq,iq15=iq15r+1j*iq15i)

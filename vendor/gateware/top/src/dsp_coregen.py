from abc import abstractproperty, ABC, abstractmethod
from typing import Dict, List, Tuple
from attrs import field, define

DAC_NBITS = 16
ADC_NBITS = 16
INSTR_MEM_WIDTH = 128

@define
class Memory:
    name: str
    depth: int
    type: str #read or write
    pl_width: int #width at PL (fabric) in bits; PS width is always 32-bit

# for ADC/DAC signals
@define
class Signal:
    local_name: str
    global_name: str

@define
class Port:
    local_name: str
    global_name: str
    type: str # input or output
    width: int
    indexed: bool = False # true if separate signal is instantiated for each core
    dspif: bool = True # true if this is propagated to dspif


class SigGen(ABC):

    def __init__(self):
        pass

    @abstractproperty
    def read_mems(self):
        pass

    @abstractproperty
    def write_mems(self):
        pass

    @abstractproperty
    def read_mem_names(self):
        pass

    @abstractproperty
    def write_mem_names(self):
        pass

    @abstractmethod
    def generate_body_code(self):
        pass

    @abstractmethod
    def name(self):
        pass

    @property
    def output_signals(self):
        """
        This is assumed to have datawidth
        DAC_AXIS_DATAWIDTH
        """
        return []

    @property
    def input_signals(self):
        return []

    @property
    def misc_io_ports(self) -> List[Port]:
        return []

    @property
    def busy_signal(self):
        return None


class DCOffsSigGen(SigGen):

    def __init__(self, name, corename, index, delay=None):
        self._name = name
        self._corename = corename
        self.index = index
        self.delay = delay

    @property
    def read_mems(self):
        return []

    @property
    def name(self):
        return self._name

    @property
    def write_mems(self):
        return []

    @property
    def read_mem_names(self):
        return []

    @property
    def write_mem_names(self):
        return []

    @property
    def output_signals(self):
        return [Signal(f'{self._name}_out', f'{self._corename}_{self._name}')]

    def generate_body_code(self):
        return \
            f'    // code for DCOffsetSigGen {self._name}\n' \
            f'    reg dc_offset_strobe; \n' \
            f'    reg[AMP_WIDTH-1:0] dc_offset_amplitude; \n\n' \
            f'    dc_offset #(.NBITS(AMP_WIDTH), .DELAY(44), .SAMPLES_PER_CLK(16)) dcoffs(.amplitude(dc_offset_amplitude), \n' \
            f'        .clk(clk), .enable(dc_offset_strobe), .reset(0), .dc_out({self.output_signals[0].local_name})); \n\n' \
            f'    always @(posedge clk) begin \n' \
            f"        dc_offset_strobe <= pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b{bin(self.index)[2:]}); \n" \
            f"        if (pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b{bin(self.index)[2:]})) \n" \
            f"            dc_offset_amplitude <= pulseout.amp; \n" \
            f"    end\n\n"


class RFSigGen(SigGen):

    def __init__(self, name, corename, index, env_mem_depth, freq_mem_depth, interp_ratio=1, samples_per_clk=16, delay=None):
        self._name = name
        self._corename = corename
        self.index = index
        self.env_mem = Memory(f'{self._corename}_{self._name}_env', env_mem_depth, 'read',
                              samples_per_clk * DAC_NBITS * 2 // interp_ratio)
        self.freq_mem = Memory(f'{self._corename}_{self._name}_freq', freq_mem_depth, 
                              'read', samples_per_clk*DAC_NBITS*2)
        self.interp_ratio = interp_ratio
        self.samples_per_clk = samples_per_clk
        self.delay = delay

    @property
    def env_mem_name(self):
        return self.env_mem.name

    @property
    def freq_mem_name(self):
        return self.freq_mem.name

    @property
    def read_mem_names(self):
        return [self.env_mem_name,
                self.freq_mem_name]

    @property
    def write_mem_names(self):
        return []

    @property
    def write_mems(self):
        return []

    @property
    def read_mems(self):
        return [self.env_mem, self.freq_mem]

    @property
    def output_signals(self):
        return [Signal(f'{self._name}_out', f'{self._corename}_{self._name}')]

    @property
    def name(self):
        return self._name

    def _generate_sig_gen_code(self):
        return \
            f'    // code for RFSigGen {self._name}\n' \
            f'    ifelement #(.ENV_ADDRWIDTH({self.env_mem_name.upper()}_R_ADDRWIDTH),.ENV_DATAWIDTH({self.env_mem_name.upper()}_R_DATAWIDTH), \n' \
            f'        .FREQ_ADDRWIDTH({self.freq_mem_name.upper()}_R_ADDRWIDTH),.FREQ_DATAWIDTH({self.freq_mem_name.upper()}_R_DATAWIDTH),.TCNTWIDTH(TCNTWIDTH)) \n' \
            f'        {self._name}_elem(.clk(clk)); \n\n' \
            f'    always @(posedge clk) begin \n' \
            f'        {self._name}_elem.reset <= pulseout.reset; \n' \
            f"        {self._name}_elem.cmdstb <= pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b{bin(self.index)[2:]}); \n" \
            f"        if (pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b{bin(self.index)[2:]}))begin \n" \
            f"            {self._name}_elem.envstart<=pulseout.env_word[11:0]; \n" \
            f"            {self._name}_elem.envlength<=pulseout.env_word[23:12]; \n" \
            f"            {self._name}_elem.ampx<=pulseout.amp; \n" \
            f"            {self._name}_elem.ampy=16'd0; \n" \
            f"            {self._name}_elem.freqaddr<=pulseout.freq; \n" \
            f"            {self._name}_elem.pini<=pulseout.phase; \n" \
            f"            {self._name}_elem.mode<=pulseout.cfg[3:2]; \n" \
            f"        end \n" \
            f"    end \n\n" \
            f'    elementconn #(.ENV_ADDRWIDTH({self.env_mem_name.upper()}_R_ADDRWIDTH),.ENV_DATAWIDTH({self.env_mem_name.upper()}_R_DATAWIDTH), .INTPRATIO({self.interp_ratio}), \n' \
            f'        .FREQ_ADDRWIDTH({self.freq_mem_name.upper()}_R_ADDRWIDTH),.FREQ_DATAWIDTH({self.freq_mem_name.upper()}_R_DATAWIDTH)) \n' \
            f'        {self._name}_elemconn(.elem({self._name}_elem),.envaddr(addr_{self.env_mem_name}),.envdata(data_{self.env_mem_name}), \n' \
            f'        .freqaddr(addr_{self.freq_mem_name}),.freqdata(data_{self.freq_mem_name})); \n\n' \
    
    def generate_body_code(self):
        return self._generate_sig_gen_code() + \
            f'    elementout #(.ENV_ADDRWIDTH({self.env_mem_name.upper()}_R_ADDRWIDTH),.ENV_DATAWIDTH({self.env_mem_name.upper()}_R_DATAWIDTH), \n' \
            f'        .FREQ_ADDRWIDTH({self.freq_mem_name.upper()}_R_ADDRWIDTH),.FREQ_DATAWIDTH({self.freq_mem_name.upper()}_R_DATAWIDTH)) \n' \
            f'        {self._name}_elem_out (.elem({self._name}_elem),.valid(),.multix({self.output_signals[0].local_name}),.multiy()); \n\n' \

    @property
    def busy_signal(self):
        return f'{self._name}_elem.busy'

class RFMixSigGen(RFSigGen):

    def __init__(self, name, corename, index, env_mem_depth, freq_mem_depth, acc_mem_depth, interp_ratio=1, samples_per_clk=4, delay=None):
        super().__init__(name, corename, index, env_mem_depth, freq_mem_depth, interp_ratio, samples_per_clk, delay)
        self.acc_mem = Memory(f'{self._corename}_accbuf', acc_mem_depth, 'write', 64)

    @property
    def output_signals(self):
        return []

    @property
    def write_mem_names(self):
        return [self.acc_mem_name]

    @property
    def write_mems(self):
        return [self.acc_mem]

    @property
    def input_signals(self):
        return [Signal(f'{self._name}_in', f'{self._corename}_{self._name}')]

    @property
    def fproc_valid_port(self):
        return Port(f'fproc_data_valid', f'{self._corename}_{self._name}_fproc_data_valid', 'output', 1, True, False)

    @property
    def misc_io_ports(self):
        return [Port(f'acc_shift', 'acc_shift', 'input', 5, False),
                Port(f'resetacc', 'resetacc', 'input', 1, False),
                self.fproc_valid_port]

    @property
    def acc_mem_name(self):
        return self.acc_mem.name

    def generate_body_code(self):
        return self._generate_sig_gen_code() + \
            f'    wire accvalid; \n' \
            f'    elementmixacc #(.ENV_ADDRWIDTH({self.env_mem_name.upper()}_R_ADDRWIDTH),.ENV_DATAWIDTH({self.env_mem_name.upper()}_R_DATAWIDTH), \n' \
            f'                   .FREQ_ADDRWIDTH({self.freq_mem_name.upper()}_R_ADDRWIDTH),.FREQ_DATAWIDTH({self.freq_mem_name.upper()}_R_DATAWIDTH),.ACCADDWIDTH(16)) \n' \
            f'    {self._name}0mixacc1(.adcx({self.input_signals[0].local_name}),.adcy(0),.shift(acc_shift),.elem({self._name}_elem.mix),.gateout(), \n' \
            f'                .accx(data_{self.acc_mem_name}[63:32]),.accy(data_{self.acc_mem_name}[31:0]),.stbout(accvalid)); \n\n' \
            f'    wire locklast_accbuf; \n' \
            f'    reg [{self.acc_mem_name.upper()}_W_ADDRWIDTH-1:0] addr_{self.acc_mem_name}_r; \n' \
            f'    reg we_{self.acc_mem_name}_r; \n' \
            f'    reg fproc_data_valid_r; \n' \
            f'    assign addr_{self.acc_mem_name} = addr_{self.acc_mem_name}_r; \n' \
            f'    assign we_{self.acc_mem_name} = we_{self.acc_mem_name}_r; \n' \
            f'    assign fproc_data_valid = fproc_data_valid_r; \n' \
            f'    assign locklast_accbuf=&addr_{self.acc_mem_name}_r; \n\n' \
            f'    always @(posedge clk) begin \n' \
            f'      we_{self.acc_mem_name}_r <= accvalid & {self._name}_elem.mode[0]; \n' \
            f'      fproc_data_valid_r <= accvalid; \n' \
            f'      addr_{self.acc_mem_name}_r <= resetacc ? 0 : addr_{self.acc_mem_name}_r + (~locklast_accbuf & we_{self.acc_mem_name}_r); \n' \
            f'    end \n\n' \


class DSPCore:
    """
    defines and generates verilog for distributed proc core 
    + associated signal gen(s)
    """

    def __init__(self, name, instr_mem_depth, sig_gens=None):
        self._name = name
        self.sig_gens: List[SigGen] = [] if sig_gens is None else sig_gens
        self.instr_mem = Memory(f'{name}_command', instr_mem_depth, 'read', INSTR_MEM_WIDTH)

    @property
    def name(self):
        return self._name

    def generate_verilog(self):
        verilog_str = ''
        
        verilog_str += \
                f'// generated by dsp_coregen.py \n' \
                f'module {self._name}_core#( \n' \
                f'    `include "plps_para.vh", \n' \
                f'    `include "bram_para.vh", \n' \
                f'    `include "braminit_para.vh")'

        io_headerstr = \
                f'    input clk, \n' \
                f'    input reset, \n' \
                f'    input [{self.instr_mem.name.upper()}_R_DATAWIDTH-1:0] command, \n' \
                f'    output [{self.instr_mem.name.upper()}_R_ADDRWIDTH-1:0] cmd_read_addr, \n' 

        for gen in self.sig_gens:
            for mem in gen.read_mem_names:
                io_headerstr += \
                    f'    input [{mem.upper()}_R_DATAWIDTH-1:0] data_{mem}, \n' \
                    f'    output [{mem.upper()}_R_ADDRWIDTH-1:0] addr_{mem}, \n\n'

            for mem in gen.write_mem_names:
                io_headerstr += \
                    f'    output [{mem.upper()}_W_DATAWIDTH-1:0] data_{mem}, \n' \
                    f'    output [{mem.upper()}_W_ADDRWIDTH-1:0] addr_{mem}, \n' \
                    f'    output we_{mem}, \n\n'
            for port in gen.misc_io_ports:
                widthstr = '' if port.width == 1 else f'[{port.width-1}:0]'
                io_headerstr += \
                    f'    {port.type}{widthstr} {port.local_name}, \n'

            io_headerstr += '\n'

        for gen in self.sig_gens:
            for output in gen.output_signals:
                io_headerstr += \
                    f'    output[DAC_AXIS_DATAWIDTH-1:0] {output.local_name}, \n'
            for input in gen.input_signals:
                io_headerstr += \
                    f'    input[ADC_AXIS_DATAWIDTH-1:0] {input.local_name}, \n'

        io_headerstr += \
                f'    output [3:0] state_dbg, \n' \
                f'    output [3:0] nextstate_dbg, \n' \
                f'    output stbend, \n' \
                f'    output procdone_mon, \n' \
                f'    output nobusy_mon, \n' \
                f'    fproc_iface.proc fproc'

        verilog_str += '(\n' + io_headerstr + ');\n\n'

        verilog_str += \
                f'    localparam TCNTWIDTH=27; \n' \
                f'    localparam ENV_WIDTH = 24; \n' \
                f'    localparam PHASE_WIDTH = 17; \n' \
                f'    localparam FREQ_WIDTH = 9; \n' \
                f'    localparam AMP_WIDTH = 16; \n' \
                f'    localparam CFG_WIDTH = 4; \n' \
                f'    localparam SYNC_BARRIER_WIDTH=8; \n' \
                f'    localparam REG_ADDR_WIDTH=4; \n' \
                f'    localparam CMD_WIDTH=128; \n' \
                f'    localparam CMD_ADDR_WIDTH=16; \n' \
                f'    localparam DATA_WIDTH=32; \n' \
                f'     \n' \
                f'    cmd_mem_iface #(.CMD_ADDR_WIDTH(16), .MEM_WIDTH(128), .MEM_TO_CMD(1)) memif(); \n' \
                f'    //fproc_iface #(.FPROC_ID_WIDTH(8), .FPROC_RESULT_WIDTH(32)) fproc(); \n' \
                f'    sync_iface #(.SYNC_BARRIER_WIDTH(8)) sync(); \n' \
                f'    pulse_iface #(.PHASE_WIDTH(PHASE_WIDTH), .FREQ_WIDTH(FREQ_WIDTH),.ENV_WORD_WIDTH(ENV_WIDTH), .AMP_WIDTH(AMP_WIDTH), .CFG_WIDTH(CFG_WIDTH))  \n' \
                f'    pulseout(); \n' \
                f' \n'\
                f'    wire procdone; \n' \
                f'    proc #(.DATA_WIDTH(DATA_WIDTH), .CMD_WIDTH(CMD_WIDTH),.CMD_ADDR_WIDTH(CMD_ADDR_WIDTH), .REG_ADDR_WIDTH(REG_ADDR_WIDTH),.SYNC_BARRIER_WIDTH(SYNC_BARRIER_WIDTH),.CMD_MEM_READ_LATENCY(3))  \n' \
                f'    dproc(.clk(clk), .reset(reset),.cmd_iface(memif), .fproc(fproc), .sync(sync), .pulseout(pulseout),.done_gate(procdone)); \n' \
                f'    reg [127:0] command_d=0; \n' \
                f'    reg [127:0] command_d2=0; \n' \
                f'    reg [15:0] addr_command=0; \n' \
                f'    always @(posedge clk) begin \n' \
                f'      command_d<=command; \n' \
                f'      command_d2<=command_d; \n' \
                f'      addr_command<=memif.instr_ptr; \n' \
                f'    end \n' \
                f'    assign memif.mem_bus[0]=command; \n' \
                f'    assign cmd_read_addr=addr_command; \n\n' 


        for gen in self.sig_gens:
            verilog_str += gen.generate_body_code()

        verilog_str += \
                f'    reg nobusy; \n'\
                f'    reg noop; \n'\
                f'    always @(posedge clk) begin \n' \
                f'        nobusy <= ~|{{' + ', '.join([f'{gen.busy_signal}' for gen in self.sig_gens 
                                                  if gen.busy_signal is not None]) + '}; \n'\
                f'        noop<=~|command;\n'\
                f'    end\n\n'
        verilog_str += \
                f'  assign stbend=procdone; \n' \
                f'  assign procdone_mon=procdone; \n' \
                f'  assign nobusy_mon=nobusy; \n' 

        verilog_str += 'endmodule'

        return verilog_str

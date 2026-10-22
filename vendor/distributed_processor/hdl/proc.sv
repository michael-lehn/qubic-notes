/**
* Top level distributed processor module. Child modules:
*   - ctrl.v: FSM and instruction paths
*   - alu.v
*   - qclk.v: pulse timing reference, reset at the beginning of program (every
*   shot)
*   - instr_ptr.v: controls set/reset/increment of instruction mem pointer
*   - pulse_iface.sv: interface to QubiC sig gen
*   (qubic-gateware/dsp/element.sv)
*   - pulse_reg.sv: special pulse parameter register
*   - fproc_iface.sv: interface to FPROC
*
*/


//NOTE: reset should be asserted for at least two clock cycles!
module proc
    #(parameter DATA_WIDTH=32,
      parameter CMD_WIDTH=128,
      parameter CMD_ADDR_WIDTH=8,
      parameter REG_ADDR_WIDTH=4,
      parameter SYNC_BARRIER_WIDTH=8,
      parameter DAC_SAMPLES_PER_CLK=4,
      parameter CMD_MEM_READ_LATENCY=3)(
      input clk,
      input reset,
      cmd_mem_iface cmd_iface,
      sync_iface.proc sync,
      fproc_iface.proc fproc,
      pulse_iface.proc pulseout,
      output done_gate);

    //`include "../hdl/instr_params.vh" //todo: debug includes
    //`include "../hdl/ctrl_params.vh"
    localparam OPCODE_WIDTH = 8;
    localparam ALU_OPCODE_WIDTH = 3;
    //localparam PULSE_OUT_WIDTH = 72;
    localparam PULSE_CMD_I_WIDTH = pulseout.ENV_WORD_WIDTH + pulseout.PHASE_WIDTH + pulseout.FREQ_WIDTH + pulseout.AMP_WIDTH + pulseout.CFG_WIDTH + 9;
    //localparam INST_PTR_SYNC_EN = 2'b01;
    //localparam INST_PTR_FPROC_EN = 2'b10;
    //localparam INST_PTR_DEFAULT_EN = 2'b00;

    //datapath wires
    wire[CMD_WIDTH-1:0] cmd_buf_out;
    wire[CMD_ADDR_WIDTH-1:0] cmd_buf_read_addr;
    wire[DATA_WIDTH-1:0] alu_out, reg_file_out0, reg_file_out1, alu_in0, alu_in1, qclk_out, qclk_in;
    wire[PULSE_CMD_I_WIDTH-1:0] pulse_cmd_i;

    //pulse datapath wires
    wire phase_write_en, phase_write_en_cmd;
    wire freq_write_en, freq_write_en_cmd;
    wire env_write_en, env_write_en_cmd;
    wire phase_write_sel; //0 for i, 1 for r
    wire freq_write_sel;
    wire env_write_sel;

    assign cmd_buf_out = cmd_iface.cmd_read;
    
    //control wires
    wire[ALU_OPCODE_WIDTH-1:0] alu_opcode;
    wire c_strobe_enable;
    wire qclk_trig_enable;
    wire alu_in0_sel;
    wire[1:0] alu_in1_sel;
    wire reg_write_en;
    //wire reg_write_sel;
    wire[1:0] inst_ptr_en_sel;
    wire[1:0] inst_ptr_load_en_sel;
    wire qclk_load_en; //enable loading new value in qclk
    reg cstrobe;
    reg qclk_trig; //when qclk_out matches cmd_time

    wire write_pulse_en; //enable writes to the local pulse register
    wire instr_load_en; //enable loading a new command into local buffer for decoding
    wire qclk_reset; //global qclk reset
    wire qclk_reset_ctrl; //qclk reset from control unit (currently just sync interface)

    wire inst_ptr_load_en; //enable loading a new address into the instruction pointer
    wire inst_ptr_enable; //enable the instruction pointer to increment/output a new value

    //local cmd buffer
    reg[CMD_WIDTH-1:0] local_cmd;
    always @(posedge clk) begin
        if(instr_load_en)
            local_cmd <= cmd_buf_out;
    end


    //cmd buffer datapath shorthands
    wire[CMD_ADDR_WIDTH-1:0] instr_ptr_load_val;
    wire[DATA_WIDTH-1:0] alu_cmd_data_in0;
    wire[DATA_WIDTH-1:0] pulse_cmd_time;
    wire[REG_ADDR_WIDTH-1:0] reg_addr_in0;
    wire[REG_ADDR_WIDTH-1:0] reg_addr_in1;
    wire[REG_ADDR_WIDTH-1:0] reg_write_addr;

    localparam INSTR_PTR_LSB = CMD_WIDTH-ALU_INPUT_SPACE-16;
    localparam FPROC_LSB = CMD_WIDTH-ALU_INPUT_SPACE-32;

    localparam ALU_INPUT_SPACE = OPCODE_WIDTH + DATA_WIDTH + REG_ADDR_WIDTH; //datapath reserved for ALU inputs (both immediate and reg addressed)
    assign instr_ptr_load_val = local_cmd[INSTR_PTR_LSB + CMD_ADDR_WIDTH - 1 : INSTR_PTR_LSB];
    assign alu_cmd_data_in0 = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH:CMD_WIDTH-OPCODE_WIDTH-DATA_WIDTH]; // data_in0 and addr_in0 overlap since you always 
    assign reg_addr_in0 = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH:CMD_WIDTH-OPCODE_WIDTH-REG_ADDR_WIDTH]; //     choose between one or the other
    assign reg_addr_in1 = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH-DATA_WIDTH:CMD_WIDTH-OPCODE_WIDTH-DATA_WIDTH-REG_ADDR_WIDTH]; 
    assign reg_write_addr = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH-DATA_WIDTH-REG_ADDR_WIDTH:CMD_WIDTH-OPCODE_WIDTH-DATA_WIDTH-2*REG_ADDR_WIDTH]; 
    //assign cmd_out = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH-DATA_WIDTH:CMD_WIDTH-OPCODE_WIDTH-DATA_WIDTH-PULSE_OUT_WIDTH];

    //pulse datapath
    assign pulse_cmd_time = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH-REG_ADDR_WIDTH-PULSE_CMD_I_WIDTH:
                            CMD_WIDTH-OPCODE_WIDTH-REG_ADDR_WIDTH-PULSE_CMD_I_WIDTH-DATA_WIDTH];
    assign pulse_cmd_i = local_cmd[CMD_WIDTH-1-OPCODE_WIDTH-REG_ADDR_WIDTH:CMD_WIDTH-OPCODE_WIDTH-REG_ADDR_WIDTH-PULSE_CMD_I_WIDTH];

    //other datapath connections
    assign qclk_in = alu_out;
    assign fproc.id = local_cmd[FPROC_LSB + fproc.FPROC_ID_WIDTH - 1 : FPROC_LSB];

    //conditional assignments from control bits
    assign alu_in0 = alu_in0_sel ?  reg_file_out0 : alu_cmd_data_in0;
    assign alu_in1 = alu_in1_sel[1] ? fproc.data : (alu_in1_sel[0] ? reg_file_out1 : qclk_out);
    //always @(*) begin
    //    if (alu_in1_sel == ALU_IN1_REG_SEL)
    //        alu_in1 = reg_file_out1;
    //    else if(alu_in1_sel == ALU_IN1_QCLK_SEL)
    //        alu_in1 = qclk_out;
    //    else
    //        alu_in1 = fproc_data;
    //end
    //

    reg reset_reg; // global reset buffer:

    assign inst_ptr_load_en = inst_ptr_load_en_sel[1] ? alu_out[0] : inst_ptr_load_en_sel[0]; //MSB selects ALU output
    reg [4:0] reset_sr=0;
    reg dummy_resetsr=0;
    always @(posedge clk) begin
        reset_reg <= reset;
	    {dummy_resetsr,reset_sr}<={reset_sr,reset_reg};
        qclk_trig <= (qclk_out == pulse_cmd_time) && qclk_trig_enable; //todo: this could cause issues, investigate
        cstrobe <= (qclk_out == pulse_cmd_time) && c_strobe_enable;
    end


    //qclk reset logic
    assign qclk_reset = qclk_reset_ctrl || (|reset_sr[3:0]);

    //instantiate modules
    //cmd_mem #(.CMD_WIDTH(CMD_WIDTH), .ADDR_WIDTH(CMD_ADDR_WIDTH)) cmd_buffer(
    //          .clk(clk), .write_enable(write_prog_enable), .read_address(cmd_buf_read_addr),
    //          .write_address(cmd_addr), .cmd_in(cmd_data), .cmd_out(local_cmd));
    instr_ptr #(.WIDTH(CMD_ADDR_WIDTH)) instr(.clk(clk), .enable(inst_ptr_enable), .reset(reset_reg),
              .load_val(instr_ptr_load_val), .load_enable(inst_ptr_load_en), .ptr_out(cmd_iface.instr_ptr));
    reg_file #(.DATA_WIDTH(DATA_WIDTH), .ADDR_WIDTH(REG_ADDR_WIDTH)) regs(
              .clk(clk), .read_addr_0(reg_addr_in0), .read_addr_1(reg_addr_in1),
              .write_addr(reg_write_addr), .write_data(alu_out), .write_enable(reg_write_en),
              .reg_0_out(reg_file_out0), .reg_1_out(reg_file_out1));
    ctrl #(.MEM_READ_CYCLES(CMD_MEM_READ_LATENCY)) ctu(.clk(clk), .reset(reset_reg), .opcode(local_cmd[CMD_WIDTH-1:CMD_WIDTH-OPCODE_WIDTH]), 
              .alu_opcode(alu_opcode), .c_strobe_enable(c_strobe_enable), .fproc_ready(fproc.ready), .sync_ready(sync.ready), 
              .alu_in0_sel(alu_in0_sel), .alu_in1_sel(alu_in1_sel), .reg_write_en(reg_write_en), .instr_ptr_en(inst_ptr_enable), 
              .instr_ptr_load_en(inst_ptr_load_en_sel), .qclk_load_en(qclk_load_en), .qclk_reset(qclk_reset_ctrl), .qclk_trig_in(qclk_trig), 
              .instr_load_en(instr_load_en), .sync_enable(sync.enable), .fproc_enable(fproc.enable), .write_pulse_en(write_pulse_en), 
              .done_gate(done_gate), .pulse_reset(pulseout.reset), .qclk_trig_enable(qclk_trig_enable));
    alu #(.DATA_WIDTH(DATA_WIDTH)) myalu(.clk(clk), .ctrl(alu_opcode), .in0(alu_in0), .in1(alu_in1), .out(alu_out));
    qclk #(.WIDTH(DATA_WIDTH)) myclk(.clk(clk), .rst(qclk_reset), .in_val(qclk_in), .load_enable(qclk_load_en), .out(qclk_out)); //todo: implement sync reset logic
    pulse_reg #(.DATA_WIDTH(DATA_WIDTH)) pulsereg(.clk(clk), .pulse_cmd_in(pulse_cmd_i), .reg_in(reg_file_out0), 
        .pulse_write_en(write_pulse_en), .cstrobe_in(cstrobe), .pulseout(pulseout));

    //`ifdef COCOTB_SIM
    //initial begin
    //  $dumpfile ("proc.vcd");
    //    $dumpvars (3, proc);
    //  #1;
    //end
    //`endif





endmodule

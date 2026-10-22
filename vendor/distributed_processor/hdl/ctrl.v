/**
* Implements distributed processor FSM. 
*
* states:
*   MEM_WAIT_STATE: wait for MEM_READ_CYCLES for input instruction to become valid, then
*       assert instr_load_en to load the cmd from memory into the internal register. Transition
*       to DECODE_STATE
*   DECODE_STATE: new instruction clocked in; depending on opcode:
*       pulse_write:
*           - write pulse regs from cmd/regs, transition to MEM_WAIT_STATE
*       pulse_write_trig:
*           - write pulse regs from cmd/regs, wait for cstrobe, then transition to MEM_WAIT_STATE
*       ALU type:
*           - read regs/set up inputs to ALU, transition to next state
*       FPROC type:
*           - assert fproc_enable, transition to FPROC_WAIT state
*   ALU_PROC_STATE_0
*       - clock in ALU inputs
*       - transition to ALU_PROC_STATE_1
*   ALU_PROC_STATE_1
*       - clock out ALU results, set up inputs that use this (e.g. register writes, qclk loads,
*           instr_ptr_load_en (jumps))
*       - transition to MEM_WAIT_STATE
*   FPROC_WAIT_STATE
*       - check fproc_ready; 
*           - if 0 stay here
*           - if 1 setup ALU inputs, transition to ALU_PROC_STATE_0
*   SYNC_WAIT_STATE
*       - check sync_ready; 
*           - if 0 stay here
*           - if 1 transition to QCLK_RST_STATE
*   QCLK_RST_STATE
*       - reset qclk (qclk_reset)
*       - transition to MEM_WAIT_STATE
*   DONE_STATE
*       - assert done_gate, stay here until reset
*   SYNC_WAIT
*
*   instruction paths:
*       pulse_write: MEM_WAIT_STATE --> DECODE_STATE --> MEM_WAIT_STATE
*       pulse_write_trig: MEM_WAIT_STATE --> DECODE_STATE --qclk_trig_in--> MEM_WAIT_STATE
*       jump_i: MEM_WAIT_STATE --> DECODE_STATE --> MEM_WAIT_STATE
*       ALU type (reg_alu(r/i), jump_cond(r,i), inc_qclk(r,i): 
*           MEM_WAIT_STATE --> DECODE_STATE --> ALU_PROC_STATE_0 --> ALU_PROC_STATE_1 --> MEM_WAIT_STATE
*       FPROC type (alu_fproc, jump_fproc):
*           MEM_WAIT_STATE --> DECODE_STATE --> FPROC_WAIT_STATE --fproc_ready--> ALU_PROC_STATE_0 
*               --> ALU_PROC_STATE_1 --> MEM_WAIT_STATE
*       SYNC:
*           MEM_WAIT_STATE --> DECODE_STATE --> SYNC_WAIT_STATE --fproc_ready--> QCLK_RST_STATE
*               --> MEM_WAIT_STATE
*       done: MEM_WAIT_STATE --> DECODE_STATE --> DONE_STATE --reset--> MEM_WAIT_STATE
*
*
*/
module ctrl#(
    parameter MEM_READ_CYCLES=3)(
    input clk,
    input reset,
    input[7:0] opcode,
    input fproc_ready,
    input sync_ready,
    input qclk_trig_in,
    output [2:0] alu_opcode,
    output reg c_strobe_enable,
    output reg qclk_trig_enable,
    output reg done_gate,
    output alu_in0_sel,
    output reg[1:0] alu_in1_sel,
    output reg reg_write_en,
    output reg instr_ptr_en,
    output reg[1:0] instr_ptr_load_en,
    output reg instr_load_en,
    output reg qclk_load_en,
    output reg qclk_reset,
    output reg sync_enable,
    output reg fproc_enable,
    output reg write_pulse_en,
    output reg pulse_reset);

    reg[4:0] state, next_state;
    reg[31:0] mem_wait_cycles;
    reg mem_wait_rst;

    localparam MEM_WAIT_STATE = 0;
    localparam DECODE_STATE = 1;
    localparam ALU_PROC_STATE_0 = 2;
    localparam ALU_PROC_STATE_1 = 3;
    localparam FPROC_WAIT_STATE = 4;
    localparam SYNC_WAIT_STATE = 6;
    localparam QCLK_RST_STATE = 7;
    localparam DONE_STATE = 9;


    parameter INST_PTR_DEFAULT_EN = 2'b00;
    parameter INST_PTR_SYNC_EN = 2'b01;
    parameter INST_PTR_FPROC_EN = 2'b10;
    parameter INST_PTR_PULSE_EN = 2'b11;
    
    parameter CMD_BUFFER_REGWRITE_SEL = 0;
    parameter ALU_REGWRITE_SEL = 1;
    parameter ALU_IN0_CMD_SEL = 0;
    parameter ALU_IN0_REG_SEL = 1;
    parameter ALU_IN1_QCLK_SEL = 2'b00;
    parameter ALU_IN1_REG_SEL = 2'b01;
    parameter ALU_IN1_FPROC_SEL = 2'b10;
    parameter INSTR_PTR_LOAD_EN_ALU = 2'b10;
    parameter INSTR_PTR_LOAD_EN_TRUE = 2'b01;
    parameter INSTR_PTR_LOAD_EN_FALSE = 2'b00;
    
    //ALU parameters
    parameter ALU_ID0 = 3'b000;
    parameter ALU_ID1 = 3'b110;
    parameter ALU_ADD = 3'b001;
    parameter ALU_SUB = 3'b010;
    parameter ALU_EQ = 3'b011;
    parameter ALU_LE = 3'b100;
    parameter ALU_GE = 3'b101;
    parameter ALU_0 = 3'b111;
    
    //in general: first 5 bits are opcode, followed by 3 bit ALU opcode
    
    //5-bit opcode: 4-bit operation followed by LSB select for ALU_IN1 (0 for cmd, 1 for reg)
    parameter REG_ALU = 4'b0001; //|opcode[8]|cmd_value[32]|reg1_addr[4]|reg_write_addr[4]
    parameter JUMP_I = 4'b0010; //|opcode[8]|cmd_value[32]|reg_addr[4]
    parameter JUMP_COND = 4'b0011; //jump address is always immediate
    parameter ALU_FPROC = 4'b0100;
    parameter JUMP_FPROC = 4'b0101;
    parameter INC_QCLK = 4'b0110;
    parameter SYNC = 4'b0111;
    parameter PULSE_WRITE = 4'b1000;
    parameter PULSE_WRITE_TRIG = 4'b1001;
    parameter DONE = 4'b1010;
    parameter PULSE_RESET = 4'b1011;
    parameter IDLE = 4'b1100;





    //`include "../hdl/ctrl_params.vh"
    //`include "../hdl/instr_params.vh"


    assign alu_opcode = opcode[2:0];
    assign alu_in0_sel = opcode[3];

    always @(posedge clk) begin
        if(reset) begin
            state <= MEM_WAIT_STATE;
            mem_wait_cycles <= 0;
        end

        else begin
            state <= next_state;
            if(mem_wait_rst)
                mem_wait_cycles <= 0;
            else
                mem_wait_cycles <= mem_wait_cycles + 1;
        end

    end

    always @(*) begin
        if(state == MEM_WAIT_STATE) begin
            if(mem_wait_cycles < MEM_READ_CYCLES - 1) begin
                next_state = MEM_WAIT_STATE;
                instr_ptr_en = 0;
                instr_load_en = 0;
                mem_wait_rst = 0;
            end

            else begin
                instr_load_en = 1;
                mem_wait_rst = 1;
                instr_ptr_en = 1;
                next_state = DECODE_STATE;
            end

            sync_enable = 0;
            fproc_enable = 0;
            reg_write_en = 0;
            qclk_load_en = 0;
            qclk_reset = 0;
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            pulse_reset = 0;
            alu_in1_sel = ALU_IN1_REG_SEL;
        
        end

        else if(state == DECODE_STATE) begin
            instr_load_en = 0;
            done_gate = 0;
            case(opcode[7:4])
                PULSE_WRITE : begin
                    next_state = MEM_WAIT_STATE;
                    mem_wait_rst = 0; 
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    instr_ptr_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    write_pulse_en = 1;
                    pulse_reset = 0;
                end

                PULSE_WRITE_TRIG : begin
                    if(qclk_trig_in)
                        next_state = MEM_WAIT_STATE;
                    else
                        next_state = DECODE_STATE;
                    c_strobe_enable = 1;
                    qclk_trig_enable = 1;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    mem_wait_rst = 0; 
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    write_pulse_en = 1;
                    pulse_reset = 0;
                end

                IDLE : begin
                    if(qclk_trig_in)
                        next_state = MEM_WAIT_STATE;
                    else
                        next_state = DECODE_STATE;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 1;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    mem_wait_rst = 0; 
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    write_pulse_en = 0;
                    pulse_reset = 0;
                end

                PULSE_RESET : begin
                    next_state = MEM_WAIT_STATE;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    mem_wait_rst = 0; 
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    write_pulse_en = 0;
                    pulse_reset = 1;
                end

                REG_ALU, JUMP_COND : begin
                    //prepare ALU inputs, go to wait state
                    next_state = ALU_PROC_STATE_0;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    //defaults:
                    mem_wait_rst = 0; 
                    reg_write_en = 0;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    qclk_load_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    write_pulse_en = 0;
                    pulse_reset = 0;
                end

                INC_QCLK : begin
                    //prepare ALU inputs, go to wait state
                    next_state = ALU_PROC_STATE_0;
                    alu_in1_sel = ALU_IN1_QCLK_SEL;
                    //defaults:
                    mem_wait_rst = 0; 
                    reg_write_en = 0;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    qclk_load_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    write_pulse_en = 0;
                    pulse_reset = 0;
                end

                JUMP_I : begin
                    next_state = MEM_WAIT_STATE;
                    mem_wait_rst = 1;
                    //defaults:
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    reg_write_en = 0;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_TRUE;
                    instr_ptr_en = 0;
                    qclk_load_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    fproc_enable = 0;
                    write_pulse_en = 0;
                    pulse_reset = 0;
                end


                ALU_FPROC, JUMP_FPROC : begin
                    next_state = FPROC_WAIT_STATE;
                    fproc_enable = 1;
                    //defaults:
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    mem_wait_rst = 0; 
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    write_pulse_en = 0;
                    pulse_reset = 0;
                end

                SYNC : begin
                    next_state = SYNC_WAIT_STATE;
                    sync_enable = 1;
                    //defaults:
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    fproc_enable = 0;
                    qclk_reset = 0;
                    mem_wait_rst = 0; 
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    instr_ptr_en = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    write_pulse_en = 0;
                    pulse_reset = 0;
                end

                DONE : begin
                    next_state = DONE_STATE;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    mem_wait_rst = 1; 
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    write_pulse_en = 0;
                    instr_ptr_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    fproc_enable = 0;
                    pulse_reset = 0;
                end

                4'b0000 : begin //all zero opcode
                    next_state = DONE_STATE;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    mem_wait_rst = 1; 
                    write_pulse_en = 0;
                    instr_ptr_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    fproc_enable = 0;
                    pulse_reset = 0;
                end

                default : begin
                    next_state = DECODE_STATE;
                    alu_in1_sel = ALU_IN1_REG_SEL;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    mem_wait_rst = 0; 
                    write_pulse_en = 0;
                    instr_ptr_en = 0;
                    sync_enable = 0;
                    qclk_reset = 0;
                    reg_write_en = 0;
                    qclk_load_en = 0;
                    c_strobe_enable = 0;
                    qclk_trig_enable = 0;
                    fproc_enable = 0;
                    pulse_reset = 0;
                end

            endcase

        end

        else if(state == ALU_PROC_STATE_0) begin
            alu_in1_sel = ALU_IN1_REG_SEL;
            next_state = ALU_PROC_STATE_1;
            reg_write_en = 0;
            mem_wait_rst = 0; 
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            instr_ptr_en = 0;
            instr_load_en = 0;
            qclk_load_en = 0;
            sync_enable = 0;
            qclk_reset = 0;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            pulse_reset = 0;
        end

        else if(state == ALU_PROC_STATE_1) begin
            alu_in1_sel = ALU_IN1_REG_SEL;
            next_state = MEM_WAIT_STATE;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            instr_ptr_en = 0;
            instr_load_en = 0;
            sync_enable = 0;
            qclk_reset = 0;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            pulse_reset = 0;
            case(opcode[7:4]) 
                REG_ALU, ALU_FPROC : begin
                    reg_write_en = 1;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    qclk_load_en = 0;
                    mem_wait_rst = 0; 
                end

                JUMP_COND, JUMP_FPROC : begin
                    mem_wait_rst = 1; 
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_ALU;
                    qclk_load_en = 0;
                    reg_write_en = 0;
                end

                INC_QCLK : begin 
                    reg_write_en = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    qclk_load_en = 1;
                    mem_wait_rst = 0; 
                end

                default : begin
                    reg_write_en = 0;
                    instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
                    qclk_load_en = 0;
                    mem_wait_rst = 0; 
                end


            endcase

        end

        else if(state == FPROC_WAIT_STATE) begin
            if(fproc_ready)
                next_state = ALU_PROC_STATE_0;
            else
                next_state = FPROC_WAIT_STATE;
            
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            mem_wait_rst = 0; 
            alu_in1_sel = ALU_IN1_FPROC_SEL;

            reg_write_en = 0;
            instr_ptr_en = 0;
            instr_load_en = 0;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            qclk_load_en = 0;
            sync_enable = 0;
            qclk_reset = 0;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            pulse_reset = 0;
        end

        else if(state == SYNC_WAIT_STATE) begin
            if(sync_ready)
                next_state = QCLK_RST_STATE;
            else
                next_state = SYNC_WAIT_STATE;
            
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            mem_wait_rst = 0; 
            alu_in1_sel = ALU_IN1_FPROC_SEL;

            reg_write_en = 0;
            instr_ptr_en = 0;
            instr_load_en = 0;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            qclk_load_en = 0;
            sync_enable = 0;
            qclk_reset = 0;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            pulse_reset = 0;
        end

        else if(state == QCLK_RST_STATE) begin
            next_state = MEM_WAIT_STATE;
            
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            mem_wait_rst = 0; 
            alu_in1_sel = 0;
            reg_write_en = 0;
            instr_ptr_en = 0;
            instr_load_en = 0;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            qclk_load_en = 0;
            sync_enable = 0;
            qclk_reset = 1;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            pulse_reset = 0;
        end

        else if(state == DONE_STATE) begin
            next_state = DONE_STATE;
            mem_wait_rst = 0; 
            alu_in1_sel = ALU_IN1_REG_SEL;
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            reg_write_en = 0;
            instr_ptr_en = 0;
            instr_load_en = 0;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            qclk_load_en = 0;
            sync_enable = 0;
            qclk_reset = 0;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 1;
            pulse_reset = 0;
        end

        else begin
            next_state = MEM_WAIT_STATE;
            mem_wait_rst = 0; 
            alu_in1_sel = ALU_IN1_REG_SEL;
            instr_ptr_load_en = INSTR_PTR_LOAD_EN_FALSE;
            reg_write_en = 0;
            instr_ptr_en = 0;
            instr_load_en = 0;
            c_strobe_enable = 0;
            qclk_trig_enable = 0;
            qclk_load_en = 0;
            sync_enable = 0;
            qclk_reset = 0;
            fproc_enable = 0;
            write_pulse_en = 0;
            done_gate = 0;
            mem_wait_rst = 0; 
            pulse_reset = 0;
        end
        
    end

endmodule



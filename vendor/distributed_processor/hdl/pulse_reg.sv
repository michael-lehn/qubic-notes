/**
* module: pulse_reg
*
* This module breaks out the pulse parameters from the input command and buffers them in 
* registers (phase, freq, amplitude, env_params, cfg). Pulse parameters (except config) 
* can also come from a 32-bit input register; selection between cmd and reg is handled using 
* parameter specific control bits. Conceputally, pulse_cmd_in comes from hardcoded command 
* bram, while reg_in comes from a proc register.
*
* input cmd:
* |2b env_ctrl|---env_word---|2b phase_ctrl|---phase_word---|2b freq_ctrl|---freq_word---|2b amp_ctrl|---amp_word---|1b cfg_wen|--cfg_word--|
*   - each parameter has two control bits: MSB is write_en, LSB selects pulse_cmd_in or input register (reg_in)
*
*/

module pulse_reg #(
    parameter DATA_WIDTH=32)(
    input clk,
    input[PHASE_WIDTH+FREQ_WIDTH+ENV_WORD_WIDTH+AMP_WIDTH+CFG_WIDTH+9-1:0] pulse_cmd_in, //9 b/c 4x2 control bits + 1x cfg control bit
    input[DATA_WIDTH-1:0] reg_in,
    input pulse_write_en,
    input cstrobe_in,
    pulse_iface.proc pulseout);

    localparam ENV_WORD_WIDTH = pulseout.ENV_WORD_WIDTH;
    localparam FREQ_WIDTH = pulseout.FREQ_WIDTH;
    localparam AMP_WIDTH = pulseout.AMP_WIDTH;
    localparam PHASE_WIDTH = pulseout.PHASE_WIDTH;
    localparam CFG_WIDTH = pulseout.CFG_WIDTH;

    reg[PHASE_WIDTH-1:0] phase;
    reg[FREQ_WIDTH-1:0] freq;
    reg[AMP_WIDTH-1:0] amp;
    reg[ENV_WORD_WIDTH-1:0] env_word;
    reg[CFG_WIDTH-1:0] cfg;
    reg cstrobe;

    localparam PULSE_CMD_WIDTH = PHASE_WIDTH+ENV_WORD_WIDTH+FREQ_WIDTH+AMP_WIDTH+CFG_WIDTH+9;

    localparam ENV_INPUT_MSB = PULSE_CMD_WIDTH-1-2;
    localparam ENV_INPUT_LSB = PULSE_CMD_WIDTH-ENV_WORD_WIDTH-2;
    localparam PHASE_INPUT_MSB = ENV_INPUT_LSB-1-2;
    localparam PHASE_INPUT_LSB = ENV_INPUT_LSB-PHASE_WIDTH-2;
    localparam FREQ_INPUT_MSB = PHASE_INPUT_LSB-1-2;
    localparam FREQ_INPUT_LSB = PHASE_INPUT_LSB-FREQ_WIDTH-2;
    localparam AMP_INPUT_MSB = FREQ_INPUT_LSB-1-2;
    localparam AMP_INPUT_LSB = FREQ_INPUT_LSB-AMP_WIDTH-2;
    localparam CFG_INPUT_MSB = AMP_INPUT_LSB-1-1;
    localparam CFG_INPUT_LSB = AMP_INPUT_LSB-CFG_WIDTH-1;

    wire[ENV_WORD_WIDTH-1:0] env_i_in, env_in;
    wire[PHASE_WIDTH-1:0] phase_i_in, phase_in;
    wire[FREQ_WIDTH-1:0] freq_i_in, freq_in;
    wire[AMP_WIDTH-1:0] amp_i_in, amp_in;
    wire[CFG_WIDTH-1:0] cfg_i_in, cfg_in;
    wire env_write_en, phase_write_en, freq_write_en, amp_write_en, cfg_write_en;
    wire env_write_sel, phase_write_sel, freq_write_sel, amp_write_sel;

    assign env_i_in = pulse_cmd_in[ENV_INPUT_MSB:ENV_INPUT_LSB];
    assign phase_i_in = pulse_cmd_in[PHASE_INPUT_MSB:PHASE_INPUT_LSB];
    assign freq_i_in = pulse_cmd_in[FREQ_INPUT_MSB:FREQ_INPUT_LSB];
    assign amp_i_in = pulse_cmd_in[AMP_INPUT_MSB:AMP_INPUT_LSB];
    assign cfg_i_in = pulse_cmd_in[CFG_INPUT_MSB:CFG_INPUT_LSB];

    //write enable if pulse_write_en and command specific enable are active
    // *pulse_write_en is proc control bit
    assign env_write_en = pulse_cmd_in[ENV_INPUT_MSB+2] & pulse_write_en;
    assign phase_write_en = pulse_cmd_in[PHASE_INPUT_MSB+2] & pulse_write_en;
    assign freq_write_en = pulse_cmd_in[FREQ_INPUT_MSB+2] & pulse_write_en;
    assign amp_write_en = pulse_cmd_in[AMP_INPUT_MSB+2] & pulse_write_en;
    assign cfg_write_en = pulse_cmd_in[CFG_INPUT_MSB+1] & pulse_write_en; //cfg has no reg option

    assign env_write_sel = pulse_cmd_in[ENV_INPUT_MSB+1];
    assign phase_write_sel = pulse_cmd_in[PHASE_INPUT_MSB+1];
    assign freq_write_sel = pulse_cmd_in[FREQ_INPUT_MSB+1];
    assign amp_write_sel = pulse_cmd_in[AMP_INPUT_MSB+1];

    assign env_in = env_write_sel ? reg_in[ENV_WORD_WIDTH-1:0] : env_i_in;
    assign phase_in = phase_write_sel ? reg_in[PHASE_WIDTH-1:0] : phase_i_in;
    assign freq_in = freq_write_sel ? reg_in[FREQ_WIDTH-1:0] : freq_i_in;
    assign amp_in = amp_write_sel ? reg_in[AMP_WIDTH-1:0] : amp_i_in;
    assign cfg_in = cfg_i_in;

    always @(posedge clk) begin
        if(env_write_en)
            env_word <= env_in;
        if(phase_write_en)
            phase <= phase_in;
        if(freq_write_en)
            freq <= freq_in;
        if(amp_write_en)
            amp <= amp_in;
        if(cfg_write_en)
            cfg <= cfg_in;
        cstrobe <= cstrobe_in;

    end

    assign pulseout.env_word = env_word;
    assign pulseout.phase = phase;
    assign pulseout.freq = freq;
    assign pulseout.amp = amp;
    assign pulseout.cfg = cfg;
    assign pulseout.cstrobe = cstrobe;

    
endmodule

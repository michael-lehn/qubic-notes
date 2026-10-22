module pulsereg_sim#(
    parameter DATA_WIDTH=32,
    parameter ENV_WIDTH = 24,
    parameter PHASE_WIDTH = 17,
    parameter FREQ_WIDTH = 9,
    parameter AMP_WIDTH = 16,
    parameter CFG_WIDTH = 4)(
    input clk,
    input[PHASE_WIDTH+FREQ_WIDTH+ENV_WIDTH+AMP_WIDTH+CFG_WIDTH+9-1:0] pulse_cmd_in, //9 b/c 4x2 control bits + 1x cfg control bit
    input[DATA_WIDTH-1:0] reg_in,
    input pulse_write_en,
    input cstrobe_in,
    output[ENV_WIDTH-1:0] env_word,
    output[PHASE_WIDTH-1:0] phase,
    output[FREQ_WIDTH-1:0] freq,
    output[AMP_WIDTH-1:0] amp,
    output[CFG_WIDTH-1:0] cfg,
    output cstrobe_out);


    pulse_iface #(.PHASE_WIDTH(PHASE_WIDTH), .FREQ_WIDTH(FREQ_WIDTH), 
        .ENV_WORD_WIDTH(ENV_WIDTH), .AMP_WIDTH(AMP_WIDTH), .CFG_WIDTH(CFG_WIDTH)) pulseout();

    pulse_reg #(.DATA_WIDTH(DATA_WIDTH)) pulsereg(.clk(clk), .reg_in(reg_in), .pulse_cmd_in(pulse_cmd_in),
        .pulse_write_en(pulse_write_en), .cstrobe_in(cstrobe_in), .pulseout(pulseout));

    assign env_word = pulseout.env_word;
    assign amp = pulseout.amp;
    assign phase = pulseout.phase;
    assign freq = pulseout.freq;
    assign cfg = pulseout.cfg;
    assign cstrobe_out = pulseout.cstrobe;

endmodule

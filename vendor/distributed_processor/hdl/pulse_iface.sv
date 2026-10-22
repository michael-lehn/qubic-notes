interface pulse_iface#(    
    parameter PHASE_WIDTH=17,
    parameter FREQ_WIDTH=9,
    parameter AMP_WIDTH=16,
    parameter CFG_WIDTH=4, //mode + dest bits
    parameter ENV_WORD_WIDTH=24)(); //12 bit addr + 12 bit length


    wire[PHASE_WIDTH-1:0] phase;
    wire[FREQ_WIDTH-1:0] freq;
    wire[AMP_WIDTH-1:0] amp;
    wire[ENV_WORD_WIDTH-1:0] env_word;
    wire[CFG_WIDTH-1:0] cfg;
    wire cstrobe;
    wire reset;

    modport proc(output phase, output freq, output amp, 
        output env_word, output cfg, output cstrobe, output reset);

endinterface


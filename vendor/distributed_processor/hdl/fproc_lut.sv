/**
* General purpose measurement LUT module. Distributes measurement (and LUT)
* results to corresponding proc cores. There are two modes, depending on
* the value of fproc.id: 
*   0 - wait for measurement on core's control qubit, then transmit to core when ready
*   1 - wait for all measurements needed by LUT, then distribute corresponding LUT 
*       output to core.
*
* TODO: separate this into two modules; one for the core state machine (interact with 
*       FPROC interface), and another for the LUT
*/

module fproc_lut #(
    parameter N_CORES=5,
    parameter N_MEAS=N_CORES)(
    input clk,
    input reset,
    fproc_iface.fproc core[N_CORES-1:0],
    input[N_MEAS-1:0] meas,
    input[N_MEAS-1:0] meas_valid);

    wire[N_CORES-1:0] lut_out;
    wire lut_ready;

    core_state_mgr #(.N_CORES(N_CORES), .N_MEAS(N_MEAS)) mgr(.clk(clk), .reset(reset), .lut_out(lut_out), 
        .lut_ready(lut_ready), .meas(meas), .meas_valid(meas_valid), .core(core));
    meas_lut#(.N_MEAS(N_MEAS), .N_CORES(N_CORES)) lut (.clk(clk), .reset(reset), .meas(meas), .meas_valid(meas_valid), 
        .lut_out(lut_out), .lut_ready(lut_ready));

endmodule



        
        

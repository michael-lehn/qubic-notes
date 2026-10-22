module fproc_meas_sim #(
    parameter N_CORES=5,
    parameter DATA_WIDTH=32,
    parameter FPROC_ID_WIDTH=8)(
    input clk,
    input reset,
    input[N_CORES-1:0] meas,
    input[N_CORES-1:0] meas_valid,
    input[FPROC_ID_WIDTH-1:0] fproc_id[N_CORES-1:0],
    input[N_CORES-1:0] fproc_enable,
    output[DATA_WIDTH-1:0] fproc_data[N_CORES-1:0],
    output[N_CORES-1:0] fproc_ready);

    fproc_iface #(.FPROC_RESULT_WIDTH(DATA_WIDTH),
                  .FPROC_ID_WIDTH(FPROC_ID_WIDTH)) fproc[N_CORES-1:0];
    genvar i;
    generate
        for(i = 0; i < N_CORES; i = i + 1) begin
            assign fproc[i].id = fproc_id[i];
            assign fproc[i].enable = fproc_enable[i];
            assign fproc_data[i] = fproc[i].data;
            assign fproc_ready[i] = fproc[i].ready;
        end
    endgenerate

    fproc_meas #(.N_CORES(5)) lut(.clk(clk), .reset(reset), .core(fproc),
        .meas(meas), .meas_valid(meas_valid));

endmodule


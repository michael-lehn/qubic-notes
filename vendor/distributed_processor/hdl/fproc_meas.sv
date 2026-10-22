module fproc_meas #(
    parameter N_CORES=5,
    parameter N_MEAS=N_CORES)(
    input clk,
    input reset,
    input[N_MEAS-1:0] meas,
    input[N_MEAS-1:0] meas_valid,
    fproc_iface.fproc core[N_CORES-1:0]);

    reg[N_CORES-1:0] core_arm_ready;

    localparam ADDR_WIDTH = (N_MEAS > 1) ? $clog2(N_MEAS) : 1;
    reg[ADDR_WIDTH-1:0] meas_read_addr[N_CORES-1:0];
    reg[N_MEAS-1:0] meas_reg;

    localparam IDLE = 2'b0;
    localparam READY = 2'b01;

    always @(posedge clk) 
        meas_reg <= (meas_reg & (~meas_valid)) | (meas & meas_valid);

    genvar i;
    generate 
        for(i = 0; i < N_CORES; i = i + 1) begin
            always @(posedge clk) begin
                // clock in enable/address  
                core_arm_ready[i] <= core[i].enable;
                meas_read_addr[i] <= core[i].id[ADDR_WIDTH-1:0];

                // clock out data/ready 
                core[i].ready <= core_arm_ready[i];
                core[i].data[0] <= meas_reg[meas_read_addr[i]];

            end
        end
    endgenerate

endmodule
                            

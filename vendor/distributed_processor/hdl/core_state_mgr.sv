
module core_state_mgr #(
    parameter N_CORES=5,
    parameter N_MEAS=N_CORES)(
    input clk,
    input reset,
    input[N_CORES-1:0] lut_out,
    input lut_ready,
    input[N_MEAS-1:0] meas,
    input[N_MEAS-1:0] meas_valid,
    fproc_iface.fproc core[N_CORES-1:0]);

    reg[1:0] core_state[N_CORES-1:0];
    reg[1:0] core_next_state[N_CORES-1:0];
    localparam IDLE = 2'b0;
    localparam WAIT_MEAS = 2'b01;
    localparam WAIT_LUT = 2'b10;


    genvar i;
    generate 
        for(i = 0; i < N_CORES; i = i + 1) begin
            always @(posedge clk) begin
                if(reset)
                    core_state[i] = IDLE;
                else
                    core_state[i] = core_next_state[i];
            end

            always @(*) begin
                case(core_state[i])
                    IDLE : begin
                        core[i].ready = 0;
                        core[i].data = 0;
                        if(core[i].enable) begin
                            if(core[i].id == 0)
                                core_next_state[i] = WAIT_MEAS;
                            else
                                core_next_state[i] = WAIT_LUT;
                        end
                        else
                            core_next_state[i] = IDLE;
                    end
                    
                    WAIT_MEAS : begin
                        if(meas_valid[i] == 1) begin
                            core[i].ready = 1;
                            core[i].data[0] = meas[i];
                            core_next_state[i] = IDLE;
                        end
                        else begin
                            core[i].ready = 0;
                            core[i].data[0] = 0;
                            core_next_state[i] = WAIT_MEAS;
                        end
                    end

                    WAIT_LUT : begin
                        if(lut_ready) begin
                            core[i].ready = 1;
                            core[i].data[0] = lut_out[i];
                            core_next_state[i] = IDLE;
                        end
                        else begin
                            core[i].ready = 0;
                            core[i].data = 0;
                            core_next_state[i] = WAIT_LUT;
                        end
                    end

                    default : begin
                        core_next_state[i] = IDLE;
                    end
                endcase
            end
        end
    endgenerate

endmodule
                            

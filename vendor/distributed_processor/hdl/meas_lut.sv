module meas_lut #(
    parameter N_CORES=5,
    parameter N_MEAS=N_CORES)(
    input clk,
    input reset,
    input[N_MEAS-1:0] meas,
    input[N_MEAS-1:0] meas_valid,
    output reg[N_CORES-1:0] lut_out,
    output lut_ready);

    reg[N_MEAS-1:0] lut_mem[2**N_MEAS-1:0]; //addressed by measurment outcome
    reg[N_MEAS-1:0] lut_mask;
    reg[N_MEAS-1:0] lut_valid;
    reg[N_MEAS-1:0] lut_addr;

    assign lut_mask = 5'b00011; //TODO: make these writable
    assign lut_mem[0] = 5'b00000;
    assign lut_mem[1] = 5'b00100;
    assign lut_mem[2] = 5'b10000;
    assign lut_mem[3] = 5'b01000;

    localparam LUT_WAIT = 0;
    localparam LUT_READY = 1;
    reg lut_state;
    reg lut_next_state;

    assign lut_ready = (lut_mask & lut_valid) == lut_mask;
    assign lut_out = lut_mem[lut_addr];

    always @(posedge clk) begin
        if(reset) begin
            lut_state = LUT_WAIT;
            lut_valid = 0;
            lut_addr = 0;
        end 
        else
            lut_state = lut_next_state;
    end

    always @(*) begin
        case(lut_state)
            LUT_WAIT : begin
                lut_valid = lut_valid | meas_valid;
                lut_addr = lut_addr | (meas_valid & meas);
                if(lut_ready)
                    lut_next_state = LUT_READY;
                else
                    lut_next_state = LUT_WAIT;
            end
            LUT_READY : begin
                lut_next_state = LUT_WAIT;
                lut_addr = 0;
                lut_valid = 0;
            end
        endcase
    end

endmodule

module reg_file
    #(parameter DATA_WIDTH=32,
    parameter ADDR_WIDTH=4)(
    input clk,
    input[ADDR_WIDTH-1:0] read_addr_0,
    input[ADDR_WIDTH-1:0] read_addr_1,
    input write_enable,
    input[ADDR_WIDTH-1:0] write_addr,
    input[DATA_WIDTH-1:0] write_data,
    output[DATA_WIDTH-1:0] reg_0_out,
    output[DATA_WIDTH-1:0] reg_1_out);

    reg[DATA_WIDTH-1:0] data[2**ADDR_WIDTH-1:0];

    assign reg_0_out[DATA_WIDTH-1:0] = data[read_addr_0];
    assign reg_1_out[DATA_WIDTH-1:0] = data[read_addr_1];


    always @(posedge clk) begin
        if(write_enable)
            data[write_addr] <= write_data;
    
    end
        
        

endmodule


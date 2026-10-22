`timescale 1ns / 1ns

module reg_delay1 #(parameter DW=16  // Width of data
,parameter LEN=4   // Cycles to delay
) (input clk  // Rising edge clock input; all logic is synchronous in this domain
,input gate  // Enable processing
,input [DW-1:0] din  // Input data
,output [DW-1:0] dout  // Output data
,input reset
);

// LEN clocks of delay.  Xilinx should turn this into
//   DW*floor((LEN+15)/16)
// SRL16 shift registers, since there are no resets.
generate
if (LEN > 1) begin: usual
	reg [DW*LEN-1:0] shifter=0;
	always @(posedge clk) begin
		shifter <= reset ? 0 : gate ? {shifter[DW*LEN-1-DW:0],din} : shifter;
	end
	assign dout = shifter[DW*LEN-1:DW*LEN-DW];
end
else if (LEN > 0) begin: degen1
	reg [DW*LEN-1:0] shifter=0;
	always @(posedge clk) begin
		shifter <= reset ? 0 : gate ? din : shifter;
	end
	assign dout = shifter[DW*LEN-1:DW*LEN-DW];
end
else begin: degen0
	assign dout = din;
end
endgenerate
endmodule

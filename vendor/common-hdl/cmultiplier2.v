/*`timescale 1 ns/10 ps
//module cmultiplier#(parameter FPGA="SPARTAN7")
//module cmultiplier#(parameter FPGA="SPARTAN6")
module cmultiplier#(parameter XWIDTH=16,parameter YWIDTH=16, parameter ZWIDTH=16)
(input clk
,input rst
,input signed [XWIDTH-1:0] xr
,input signed [XWIDTH-1:0] xi
,input signed [YWIDTH-1:0] yr
,input signed [YWIDTH-1:0] yi
,output signed [ZWIDTH-1:0] zr
,output signed [ZWIDTH-1:0] zi
);
reg signed [XWIDTH-1:0] xr1=0;
reg signed [XWIDTH-1:0] xr2=0;
reg signed [XWIDTH-1:0] xr3=0;
reg signed [XWIDTH-1:0] xr4=0;
reg signed [XWIDTH-1:0] xi1=0;
reg signed [XWIDTH-1:0] xi2=0;
reg signed [XWIDTH-1:0] xi3=0;
reg signed [XWIDTH-1:0] xi4=0;
reg signed [YWIDTH-1:0] yr1=0;
reg signed [YWIDTH-1:0] yr2=0;
reg signed [YWIDTH-1:0] yr3=0;
reg signed [YWIDTH-1:0] yi1=0;
reg signed [YWIDTH-1:0] yi2=0;
reg signed [YWIDTH-1:0] yi3=0;
// (zr+1j*zi)=(xr+1j*xi)*(yr+1j*yi)
// = (xr*yr-xi*yi)+1j*(xr*yi+xi*yr)
// =(xr-xi)*yi+(yr-yi)*xr + 1j*((xr-xi)*yi+(yr+yi)*xi)
always @(posedge clk) begin
	xr1<=xr;
	xr2<=xr1;
	xr3<=xr2;
	xr4<=xr3;
	xi1<=xi;
	xi2<=xi1;
	xi3<=xi2;
	xi4<=xi3;
	yr1<=yr;
	yr2<=yr1;
	yr3<=yr2;
	yi1<=yi;
	yi2<=yi1;
	yi3<=yi2;
end
wire signed [XWIDTH+YWIDTH:0] pa,pb,pc;
reg signed [XWIDTH+YWIDTH:0] par=0,pbr=0,pcr=0;
reg signed [XWIDTH+YWIDTH:0] prr=0,pri=0,pir=0,pii=0;


always @(posedge clk) begin
	par<=(xr-xi)*yi;
	pbr<=(yr-yi)*xr+par;
	pcr<=(yr+yi)*xi+par;
end



//always @(posedge clk) begin
//	prr<=xr*yr;
//	pri<=xr*yi;
//	pir<=xi*yr;
//	pii<=xi*yi;
//	pbr<=prr-pii;
//	pcr<=pri+pir;
//end

assign pb=pbr;
assign pc=pcr;
assign zr=pb[XWIDTH+YWIDTH-1:XWIDTH+YWIDTH-ZWIDTH];
assign zi=pc[XWIDTH+YWIDTH-1:XWIDTH+YWIDTH-ZWIDTH];

endmodule

*/
module cmultiplier # (parameter XWIDTH = 16, YWIDTH = 18)
(
	input clk,
	input signed [XWIDTH-1:0] xr, xi,
	input signed [YWIDTH-1:0] yr, yi,
	output signed [XWIDTH+YWIDTH:0] zr, zi
);
reg signed [XWIDTH-1:0] xi1, xi2, xi3, xi4;
reg signed [XWIDTH-1:0] xr1, xr2, xr3, xr4;
reg signed [YWIDTH-1:0] yi1, yi2, yi3, yr1, yr2, yr3;
reg signed [XWIDTH:0] addcommon;
reg signed [YWIDTH:0] addr, addi;
reg signed [XWIDTH+YWIDTH:0] mult0, multr, multi, zr_int, zi_int;
reg signed [XWIDTH+YWIDTH:0] common, commonr1, commonr2;

always @(posedge clk)
begin
	xi1 <= xi;
	xi2 <= xi1;
	xi3 <= xi2;
	xi4 <= xi3;
	xr1 <= xr;
	xr2 <= xr1;
	xr3 <= xr2;
	xr4 <= xr3;
	yi1 <= yi;
	yi2 <= yi1;
	yi3 <= yi2;
	yr1 <= yr;
	yr2 <= yr1;
	yr3 <= yr2;
end
always @(posedge clk) begin: commonpart
	addcommon <= xr1 - xi1;
	mult0 <= addcommon * yi2;
	common <= mult0;
end
always @(posedge clk) begin: realpart
	addr <= yr3 - yi3;
	multr <= addr * xr4;
	commonr1 <= common;
	zr_int <= multr + commonr1;
end
always @(posedge clk) begin: imagpart
	addi <= yr3 + yi3;
	multi <= addi * xi4;
	commonr2 <= common;
	zi_int <= multi + commonr2;
end
assign zr = zr_int;
assign zi = zi_int;

endmodule // cmult

// OPIN cannot be changed during the run, trying to save combinational logic to make timing, to be tested
`timescale 1ns / 1ns
module cordicg(clk, xin, yin, phasein, xout, yout, phaseout,error,gin,gout);
parameter OPIN=1'b0; // input [0:0] opin;  //  1 forces y to zero (rect to polar), 0 forces theta to zero (polar to rect)
parameter WIDTH=19;
parameter NSTAGE=19;
parameter NORMALIZE=0;
localparam ZWIDTH=NSTAGE+1;
parameter BUFIN=0;
parameter GW=1;
input clk;
input signed [WIDTH-1:0] xin;
input signed [WIDTH-1:0] yin;
input [ZWIDTH-1:0] phasein;
output signed [WIDTH-1:0] xout;
output signed [WIDTH-1:0] yout;
output [ZWIDTH-1:0] phaseout;
output error;
input [GW-1:0] gin;
output [GW-1:0] gout;

localparam [33*32-1:0] PHASE_CONST ={32'd0,32'd0,32'd1,32'd1,32'd3,32'd5,32'd10,32'd20,32'd41,32'd81,32'd163,32'd326,32'd652,32'd1304,32'd2608,32'd5215,32'd10430,32'd20861,32'd41722,32'd83443,32'd166886,32'd333772,32'd667544,32'd1335087,32'd2670163,32'd5340245,32'd10679838,32'd21354465,32'd42667331,32'd85004756,32'd167458907,32'd316933406,32'd536870912
};// print ','.join(["%d'd%d"%(32,int(i)) for i in floor(arctan(1.0/(2**arange(32,-1,-1)))*2/2/pi*2**(32-1)+0.5)]). I guess this is the highest zwidth we should use, if not, we can generate something even bigger, and adjust ain location accordingly

wire [31:0] PHASE [0:32];
generate 
for (genvar i =0;i<=32;i=i+1) begin
	assign PHASE[i]=PHASE_CONST[i*32+31:i*32];
end
endgenerate

reg signed [WIDTH-1:0] xout_r=0;
reg signed [WIDTH-1:0] yout_r=0;
reg [ZWIDTH-1:0] phaseout_r=0;
reg errorr=0;
wire signed [WIDTH-1:0] xin_1;
wire signed [WIDTH-1:0] yin_1;
wire [ZWIDTH-1:0] phasein_1;
assign error=|errorr;
localparam WIDTHP1=WIDTH+1;
generate
if (BUFIN==0) begin
	assign xin_1=xin;
	assign yin_1=yin;
	assign phasein_1=phasein;
end
else begin
	reg signed [WIDTH-1:0] xin_d=0;
	reg signed [WIDTH-1:0] yin_d=0;
	reg [ZWIDTH-1:0] phasein_d=0;
	always @(posedge clk) begin
		xin_d<=xin;
		yin_d<=yin;
		phasein_d<=phasein;
	end
	assign xin_1=xin_d;
	assign yin_1=yin_d;
	assign phasein_1=phasein_d;
end
endgenerate
wire shiftpi;
generate
if (OPIN) begin
assign shiftpi=(xin_1[WIDTH-1]);
end
else begin
assign shiftpi=phasein_1[ZWIDTH-1]^phasein_1[ZWIDTH-2];
end
endgenerate
wire plusall [0:NSTAGE] ;
reg op [0:NSTAGE];
reg pluscheck [0:NSTAGE];
reg pluscheck0 [0:NSTAGE];
reg signed [WIDTHP1-1:0] x[0:NSTAGE];
reg signed [WIDTHP1-1:0] y[0:NSTAGE];
reg [ZWIDTH-1:0] z[0:NSTAGE];
reg signed [WIDTHP1-1:0] xshift[0:NSTAGE];
reg signed [WIDTHP1-1:0] yshift[0:NSTAGE];
reg [ZWIDTH-1:0] zshift[0:NSTAGE];
always @(posedge clk) begin
	x[0] <= shiftpi ? -((WIDTHP1)'(signed'(xin_1))) : (WIDTHP1)'(signed'(xin_1));
	y[0] <= shiftpi ? -((WIDTHP1)'(signed'(yin_1))) : (WIDTHP1)'(signed'(yin_1));
	z[0] <= shiftpi ? {{1{~phasein_1[ZWIDTH-1]}},phasein_1[ZWIDTH-2:0]} : {phasein_1[ZWIDTH-1],phasein_1[ZWIDTH-2:0]};
end
genvar istage;
generate 
for (istage=0; istage<NSTAGE; istage=istage+1) begin: stage
	wire [ZWIDTH-1:0] ain=PHASE[istage][31:32-ZWIDTH];
	if (OPIN) begin
		assign plusall[istage]=~y[istage][WIDTHP1-1];
	end
	else begin
		assign plusall[istage]=z[istage][ZWIDTH-1];
	end
	wire plus=OPIN ? ~y[istage][WIDTHP1-1] : z[istage][ZWIDTH-1];
	reg signed [WIDTHP1-1:0] xnext=0;
	reg signed [WIDTHP1-1:0] ynext=0;
	reg [ZWIDTH-1:0] znext=0;
	reg signed [WIDTHP1-1:0] xplus=0;
	reg signed [WIDTHP1-1:0] xminus=0;
	reg signed [WIDTHP1-1:0] yplus=0;
	reg signed [WIDTHP1-1:0] yminus=0;
	reg [ZWIDTH-1:0] zplus=0;
	reg [ZWIDTH-1:0] zminus=0;

	always @(posedge clk) begin
		xplus<= (x[istage] + (y[istage]>>>istage));
		yplus<= (y[istage] - (x[istage]>>>istage));
		zplus<= z[istage] + ain;
		xminus<= (x[istage] - (y[istage]>>>istage)) ;
		yminus<= (y[istage] + (x[istage]>>>istage));
		zminus<= z[istage] - ain;
//		x[istage+1]<=plusall[istage] ? xplus : xminus;
//		y[istage+1]<=plusall[istage] ? yplus : yminus;
//		z[istage+1]<=plusall[istage] ? zplus : zminus;

	end
	always @(posedge clk) begin
		x[istage+1]<= plusall[istage] ? (x[istage] + (y[istage]>>>istage)) : (x[istage] - (y[istage]>>>istage)) ;
		y[istage+1]<= plusall[istage] ? (y[istage] - (x[istage]>>>istage)) : (y[istage] + (x[istage]>>>istage));
		z[istage+1]<= plusall[istage] ? z[istage] + ain : z[istage] - ain;
		pluscheck[istage+1]<=plusall[istage];
		pluscheck0[istage+1]<=plusall[istage];
	end
end

wire signed [WIDTHP1-1:0] xg=x[NSTAGE-1];
wire signed [WIDTHP1-1:0] yg=y[NSTAGE-1];
wire         [ZWIDTH-1:0] zg=z[NSTAGE-1];

reg signed [WIDTH:0] xsum0=0;
reg signed [WIDTH:0] xsum1=0;
reg signed [WIDTH:0] xsum2=0;
reg signed [WIDTH:0] xsum2_d=0;
reg signed [WIDTH:0] xsum3=0;
reg signed [WIDTH:0] ysum0=0;
reg signed [WIDTH:0] ysum1=0;
reg signed [WIDTH:0] ysum2=0;
reg signed [WIDTH:0] ysum2_d=0;
reg signed [WIDTH:0] ysum3=0;
reg [ZWIDTH-1:0] zg0=0;
reg [ZWIDTH-1:0] zg1=0;

if (NORMALIZE==1) begin
	reg xdummy=0,ydummy=0,zdummy=0;
	// cordic gain= 1/0.6072529350088812561694
	// (1./2**1)+(1./2**3)-(1./2**6)-(1./2**9)-(1./2**12)+(1./2**14)=0.607238
	// (1./2**1)+(1./2**3)-(1./2**6)-(1./2**9)-(1./2**12)+(1./2**14)+(1./2**16)-(1./2**19)+(1./2**20)-(1./2**23)-(1./2**25)=0.6072529256
	always @(posedge clk) begin
		xsum0<=(xg>>>1)+(xg>>>3);
		xsum1<=(xg>>>6)+(xg>>>9);
		xsum2<=(xg>>>12)-(xg>>>14);//+(xg>>>16)-(xg>>>19)+(xg>>>20)-(xg>>>23)-(xg>>>25);
		xsum2_d<=xsum2;
		xsum3<=xsum0-xsum1;
		{xdummy,xout_r}<=xsum3-xsum2_d;
		ysum0<=(yg>>>1)+(yg>>>3);
		ysum1<=(yg>>>6)+(yg>>>9);
		ysum2<=(yg>>>12)-(yg>>>14);//+(yg>>>16)-(yg>>>19)+(yg>>>20)-(yg>>>23)-(yg>>>25);
		ysum2_d<=ysum2;
		ysum3<=ysum0-ysum1;
		{ydummy,yout_r}<=ysum3-ysum2_d;
		zg0 <= zg;
		zg1 <= zg0;
		phaseout_r<= zg1;
		errorr<=(xdummy^xout_r[WIDTH-1])|(ydummy^yout[WIDTH-1]);
	end
end
else begin
	always @(posedge clk) begin
		xout_r<=xg[WIDTH-1:0];
		yout_r<=yg[WIDTH-1:0];
		phaseout_r <= zg;
		errorr<=1'b0;
	end
end
endgenerate
assign xout=xout_r;
assign yout=yout_r;
assign phaseout=phaseout_r;
wire signed [WIDTH-1:0] xout1=xout;
wire signed [WIDTH-1:0] yout1=yout;
wire [ZWIDTH-1:0] phaseout1=phaseout;

localparam BUFINDELAY=(BUFIN==0)? 0 : 1 ;
localparam NORMALIZEDDELAY=(NORMALIZE==0)? 1:3;
reg_delay1 #(.DW(GW), .LEN(NSTAGE+BUFINDELAY+NORMALIZEDDELAY)) reg_delay(.clk(clk), .gate(1'b1), .din(gin),   .dout(gout),.reset(1'b0));
endmodule

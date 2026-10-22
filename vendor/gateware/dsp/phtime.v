module phtime(input clk
,input [26:0] freq
,input [26:0] tcnt
,input gatein 
,output [26:0] phasetime
,output gateout
);
//localparam TCNTWIDTH=18; // < 18, buildin dsp is 27*18 bit
//reg [18-1:0] tcnt=0;
//reg [TCNTWIDTH-1:0] tcnt=0;
reg [26:0] freq_r=0;
reg [26:0] tcnt_r=0;
wire [27+27-1:0] phasetime_w=freq_r*tcnt_r;
/*reg [27-1:0] phasetime_r0=0;
reg [27-1:0] phasetime_r1=0;
reg [27-1:0] phasetime_r2=0;
reg [27-1:0] phasetime_r3=0;
reg [27-1:0] phasetime_r4=0;
reg [27-1:0] phasetime_wrap=0;
reg valid0=0;
reg valid1=0;
reg valid2=0;
reg valid3=0;
wire tcntlast0=&tcnt;
reg tcntlast1=0;
reg tcntlast2=0;
reg tcntlast3=0;
reg tcntlast4=0;
reg [26:0] phadd=0;
reg [26:0] phadd0=0;
reg [26:0] phadd1=0;
reg [26:0] phadd2=0;
reg [26:0] phadd3=0;
reg [26:0] phadd4=0;

always @(posedge clk) begin
	//tcnt<= reset ? 0 : tcnt+1;
	phasetime_r0<=phasetime_w[26:0];
	phasetime_r1<=phasetime_r0;
	phasetime_r2<=phasetime_r1;
	phasetime_r3<=phasetime_r2;
	phasetime_r4<=phasetime_r3  + phasetime_wrap;
	tcntlast1<=tcntlast0;
	tcntlast2<=tcntlast1;
	tcntlast3<=tcntlast2;
	tcntlast4<=tcntlast3;

	phasetime_wrap<= reset ? 0 : (tcntlast4 ? (phasetime_r3+phasetime_wrap +freq) : phasetime_wrap); 
	valid0<=~reset;
	valid1<=valid0;
	valid2<=valid1;
	valid3<=valid2;
	phadd<=reset ? 0 : phadd+freq;
	phadd0<=phadd;
	phadd1<=phadd0;
	phadd2<=phadd1;
	phadd3<=phadd2;
	phadd4<=phadd3;

end
wire [26:0] err=phadd4-phasetime_r4;
assign phasetime=phasetime_r4;
assign valid=valid3;
*/
reg [26:0] phasetime_r0=0;
reg [26:0] phasetime_r1=0;
reg [26:0] phasetime_r2=0;
reg [26:0] phasetime_r3=0;
reg [7:0] gatesr=0;
always @(posedge clk) begin
	freq_r<=freq;
	tcnt_r<=tcnt;
	phasetime_r0<=phasetime_w[26:0];
	phasetime_r1<=phasetime_r0;
	phasetime_r2<=phasetime_r1;
	phasetime_r3<=phasetime_r2;
	gatesr<={gatesr[6:0],gatein};
end
assign phasetime=phasetime_r3;
assign gateout=gatesr[4];
endmodule

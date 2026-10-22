/**
* reset/strobe signals:
*  - stb_start: 1 clock cycle, pos edge
*       assert this to start nshot experiment (reset procs)
*  - nshot: reg, number of shots to take
*       proc will run command buffer nshot times, with resets in between
*  - resetacc: level signal reset high
*       assert this to reset write pointer to acc_buf (where shots are stored; all channels)
*
*  - reset: reset all modules
*
*  to run experiment: 
*   - set nshot
*   - assert resetacc + stb_start when ready
*
*/


module dsp #(`include "plps_para.vh"	
,`include "bram_para.vh"
,`include "braminit_para.vh"
)(ifdsp.dsp dspif);
reg procreset=0;
reg procreset_d=0;
reg lastshotdone=0;
reg done=0;
reg [31:0] nshot=0;
wire [NPROC-1:0] stbprocend;
wire [NPROC-1:0] procdone;
reg procdone_r=0;
wire [NPROC-1:0] nobusy;
reg nobusy_r=0;
reg [31:0] shotcnt=0;
reg [31:0] nextshotcnt=0;//shotcnt+1;
reg [31:0] currentshotcnt=0;
reg [NPROC-1:0] proccorereset;
reg [DAC_AXIS_DATAWIDTH-1:0] dac[0:3];

always @(posedge dspif.clk) begin
	procreset_d<=procreset;
	//	proccorereset<={N_QUBIT_CORES{procreset|procreset_d}};
	proccorereset<={NPROC{procreset}};
	dspif.procdone<=procdone;

end

dsp_cores cores(.dspif(dspif), .reset(procreset_d), .procdone(procdone), .nobusy(nobusy));




reg [ADC_AXIS_DATAWIDTH-1:0] adc[0:NADC-1];
reg [ADC_AXIS_DATAWIDTH-1:0] adc_d1[0:NADC-1];
reg [ADC_AXIS_DATAWIDTH-1:0] adc_d2[0:NADC-1];
reg [ADC_AXIS_DATAWIDTH-1:0] dacundersample[0:NDAC-1];
reg [ADC_AXIS_DATAWIDTH-1:0] mixbb1=0;
reg [ADC_AXIS_DATAWIDTH-1:0] mixbb2=0;

always @(posedge dspif.clk) begin
	case (dspif.mixbb1sel)
		0: 	mixbb1<=adc[0];
		1: 	mixbb1<=dacundersample[0];
		2: 	mixbb1<=dacundersample[1];
	//	1: 	mixbb1<=adc[1];
	//	2: 	mixbb1<=dacundersample[0];
	//	3: 	mixbb1<=dacundersample[1];
	//	4: 	mixbb1<=dacundersample[2];
	//	5: 	mixbb1<=dacundersample[3];
	//	6: 	mixbb1<=0;
	endcase
	case (dspif.mixbb2sel)
		0: 	mixbb2<=adc[1];
		1: 	mixbb2<=dacundersample[2];
		2: 	mixbb2<=dacundersample[3];
	//	0: 	mixbb2<=adc[0];
		//1: 	mixbb2<=adc[1];
		//2: 	mixbb2<=dacundersample[0];
		//3: 	mixbb2<=dacundersample[1];
		//4: 	mixbb2<=dacundersample[2];
		//5: 	mixbb2<=dacundersample[3];
		//6: 	mixbb2<=0;
	endcase

end

panzoomtrigif #(.NCHAN(10),.ADDRWIDTH(ACQBUF_W_ADDRWIDTH),.DATAWIDTH(ACQBUF_W_DATAWIDTH))acqpztif[0:1]();
panzoomtrigif #(.NCHAN(4),.ADDRWIDTH(DACMON_W_ADDRWIDTH),.DATAWIDTH(DACMON_W_DATAWIDTH))dacmonpztif[0:4]();
generate 
for (genvar i=0;i<2;i=i+1) begin: acqpztifwire
	reg stb_start_r=0;
	always @(posedge dspif.clk) begin
		stb_start_r<=dspif.stb_start;
        adc_d2[0] <= dspif.adc[0];
        adc_d2[1] <= dspif.adc[1];
        adc_d1[0] <= adc_d2[0];
        adc_d1[1] <= adc_d2[1];
        adc[0] <= adc_d1[0];
        adc[1] <= adc_d1[1];
	end
	assign acqpztif[i].clk=dspif.clk;
	assign acqpztif[i].reset=dspif.acqbufreset;
	assign acqpztif[i].chansel=dspif.acqchansel[i];
	assign acqpztif[i].stb_start=stb_start_r;
	assign acqpztif[i].delayaftertrig=dspif.delayaftertrig;
	assign acqpztif[i].decimator=dspif.decimator;
	assign acqpztif[i].chan[0]=adc[0];
	assign acqpztif[i].chan[1]=adc[1];
	//assign acqpztif[i].chan[2]=rdloelem[0].multix; //todo: break out these signals
	//assign acqpztif[i].chan[3]=rdloelem[0].multiy;
	//assign acqpztif[i].chan[4]=rdloelem[1].multix;
	//assign acqpztif[i].chan[5]=rdloelem[1].multiy;
	//assign acqpztif[i].chan[6]=rdloelem[2].multix;
	//assign acqpztif[i].chan[7]=rdloelem[2].multiy;
	//assign acqpztif[i].chan[8]=rdloelem[3].multix;
	//assign acqpztif[i].chan[9]=rdloelem[3].multiy;
	assign dspif.we_acqbuf[i]=acqpztif[i].we;
	assign dspif.addr_acqbuf[i]=acqpztif[i].addr;
	assign dspif.data_acqbuf[i]=acqpztif[i].data;
end
endgenerate
generate 
for (genvar i=0;i<4;i=i+1) begin: dacmonpztifwire
	reg stb_start_r=0;
	always @(posedge dspif.clk) begin
		stb_start_r<=dspif.stb_start;
	end
	assign dacmonpztif[i].clk=dspif.clk;
	assign dacmonpztif[i].reset=dspif.dacmonreset;
	assign dacmonpztif[i].chansel=dspif.dacmonchansel[i];
	assign dacmonpztif[i].stb_start=stb_start_r;
	assign dacmonpztif[i].delayaftertrig=dspif.delayaftertrig;
	assign dacmonpztif[i].decimator=dspif.decimator;
	assign dacmonpztif[i].chan[0]=dac[0];
	assign dacmonpztif[i].chan[1]=dac[1];
	assign dacmonpztif[i].chan[2]=dac[2];
	assign dacmonpztif[i].chan[3]=dac[3];
	assign dspif.we_dacmon[i]=dacmonpztif[i].we;
	assign dspif.addr_dacmon[i]=dacmonpztif[i].addr;
	assign dspif.data_dacmon[i]=dacmonpztif[i].data;
end
endgenerate


generate
for (genvar i=0;i<16;i=i+1) begin : step16
	for (genvar j=0;j<NDAC;j=j+1) begin
		always @(posedge dspif.clk) begin
			dac[j][(i+1)*16-1:i*16]<=dspif.dac[j][(i+1)*16-1:i*16];
		end
	end
	/*	for (genvar k=0;k<NDACMON;k=k+1) begin
	always @(posedge dspif.clk) begin
	dspif.data_dacmon[k][(i+1)*16-1:i*16]<=dac[k][(i+1)*16-1:i*16];
	end
	end
	*/
end
endgenerate

//update logic for handshaking
wire update_lastshotdone;
wire lastshotdone_true;
assign update_lastshotdone = done | dspif.stb_start;
assign lastshotdone_true = done & (~dspif.stb_start);

always @(posedge dspif.clk) begin
    if(update_lastshotdone) begin
        lastshotdone <= lastshotdone_true;
    end

    else begin
        lastshotdone <= lastshotdone;
    end
end

assign dspif.shotcnt=currentshotcnt;
assign dspif.lastshotdone=lastshotdone;



enum {IDLE	=4'b0000
,START		=4'b0001
,PROCRUN	=4'b0011
,ELEMBUSY	=4'b0010
,MORESHOT	=4'b0110
,SHOTADD	=4'b0111
,DONE		=4'b0101
} state=IDLE,nextstate=IDLE;
reg shotadd=0;

always @(posedge dspif.clk) begin
	if (dspif.reset) begin
		state <= IDLE;
	end
	else begin
		state <= nextstate;
	end
end
always @(*) begin
	nextstate=IDLE;
	case (state)
		IDLE: begin
			nextstate= dspif.stb_start ? START : IDLE;
		end
		START: begin
			nextstate=PROCRUN;
		end
		PROCRUN: begin
			nextstate= procdone_r ? ELEMBUSY : PROCRUN;
		end
		ELEMBUSY: begin
			nextstate= nobusy_r ? MORESHOT : ELEMBUSY;
		end
		MORESHOT: begin
			//nextstate=(|nshot)  & (|(nextshotcnt^nshot)) ? SHOTADD : DONE;
			nextstate=shotadd ? SHOTADD : DONE;
		end
		SHOTADD: begin
			nextstate=START;
		end
		DONE: begin
			nextstate=IDLE;
		end
        default: begin
            nextstate=IDLE;
        end
	endcase
end
always @(posedge dspif.clk) begin
	nextshotcnt<=shotcnt+1;
	shotadd <= (|(nextshotcnt^nshot)) | (~|nshot);
	nobusy_r<=&nobusy;
	procdone_r<=&procdone;
	if (dspif.reset) begin
		shotcnt<=0;
		done<=1'b0;
		procreset<=1'b1;
        nshot<=dspif.nshot;
	end
	else begin
		case (nextstate)
			IDLE: begin
				done<=1'b0;
				procreset<=1'b1;
				shotcnt<=0;
				nshot<=dspif.nshot;
			end
			START: begin
				done<=1'b0;
				procreset<=1'b0;
				shotcnt<=shotcnt;
			end
			PROCRUN: begin
				done<=1'b0;
				procreset<=1'b0;
				shotcnt<=shotcnt;
			end
			ELEMBUSY: begin
				done<=1'b0;
				procreset<=1'b1;
				shotcnt<=shotcnt;
			end
			MORESHOT: begin
				done<=1'b0;
				shotcnt<=shotcnt;
				procreset<=1'b1;
			end
			SHOTADD: begin
				done<=1'b0;
				shotcnt<=nextshotcnt;//+32'h1;
				currentshotcnt<=shotcnt;
				procreset<=1'b1;
			end
			DONE: begin
				done<=1'b1;
				shotcnt<=0;
				procreset<=1'b1;
			end
		endcase
	end
end

/*`include "iladsp.vh"*/
endmodule


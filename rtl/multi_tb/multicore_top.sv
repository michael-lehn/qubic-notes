// N QubiC qubit cores sharing one fproc_meas, driven by the gateware's shot sequencer.
//
// qcore: one core as the gateware generator emits it (vendor/gateware/top/src/dsp_coregen.py):
//   processor + instruction memory + qdrv, rdrv (elementconn + elementout) and rdlo
//   (elementconn + elementmixacc), each with envelope and frequency memories, and the
//   pulse-register glue of dsp_coregen.py:181-197. Widths follow the ZCU216 build
//   (vendor/gateware/top/zcu216_14_2/dsp_config.yaml): qdrv interp 4 / 16 samples,
//   rdrv interp 16 / 16 samples, rdlo interp 4 / 4 samples.
// multicore_top: N qcores, fproc_meas (dsp_build.py:279-287, 396-409) and the shot state
//   machine of vendor/gateware/dsp/dsp.sv:180-280 (procreset -> procreset_d -> cores).

// BRAM model: registered address, registered data (write port: whole read-width words)
module bram #(parameter AW = 10, parameter DW = 32)(
    input clk, input we, input [AW-1:0] waddr, input [DW-1:0] wdata,
    input [AW-1:0] raddr, output reg [DW-1:0] rdata);
    reg [DW-1:0] mem [0:(1 << AW) - 1];
    reg [AW-1:0] raddr_r = 0;
    always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        raddr_r <= raddr;
        rdata <= mem[raddr_r];
    end
endmodule

module qcore #(parameter CMD_ADDR_WIDTH = 16)(
    input clk,
    input reset,
    input [CMD_ADDR_WIDTH-1:0] cmd_write_addr,
    input [127:0] cmd_write,
    input cmd_write_enable,
    input [2:0] mem_sel,                 // 0 qdrv env, 1 qdrv freq, 2 rdrv env, 3 rdrv freq, 4 rdlo env, 5 rdlo freq
    input [11:0] mem_addr,
    input [511:0] mem_data,
    input mem_we,
    input [15:0] adc_sample,
    input [4:0] acc_shift,
    input meas_force_en,                 // testbench only: replace the demodulated sign bit
    input meas_force_bit,
    fproc_iface.proc fproc,
    output procdone,
    output reg nobusy,
    output reg meas_valid,               // -> fproc_meas.meas_valid[core] (dsp_build.py:403, after dsp_coregen.py:262)
    output reg meas_bit);                // -> fproc_meas.meas[core]       (dsp_build.py:404)

    // ---------------------------------------------------------------- processor
    cmd_mem_iface #(.CMD_ADDR_WIDTH(CMD_ADDR_WIDTH), .MEM_WIDTH(32), .MEM_TO_CMD(4)) memif();
    sync_iface #(.SYNC_BARRIER_WIDTH(8)) sync();
    pulse_iface #(.PHASE_WIDTH(17), .FREQ_WIDTH(9), .ENV_WORD_WIDTH(24), .AMP_WIDTH(16), .CFG_WIDTH(4)) pulseout();
    assign sync.ready = 1'b0;            // not driven in the generated gateware (dsp_coregen.py:349-355)

    proc #(.DATA_WIDTH(32), .CMD_WIDTH(128), .CMD_ADDR_WIDTH(CMD_ADDR_WIDTH), .REG_ADDR_WIDTH(4),
           .SYNC_BARRIER_WIDTH(8), .CMD_MEM_READ_LATENCY(3))
        dpr(.clk(clk), .reset(reset), .cmd_iface(memif), .fproc(fproc), .sync(sync),
            .pulseout(pulseout), .done_gate(procdone));

    genvar i;
    generate for (i = 0; i < 4; i = i + 1)
        cmd_mem #(.CMD_WIDTH(32), .ADDR_WIDTH(CMD_ADDR_WIDTH), .READ_LATENCY(3))
            mem(.clk(clk), .write_enable(cmd_write_enable), .cmd_in(cmd_write[32*(i+1)-1:32*i]),
                .write_address(cmd_write_addr), .read_address(memif.instr_ptr), .cmd_out(memif.mem_bus[i]));
    endgenerate

    // ---------------------------------------------------------------- signal generators
    ifelement #(.ENV_ADDRWIDTH(10), .ENV_DATAWIDTH(128), .FREQ_ADDRWIDTH(8), .FREQ_DATAWIDTH(512), .TCNTWIDTH(27)) qdrv_elem(.clk(clk));
    ifelement #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .FREQ_ADDRWIDTH(8), .FREQ_DATAWIDTH(512), .TCNTWIDTH(27)) rdrv_elem(.clk(clk));
    ifelement #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .FREQ_ADDRWIDTH(10), .FREQ_DATAWIDTH(128), .TCNTWIDTH(27)) rdlo_elem(.clk(clk));

    // dsp_coregen.py:181-193, one block per signal generator (index 0, 1, 2)
    always @(posedge clk) begin
        qdrv_elem.reset <= pulseout.reset;
        qdrv_elem.cmdstb <= pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b00);
        if (pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b00)) begin
            qdrv_elem.envstart <= pulseout.env_word[11:0];
            qdrv_elem.envlength <= pulseout.env_word[23:12];
            qdrv_elem.ampx <= pulseout.amp;
            qdrv_elem.ampy = 16'd0;
            qdrv_elem.freqaddr <= pulseout.freq;
            qdrv_elem.pini <= pulseout.phase;
            qdrv_elem.mode <= pulseout.cfg[3:2];
        end
        rdrv_elem.reset <= pulseout.reset;
        rdrv_elem.cmdstb <= pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b01);
        if (pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b01)) begin
            rdrv_elem.envstart <= pulseout.env_word[11:0];
            rdrv_elem.envlength <= pulseout.env_word[23:12];
            rdrv_elem.ampx <= pulseout.amp;
            rdrv_elem.ampy = 16'd0;
            rdrv_elem.freqaddr <= pulseout.freq;
            rdrv_elem.pini <= pulseout.phase;
            rdrv_elem.mode <= pulseout.cfg[3:2];
        end
        rdlo_elem.reset <= pulseout.reset;
        rdlo_elem.cmdstb <= pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b10);
        if (pulseout.cstrobe & (pulseout.cfg[1:0] == 2'b10)) begin
            rdlo_elem.envstart <= pulseout.env_word[11:0];
            rdlo_elem.envlength <= pulseout.env_word[23:12];
            rdlo_elem.ampx <= pulseout.amp;
            rdlo_elem.ampy = 16'd0;
            rdlo_elem.freqaddr <= pulseout.freq;
            rdlo_elem.pini <= pulseout.phase;
            rdlo_elem.mode <= pulseout.cfg[3:2];
        end
    end

    wire [9:0] qdrv_env_addr;   wire [127:0] qdrv_env_data;
    wire [7:0] qdrv_freq_addr;  wire [511:0] qdrv_freq_data;
    wire [11:0] rdrv_env_addr;  wire [31:0] rdrv_env_data;
    wire [7:0] rdrv_freq_addr;  wire [511:0] rdrv_freq_data;
    wire [11:0] rdlo_env_addr;  wire [31:0] rdlo_env_data;
    wire [9:0] rdlo_freq_addr;  wire [127:0] rdlo_freq_data;
    bram #(10, 128) qdrv_env (clk, mem_we && mem_sel == 0, mem_addr[9:0], mem_data[127:0], qdrv_env_addr, qdrv_env_data);
    bram #(8, 512)  qdrv_freq(clk, mem_we && mem_sel == 1, mem_addr[7:0], mem_data,         qdrv_freq_addr, qdrv_freq_data);
    bram #(12, 32)  rdrv_env (clk, mem_we && mem_sel == 2, mem_addr,      mem_data[31:0],   rdrv_env_addr, rdrv_env_data);
    bram #(8, 512)  rdrv_freq(clk, mem_we && mem_sel == 3, mem_addr[7:0], mem_data,         rdrv_freq_addr, rdrv_freq_data);
    bram #(12, 32)  rdlo_env (clk, mem_we && mem_sel == 4, mem_addr,      mem_data[31:0],   rdlo_env_addr, rdlo_env_data);
    bram #(10, 128) rdlo_freq(clk, mem_we && mem_sel == 5, mem_addr[9:0], mem_data[127:0],  rdlo_freq_addr, rdlo_freq_data);

    elementconn #(.ENV_ADDRWIDTH(10), .ENV_DATAWIDTH(128), .INTPRATIO(4), .FREQ_ADDRWIDTH(8), .FREQ_DATAWIDTH(512))
        qdrv_elemconn(.elem(qdrv_elem), .envaddr(qdrv_env_addr), .envdata(qdrv_env_data),
                      .freqaddr(qdrv_freq_addr), .freqdata(qdrv_freq_data));
    elementout #(.ENV_ADDRWIDTH(10), .ENV_DATAWIDTH(128), .FREQ_ADDRWIDTH(8), .FREQ_DATAWIDTH(512))
        qdrv_elem_out(.elem(qdrv_elem), .valid(), .multix(), .multiy());
    elementconn #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .INTPRATIO(16), .FREQ_ADDRWIDTH(8), .FREQ_DATAWIDTH(512))
        rdrv_elemconn(.elem(rdrv_elem), .envaddr(rdrv_env_addr), .envdata(rdrv_env_data),
                      .freqaddr(rdrv_freq_addr), .freqdata(rdrv_freq_data));
    elementout #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .FREQ_ADDRWIDTH(8), .FREQ_DATAWIDTH(512))
        rdrv_elem_out(.elem(rdrv_elem), .valid(), .multix(), .multiy());
    elementconn #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .INTPRATIO(4), .FREQ_ADDRWIDTH(10), .FREQ_DATAWIDTH(128))
        rdlo_elemconn(.elem(rdlo_elem), .envaddr(rdlo_env_addr), .envdata(rdlo_env_data),
                      .freqaddr(rdlo_freq_addr), .freqdata(rdlo_freq_data));

    wire accvalid;
    wire [31:0] accx, accy;
    elementmixacc #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .FREQ_ADDRWIDTH(10), .FREQ_DATAWIDTH(128), .ACCADDWIDTH(16))
        rdlo0mixacc1(.adcx({4{adc_sample}}), .adcy(64'd0), .shift(acc_shift), .elem(rdlo_elem.mix),
                     .gateout(), .accx(accx), .accy(accy), .stbout(accvalid));

    reg fproc_data_valid_r = 0;
    always @(posedge clk) begin
        fproc_data_valid_r <= accvalid;                                      // dsp_coregen.py:262
        meas_valid <= fproc_data_valid_r;                                    // dsp_build.py:403
        meas_bit <= meas_force_en ? meas_force_bit : accx[31];               // dsp_build.py:404 (+ test override)
        nobusy <= ~|{qdrv_elem.busy, rdrv_elem.busy, rdlo_elem.busy};        // dsp_coregen.py:372-376
    end
endmodule

module multicore_top #(parameter N = 3, parameter CMD_ADDR_WIDTH = 16)(
    input clk,
    input reset,                         // global reset (dspif.reset)
    input stb_start,                     // start an nshot experiment
    input [31:0] nshot,
    input [1:0] core_sel,
    input [CMD_ADDR_WIDTH-1:0] cmd_write_addr,
    input [127:0] cmd_write,
    input cmd_write_enable,
    input [2:0] mem_sel,
    input [11:0] mem_addr,
    input [511:0] mem_data,
    input mem_we,
    input [16*N-1:0] adc_samples,
    input [4:0] acc_shift,
    input [N-1:0] meas_force_en,         // testbench only: per-core measurement override
    input [N-1:0] meas_force_bit,
    output reg done,                     // all shots finished
    output reg [31:0] shotcnt);

    fproc_iface #(.FPROC_ID_WIDTH(8), .FPROC_RESULT_WIDTH(32)) fproc_if[N-1:0]();
    wire [N-1:0] procdone, nobusy, meas_valid, meas_bit;
    reg procreset = 1, procreset_d = 1;

    genvar k;
    generate for (k = 0; k < N; k = k + 1) begin: core
        qcore #(.CMD_ADDR_WIDTH(CMD_ADDR_WIDTH)) q(
            .clk(clk), .reset(procreset_d),
            .cmd_write_addr(cmd_write_addr), .cmd_write(cmd_write), .cmd_write_enable(cmd_write_enable && core_sel == k),
            .mem_sel(mem_sel), .mem_addr(mem_addr), .mem_data(mem_data), .mem_we(mem_we && core_sel == k),
            .adc_sample(adc_samples[16*k +: 16]), .acc_shift(acc_shift),
            .meas_force_en(meas_force_en[k]), .meas_force_bit(meas_force_bit[k]), .fproc(fproc_if[k]),
            .procdone(procdone[k]), .nobusy(nobusy[k]), .meas_valid(meas_valid[k]), .meas_bit(meas_bit[k]));
    end endgenerate

    fproc_meas #(.N_CORES(N), .N_MEAS(N)) fproc(.clk(clk), .reset(procreset_d), .meas(meas_bit),
        .meas_valid(meas_valid), .core(fproc_if));

    // ---------------------------------------------------------------- shot sequencer (dsp.sv)
    localparam IDLE = 0, START = 1, PROCRUN = 2, ELEMBUSY = 3, MORESHOT = 4, SHOTADD = 5, DONE = 6;
    reg [2:0] state = IDLE, nextstate;
    reg [31:0] nshot_r = 0, nextshotcnt = 0;
    reg shotadd = 0, procdone_r = 0, nobusy_r = 0;

    always @(posedge clk) procreset_d <= procreset;              // dsp.sv:40

    always @(posedge clk) state <= reset ? IDLE : nextstate;
    always @(*) begin
        case (state)
            IDLE:     nextstate = stb_start ? START : IDLE;
            START:    nextstate = PROCRUN;
            PROCRUN:  nextstate = procdone_r ? ELEMBUSY : PROCRUN;
            ELEMBUSY: nextstate = nobusy_r ? MORESHOT : ELEMBUSY;
            MORESHOT: nextstate = shotadd ? SHOTADD : DONE;
            SHOTADD:  nextstate = START;
            DONE:     nextstate = IDLE;
            default:  nextstate = IDLE;
        endcase
    end
    always @(posedge clk) begin
        nextshotcnt <= shotcnt + 1;
        shotadd <= (|(nextshotcnt ^ nshot_r)) | (~|nshot_r);
        nobusy_r <= &nobusy;
        procdone_r <= &procdone;
        if (reset) begin
            shotcnt <= 0; done <= 0; procreset <= 1; nshot_r <= nshot;
        end else case (nextstate)
            IDLE:     begin done <= 0; procreset <= 1; shotcnt <= 0; nshot_r <= nshot; end
            START:    begin done <= 0; procreset <= 0; end
            PROCRUN:  begin done <= 0; procreset <= 0; end
            ELEMBUSY: begin done <= 0; procreset <= 1; end
            MORESHOT: begin done <= 0; procreset <= 1; end
            SHOTADD:  begin done <= 0; shotcnt <= nextshotcnt; procreset <= 1; end
            DONE:     begin done <= 1; shotcnt <= 0; procreset <= 1; end
            default:  ;
        endcase
    end
endmodule

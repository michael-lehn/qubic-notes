// One QubiC qubit core reduced to what decides measurement-feedback timing:
//   processor (distributed_processor/hdl/proc.sv) + fproc_meas
//   + the rdlo signal generator and its mixer/accumulator (gateware/dsp/element.sv)
// Glue copied from the gateware generator:
//   gateware/top/src/dsp_coregen.py:181-197  (pulse register -> rdlo element)
//   gateware/top/src/dsp_coregen.py:255-263  (accvalid -> fproc_data_valid_r)
//   gateware/top/src/dsp_build.py:401-404    (-> fproc_meas_valid / fproc_meas_input = acc[63])
// Widths follow gateware/top/zcu216_14_2/dsp_config.yaml for rdlo (interp 4, 4 samples/clk,
// env 4096 x 32 bit, freq 4096 x 32 bit read 128 bit wide).
module core_meas_top #(
    parameter CMD_ADDR_WIDTH = 16,
    parameter MEM_READ_LATENCY = 3)(
    input clk,
    input reset,
    input [CMD_ADDR_WIDTH-1:0] cmd_write_addr,
    input [127:0] cmd_write,
    input cmd_write_enable,
    input [11:0] env_write_addr,
    input [31:0] env_write,
    input env_write_enable,
    input [9:0] freq_write_addr,
    input [127:0] freq_write,
    input freq_write_enable,
    input [15:0] adc_sample,            // ADC input, same value on all 4 samples of a clock
    input [4:0] acc_shift,
    output done_gate);

    // ------------------------------------------------------------ processor + FPROC
    cmd_mem_iface #(.CMD_ADDR_WIDTH(CMD_ADDR_WIDTH), .MEM_WIDTH(32), .MEM_TO_CMD(4)) memif();
    fproc_iface #(.FPROC_ID_WIDTH(8), .FPROC_RESULT_WIDTH(32)) fproc_if[0:0]();
    sync_iface #(.SYNC_BARRIER_WIDTH(8)) sync();
    pulse_iface #(.PHASE_WIDTH(17), .FREQ_WIDTH(9), .ENV_WORD_WIDTH(24), .AMP_WIDTH(16), .CFG_WIDTH(4)) pulseout();
    assign sync.ready = 1'b0;

    proc #(.DATA_WIDTH(32), .CMD_WIDTH(128), .CMD_ADDR_WIDTH(CMD_ADDR_WIDTH), .REG_ADDR_WIDTH(4),
           .SYNC_BARRIER_WIDTH(8), .CMD_MEM_READ_LATENCY(MEM_READ_LATENCY))
        dpr(.clk(clk), .reset(reset), .cmd_iface(memif), .fproc(fproc_if[0]), .sync(sync),
            .pulseout(pulseout), .done_gate(done_gate));

    genvar i;
    generate for (i = 0; i < 4; i = i + 1)
        cmd_mem #(.CMD_WIDTH(32), .ADDR_WIDTH(CMD_ADDR_WIDTH), .READ_LATENCY(MEM_READ_LATENCY))
            mem(.clk(clk), .write_enable(cmd_write_enable), .cmd_in(cmd_write[32*(i+1)-1:32*i]),
                .write_address(cmd_write_addr), .read_address(memif.instr_ptr), .cmd_out(memif.mem_bus[i]));
    endgenerate

    reg [0:0] fproc_meas_input = 0;
    reg [0:0] fproc_meas_valid = 0;
    fproc_meas #(.N_CORES(1), .N_MEAS(1)) fproc(.clk(clk), .reset(reset), .meas(fproc_meas_input),
        .meas_valid(fproc_meas_valid), .core(fproc_if));

    // ------------------------------------------------------------ rdlo signal generator (index 2)
    ifelement #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .FREQ_ADDRWIDTH(10), .FREQ_DATAWIDTH(128),
                .TCNTWIDTH(27)) rdlo_elem(.clk(clk));

    always @(posedge clk) begin
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

    // waveform memories (BRAM model: registered address + registered data)
    reg [31:0] env_mem [0:4095];
    reg [127:0] freq_mem [0:1023];
    wire [11:0] env_addr;
    wire [9:0] freq_addr;
    reg [11:0] env_addr_r = 0;
    reg [9:0] freq_addr_r = 0;
    reg [31:0] env_data = 0;
    reg [127:0] freq_data = 0;
    always @(posedge clk) begin
        if (env_write_enable) env_mem[env_write_addr] <= env_write;
        if (freq_write_enable) freq_mem[freq_write_addr] <= freq_write;
        env_addr_r <= env_addr;
        freq_addr_r <= freq_addr;
        env_data <= env_mem[env_addr_r];
        freq_data <= freq_mem[freq_addr_r];
    end

    elementconn #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .INTPRATIO(4), .FREQ_ADDRWIDTH(10), .FREQ_DATAWIDTH(128))
        rdlo_elemconn(.elem(rdlo_elem), .envaddr(env_addr), .envdata(env_data),
                      .freqaddr(freq_addr), .freqdata(freq_data));

    wire accvalid;
    wire [31:0] accx, accy;
    elementmixacc #(.ENV_ADDRWIDTH(12), .ENV_DATAWIDTH(32), .FREQ_ADDRWIDTH(10), .FREQ_DATAWIDTH(128),
                    .ACCADDWIDTH(16))
        rdlo0mixacc1(.adcx({4{adc_sample}}), .adcy(64'd0), .shift(acc_shift), .elem(rdlo_elem.mix),
                     .gateout(), .accx(accx), .accy(accy), .stbout(accvalid));

    reg fproc_data_valid_r = 0;
    always @(posedge clk) begin
        fproc_data_valid_r <= accvalid;                 // dsp_coregen.py:262
        fproc_meas_valid[0] <= fproc_data_valid_r;      // dsp_build.py:403
        fproc_meas_input[0] <= accx[31];                // dsp_build.py:404 (acc word bit 63 = accx[31])
    end
endmodule

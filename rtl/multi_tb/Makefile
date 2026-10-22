# N qubit cores (processor + qdrv/rdrv/rdlo signal generators) + fproc_meas + shot sequencer.
#   make QD_BIN=build/prog.json [QD_NSHOT=3] [QD_ADC="1,1,1;-1,1,1"] [QD_OUT=build/out.json]
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
QUBIC_ROOT ?= $(CURDIR)/../../vendor
DP := $(QUBIC_ROOT)/distributed_processor/hdl
GW := $(QUBIC_ROOT)/gateware/dsp
CH := $(QUBIC_ROOT)/common-hdl

VERILOG_SOURCES += $(DP)/alu.v $(DP)/cmd_mem.v $(DP)/ctrl.v $(DP)/instr_ptr.v $(DP)/qclk.v $(DP)/reg_file.v
VERILOG_SOURCES += $(DP)/cmd_mem_iface.sv $(DP)/fproc_iface.sv $(DP)/fproc_meas.sv $(DP)/pulse_iface.sv \
                   $(DP)/pulse_reg.sv $(DP)/sync_iface.sv $(DP)/proc.sv
VERILOG_SOURCES += $(GW)/element.sv $(GW)/ammod.v $(GW)/phtime.v
VERILOG_SOURCES += $(CH)/reg_delay1.v $(CH)/cordicg3.sv $(CH)/cmultiplier2.v
VERILOG_SOURCES += $(CURDIR)/multicore_top.sv
EXTRA_ARGS += -Wno-fatal -Wno-HIERPARAM --top-module multicore_top
COCOTB_TOPLEVEL = multicore_top
COCOTB_TEST_MODULES = test_multi

include $(shell cocotb-config --makefiles)/Makefile.sim

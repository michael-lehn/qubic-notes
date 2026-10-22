# Processor + fproc_meas + rdlo element/mixer: measurement-feedback timing on RTL.
#   make QD_BIN=build/ex6.json [QD_ADC=-1] [QD_SHIFT=0]
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
VERILOG_SOURCES += $(CURDIR)/core_meas_top.sv
EXTRA_ARGS += -Wno-fatal -Wno-HIERPARAM --top-module core_meas_top
COCOTB_TOPLEVEL = core_meas_top
COCOTB_TEST_MODULES = test_meas

include $(shell cocotb-config --makefiles)/Makefile.sim

# Run QD-compiled machine code on the processor RTL.
#   make QD_BIN=prog.json [QD_CORE=qubit_command0] [QD_MEAS=1,0,1] [QD_MAX_CYCLES=2000000]
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
QUBIC_ROOT ?= $(CURDIR)/../../vendor
DP := $(QUBIC_ROOT)/distributed_processor

VERILOG_SOURCES += $(wildcard $(DP)/hdl/*.v) $(wildcard $(DP)/hdl/*.sv)
VERILOG_SOURCES += $(DP)/sim_modules/toplevel_sim.sv
EXTRA_ARGS += -Wno-fatal -Wno-HIERPARAM
COCOTB_TOPLEVEL = toplevel_sim
COCOTB_TEST_MODULES = test_qd

include $(shell cocotb-config --makefiles)/Makefile.sim

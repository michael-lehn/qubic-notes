SIM ?= verilator
TOPLEVEL_LANG ?= verilog
QUBIC_ROOT ?= $(CURDIR)/../../vendor
DP := $(QUBIC_ROOT)/distributed_processor

VERILOG_SOURCES += $(wildcard $(DP)/hdl/*.v) $(wildcard $(DP)/hdl/*.sv)
VERILOG_SOURCES += $(DP)/sim_modules/toplevel_sim.sv
EXTRA_ARGS += -Wno-fatal -Wno-HIERPARAM
COCOTB_TOPLEVEL = toplevel_sim
COCOTB_TEST_MODULES = test_isa

include $(shell cocotb-config --makefiles)/Makefile.sim

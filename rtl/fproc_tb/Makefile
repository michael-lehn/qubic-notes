SIM ?= verilator
TOPLEVEL_LANG ?= verilog
QUBIC_ROOT ?= $(CURDIR)/../../vendor
DP := $(QUBIC_ROOT)/distributed_processor

# fproc_meas_sim_fixed.sv = sim_modules/fproc_meas_sim.sv with "()" added to the
# interface-array instantiation; Verilator rejects the original.
VERILOG_SOURCES += $(DP)/hdl/fproc_iface.sv $(DP)/hdl/fproc_meas.sv $(CURDIR)/fproc_meas_sim_fixed.sv
EXTRA_ARGS += -Wno-fatal -Wno-HIERPARAM --top-module fproc_meas_sim
COCOTB_TOPLEVEL = fproc_meas_sim
COCOTB_TEST_MODULES = test_fproc

include $(shell cocotb-config --makefiles)/Makefile.sim

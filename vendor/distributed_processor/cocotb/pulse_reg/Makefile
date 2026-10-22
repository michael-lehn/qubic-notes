SIM ?= verilator
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES += $(PWD)/../../hdl/pulse_reg.sv
VERILOG_SOURCES += $(PWD)/../../hdl/pulse_iface.sv
VERILOG_SOURCES += $(PWD)/../../sim_modules/pulsereg_sim.sv
EXTRA_ARGS += --trace --trace-structs
TOPLEVEL = pulsereg_sim
#COMPILE_ARGS += -Wno

MODULE = test_pulse_reg

include $(shell cocotb-config --makefiles)/Makefile.sim

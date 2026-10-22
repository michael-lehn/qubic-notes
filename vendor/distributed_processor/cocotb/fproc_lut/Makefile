SIM ?= verilator
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES += $(PWD)/../../sim_modules/fproc_lut_sim.sv
VERILOG_SOURCES += $(PWD)/../../hdl/*.v
VERILOG_SOURCES += $(PWD)/../../hdl/*.sv
VERILOG_SOURCES += $(PWD)/../../hdl/*.vh
#VERILOG_SOURCES += $(PWD)/../sim_modules/*.sv
EXTRA_ARGS += --trace --trace-structs
TOPLEVEL = fproc_lut_sim
#COMPILE_ARGS += -Wno

MODULE = test_lut

include $(shell cocotb-config --makefiles)/Makefile.sim

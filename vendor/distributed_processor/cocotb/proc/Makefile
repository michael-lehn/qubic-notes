SIM ?= verilator
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES += $(PWD)/../../hdl/*.v
VERILOG_SOURCES += $(PWD)/../../hdl/*.sv
VERILOG_SOURCES += $(PWD)/../../hdl/*.vh
VERILOG_SOURCES += $(PWD)/../../sim_modules/*.sv
EXTRA_ARGS += --trace --trace-structs
TOPLEVEL = toplevel_sim
COMPILE_ARGS += -Wno-fatal

MODULE = test_proc

include $(shell cocotb-config --makefiles)/Makefile.sim

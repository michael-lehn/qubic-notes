# QubiC Distributed Processor

A custom FPGA based processor for controlling superconducting qubits. Primarily designed for the QubiC control system, but can be ported to any system using an FPGA for DDS-based RF pulse sysnthesis. The full instruction set can be found [here](https://gitlab.com/LBL-QubiC/distributed_processor/-/wikis/Instruction-Set). Currently implemented on hardware with [QubiC](https://gitlab.com/LBL-QubiC/gateware/-/tree/rfsoc) on the ZCU216 RFSoC evaluation board.

## Gateware

All FPGA gateware is written in Verilog/SystemVerilog and can be found in [hdl](https://gitlab.com/LBL-QubiC/distributed_processor/-/tree/master/hdl). There is also a [simulation environment](https://gitlab.com/LBL-QubiC/distributed_processor/-/tree/master/cocotb/proc) which uses [cocotb](https://www.cocotb.org/) with a [Verilator (v4.106)](https://github.com/verilator/verilator/tree/v4.106) backend.

## Software

The software stack [(distproc)](https://gitlab.com/LBL-QubiC/distributed_processor/-/tree/master/python/distproc) consists of a series of tools for compiling gate-level quantum programs (including measurement-based control flow) to distributed processor machine code. The stack consists of a [compiler](https://gitlab.com/LBL-QubiC/distributed_processor/-/tree/master/python/distproc/compiler.py) and [assembler](https://gitlab.com/LBL-QubiC/distributed_processor/-/tree/master/python/distproc/assembler.py) layer.

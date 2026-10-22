# Qubit Control System (QubiC)

QubiC is an in-house developed FPGA based qubit control system developed at Lawrence Berkeley National Lab (LBNL) with the support of the US Department of Energy (DOE). The QubiC source code is released under a [LBNL modified BSD license](LICENSE).

This repo contains core supporting software for the QubiC 2.0 system. Currently, QubiC 2.0 is implemented on the Xilinx ZCU216 RFSoC evaluation board using a [pynq](http://www.pynq.io/) backend. The QubiC 2.0 gateware can be found [here](https://gitlab.com/LBL-QubiC/gateware/-/tree/rfsoc).

## Helpful Links for Getting Started

 - [Getting Started Guide](https://gitlab.com/LBL-QubiC/software/-/wikis/Getting-Started-with-QubiC-2.0-on-the-ZCU216) for configuring the ZCU216 to run QubiC
 - [API Reference](https://lbl-qubic.gitlab.io/software/)
 - [QubiC Homepage](https://lbl-qubic.gitlab.io)
 - [Understanding Channel Configuration](https://gitlab.com/LBL-QubiC/software/-/wikis/Understanding-Channel-Configuration) for the channel layout of the current gateware, and the gateware -> hardware channel mapping.
 - [demo notebooks](https://gitlab.com/LBL-QubiC/software/-/tree/rfsoc/examples?ref_type=heads) for writing and running simple qubic programs
 - more advanced examples can be found in the [repo](https://gitlab.com/LBL-QubiC/qce23tutorial) for our [IEEE Quantum Week 2023 Tutorial](https://sites.google.com/lbl.gov/qubicqce23?usp=sharing)
 - language references: 
   - [QubiC-IR](https://lbl-qubic.gitlab.io/distributed_processor/)
   - [distributed processor instruction set](https://gitlab.com/LBL-QubiC/distributed_processor/-/wikis/Instruction-Set)

## Dependencies
 - [distproc](https://gitlab.com/LBL-QubiC/distributed_processor/-/tree/master/python) (contains the low-level tools for compiling and assembling quantum programs)
 - [qubitconfig](https://gitlab.com/LBL-QubiC/experiments/qubitconfig) (QubiC configuration management system, for storing and tracking gate-to-pulse calibrations)
 - pynq
 - numpy
 - scipy
 - scikit-learn
 - matplotlib

## Other Relevant Repos
 - [qubic gateware](https://gitlab.com/LBL-QubiC/gateware/-/tree/rfsoc) contains the complete FPGA design (written primarily in Verilog) for QubiC 2.0
 - [distributed processor](https://gitlab.com/LBL-QubiC/distributed_processor) contains the HDL for the QubiC distributed processor, as well as the distproc module linked above
 - [chip calibration](https://gitlab.com/LBL-QubiC/experiments/chipcalibration) contains calibration routines for superconducting qubits (in early-stage development)
 - [QWIP](https://github.com/qnl/qwip) Quantum Workflows in Python.
 - [qcal](https://github.com/akelhashim/qcal) software for quantum calibration, characterization, and benchmarking.


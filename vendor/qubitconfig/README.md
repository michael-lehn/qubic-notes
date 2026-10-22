****************************

Qubit Control System (QubiC) Copyright (c) 2021, The Regents of 
the University of California, through Lawrence Berkeley National
Laboratory (subject to receipt of any required approvals from the
U.S. Dept. of Energy). All rights reserved.

If you have questions about your rights to use or distribute this software,
please contact Berkeley Lab's Intellectual Property Office at
IPO@lbl.gov.

NOTICE.  This Software was developed under funding from the U.S. Department
of Energy and the U.S. Government consequently retains certain rights.  As
such, the U.S. Government has been granted for itself and others acting on
its behalf a paid-up, nonexclusive, irrevocable, worldwide license in the
Software to reproduce, distribute copies to the public, prepare derivative 
works, and perform publicly and display publicly, and to permit others to do so.


****************************


Qubit Control System (QubiC) [1]

QubiC is an in-house developed FPGA based qubit control system developed at LBNL under the supporting from Department of Energy (DOE).
The QubiC source code is released under a [LBNL modified BSD license](Legal.txt).

The QubiC contains the hardware, FPGA gateware and software. Each in its own git submodule. 
This is the software part for QubiC.

The QubiC software takes in the quantum circuit and convert to the command format defined in the QubiC gateware interface, and execute the circuit on the quantum processing unit. 

This package implemented several typical quantum characterization verification and validication on QubiC platform, including the Readout alignment, One tone spectroscopy, Punch-out experiment, Two tone spectroscopy, Measure chevron pattern, Rabi time, Rabi amplitude, Coherence time measurement T1 and Ramsey (T2ramsey), Spin-echo (T2 spinecho) experiment. 

An automatication script is developed to streamline the single qubit gate and two qubits gate parameter optimization and randomized benchmarking.

1. https://arxiv.org/abs/2101.00071

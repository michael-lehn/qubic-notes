# QubiC-IR

The QubiC intermediate representation (QubiC-IR) is a **domain-specific** language for writing **dynamic quantum programs**, and compiling these programs to **QubiC hardware targets**. QubiC-IR is a _multi-level_ representation; users can supply code at a variety of abstraction levels and customize the compiler flow accordingly. A subset of QubiC-IR is directly compilable to QubiC (distributed processor) assembly code; the compiler tools provide a comprehensive set of passes for lowering the full IR to this subset. Of course, users may wish to write their own passes if more flexibility is needed.

The QubiC-IR feature set mirrors that of the [distributed processor](https://gitlab.com/LBL-QubiC/distributed_processor), and includes **quantum gate** and **pulse-level** operations, arbitrary **measurement-based control flow** (branching and looping), arithmetic, and register-based **pulse parameterization** (e.g. pulse phases and amplitudes can be altered dynamically on-FPGA). Programs can be represented as either **JSON strings** (for portability) or **python objects** (used by compiler tools).

# Helpful External Links

  - [Getting Started Guide](https://gitlab.com/LBL-QubiC/software/-/wikis/Getting-Started-with-QubiC-2.0-on-the-ZCU216) for configuring the ZCU216 to run QubiC
  - [demo notebooks](https://gitlab.com/LBL-QubiC/software/-/tree/master/examples?ref_type=heads) for writing and running simple qubic programs
  - [distributed processor instruction set](https://gitlab.com/LBL-QubiC/distributed_processor/-/wikis/Instruction-Set)


## Declaring Variables

Variables can be declared using the `Declare` instruction:

    {'name': 'declare', 'var': 'my_var', 'dtype': 'int', 'scope': ['Q0']}

or 
    
    Declare(var='my_var', dtype='int', scope=['Q0'])

## Types

Variables are typed; currently three data types are supported:

  - `'int'`: 32-bit signed integer (default)
  - `'amp'`: indicates a variable used to parameterize a pulse amplitude; can be a floating point value between 0 and 1
  - `'phase'`: indicates a variable used to parameterize a pulse phase; can be a floating point value between 0 and 2$\pi$

Note that the `'amp'` and `'phase'` types are NOT actually floating point in hardware; they are fixed-point words with formats given by [qubic.rfsoc.hwconfig]. Rather, what is meant above is that values with python `float` type can be used by instructions that modify these variables; conversion to the proper fixed-point format is done by the assembler.

## Initializing Variables

Variables can be (re-)initialized using the `SetVar` instruction:
    
    {'name': 'set_var', 'var': 'my_var', 'value': 0}

or

    SetVar(var='my_var', value=0)

where `value` can either be an immediate (numerical) value or another variable.

## ALU operations

Arithmetic can be performed on variables using the `Alu` instruction:

    {'name': 'alu', 'lhs': 3, 'op': 'add', 'rhs': 'my_var', 'out': 'my_var'} //add 3 to 'my_var'

or

    Alu(lhs=3, op='add', rhs='my_var', out='my_var')

This instruction has the following fields:

  - `lhs`: Left-hand side input to the binary operation; can be an immediate (of the same type as `rhs` and `out`), or a variable
  - `rhs`: Right-hand side input to the binary operation; must be a variable
  - `op`: ALU operation. Currently supported operations are:
    - `'add'`: `out` = `lhs` + `rhs`
    - `'sub'`: `out` = `lhs` - `rhs`
    - `'ge'`: `out` = `lhs` > `rhs`
    - `'le'`: `out` = `lhs` < `rhs`
    - `'eq'`: `out` = `lhs` == `rhs`
    - `'id0'`: `out` = `lhs`
    - `'id1'`: `out` = `rhs`
    - `'zero'`: `out` = 0

  - `out`: Destination variable for the result of the operation
  - `scope`: Instruction [scope](scope.md) (optional; can be set by a [compiler pass](../api/ir_passes.md#distproc.ir.passes.RescopeVars))

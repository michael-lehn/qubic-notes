"""qdc: compile a .qd file to QubiC-IR, assembly and machine code."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import backend
from .diag import Diagnostics, QdError
from .lower import Lowering
from .sema import Sema
from .syntax import parse
from .target import DEFAULT_CHANNELS, DEFAULT_QCHIP, Target


class _QubicNoise(logging.Filter):
    """QubiC warns on every loop; QD warns precisely, at the gate that causes it (sema._gate)."""
    def filter(self, record):
        return 'Z-phase resolution inside loops' not in record.getMessage()


def quiet_qubic():
    logging.basicConfig()
    for h in logging.root.handlers:
        h.addFilter(_QubicNoise())


def front_end(source: str, filename: str, target: Target):
    """Source -> QubiC-IR (list of dicts). Raises QdError."""
    diag = Diagnostics(filename, source)
    sema = Sema(target, diag)
    mir = sema.run(parse(source))
    ir = Lowering(sema, mir, target).emit()
    return ir, diag


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='qdc', description=__doc__)
    ap.add_argument('file')
    ap.add_argument('--ir', action='store_true', help='print the generated QubiC-IR')
    ap.add_argument('--asm', action='store_true', help='print per-core assembly')
    ap.add_argument('--bin', action='store_true', help='print 128-bit words with decoding')
    ap.add_argument('--timing', action='store_true', help='print the static schedule (default if nothing else)')
    ap.add_argument('--check', action='store_true', help='front-end checks only, no QubiC compile')
    ap.add_argument('--emit-ir', metavar='OUT.json', help='write the QubiC-IR as JSON')
    ap.add_argument('--emit-bin', metavar='OUT.json', help='write machine words per core (hex) as JSON')
    ap.add_argument('--qchip', default=DEFAULT_QCHIP)
    ap.add_argument('--channels', default=DEFAULT_CHANNELS)
    a = ap.parse_args(argv)
    quiet_qubic()

    source = open(a.file).read()
    target = Target(a.qchip, a.channels)
    diag = Diagnostics(a.file, source)
    try:
        ir, diag = front_end(source, a.file, target)
    except QdError as e:
        print(diag.format_error(e), file=sys.stderr)
        return 1
    if diag.warnings:
        print(diag.format_warnings(), file=sys.stderr)
    if a.emit_ir:
        with open(a.emit_ir, 'w') as f:
            json.dump(ir, f, indent=1)
    if a.ir:
        print(json.dumps(ir, indent=1))
    if a.check:
        print(f'{a.file}: ok', file=sys.stderr)
        return 0
    b = backend.build(ir, target)
    if a.emit_bin:
        with open(a.emit_bin, 'w') as f:
            mems = {name.strip(':'): [f'{w:08x}' for w in __import__('numpy').frombuffer(buf, dtype='<u4')]
                    for name, buf in b.exe.program_binaries.items() if 'command' not in name}
            json.dump({**{core: [f'{w:032x}' for w in ws] for core, ws in b.words().items()},
                       'memories': mems}, f, indent=1)
    if a.asm:
        print(backend.assembly(b))
    if a.bin:
        print(backend.listing(b))
    if a.timing or not (a.ir or a.asm or a.bin):
        print(backend.timing(b, target))
    return 0


if __name__ == '__main__':
    sys.exit(main())

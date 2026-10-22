#!/usr/bin/env bash
# Create .venv with everything needed to run compiler/, qdsl/ and rtl/.
# QubiC sources come only from vendor/ (see vendor/MANIFEST.md); packages are installed from
# build copies so vendor/ stays pristine.
set -euo pipefail
cd "$(dirname "$0")"
V=vendor
PY="${PYTHON:-/opt/homebrew/opt/python@3.12/bin/python3.12}"   # cocotb does not build on 3.15

rm -rf .build && mkdir -p .build/qubicpkg/qubic/rfsoc
cp -R $V/qubitconfig .build/qubitconfig
cp -R $V/distributed_processor/python .build/distproc
# Our compiler extension: IncQclk (runtime delay). See patches/README.md.
for p in patches/distproc-*.patch; do patch -s -p1 -d .build/distproc < "$p"; done
# Only the parts of the 'software' package the scripts need (RFSoC element configs + pulse shapes).
cp $V/software/qubic/__init__.py $V/software/qubic/pulse_factory.py .build/qubicpkg/qubic/
cp $V/software/qubic/rfsoc/__init__.py $V/software/qubic/rfsoc/hwconfig.py .build/qubicpkg/qubic/rfsoc/

"$PY" -m venv .venv
.venv/bin/pip install -q attrs networkx parse numpy pandas cocotb lark ipdb
.venv/bin/pip install -q --no-deps .build/qubitconfig .build/distproc
echo "done: source env.sh, then see README.md"

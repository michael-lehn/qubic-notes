# source this file: puts the venv, qdsl and the copied 'qubic' package on the path
_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export QUBIC_ROOT="$_here/vendor"            # all QubiC sources are vendored (vendor/MANIFEST.md)
export PATH="$_here/.venv/bin:$PATH"
export PYTHONPATH="$_here:$_here/.build/qubicpkg${PYTHONPATH:+:$PYTHONPATH}"

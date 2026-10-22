#!/usr/bin/env bash
# QD source -> machine code -> processor RTL, with checks. Run after `source env.sh`.
set -euo pipefail
cd "$(dirname "$0")"
EX=../../qdsl/examples
OUT=build && mkdir -p $OUT

sim() {  # sim NAME MEAS
    make QD_BIN=$OUT/$1.json QD_MEAS=$2 QD_OUT=$OUT/$1_m$2.result.json > $OUT/$1_m$2.log 2>&1 \
        || { echo "simulation failed, see $OUT/$1_m$2.log"; exit 1; }
}

python -m qdsl $EX/ex6_active_reset.qd --emit-bin $OUT/ex6.json > /dev/null
python -m qdsl $EX/t1_runtime.qd      --emit-bin $OUT/t1.json  > /dev/null
sim ex6 1; sim ex6 0; sim t1 0

python - <<'PY'
import json
load = lambda f: json.load(open(f'build/{f}.result.json'))
QDRV, RDRV = 0, 1                                    # cfg = element index on the core

m1, m0 = load('ex6_m1'), load('ex6_m0')
x90 = lambda r: [s['qclk'] for s in r['strobes'] if s['cfg'] == QDRV]
last_read = lambda r: [s['qclk'] for s in r['strobes'] if s['cfg'] == RDRV][-1]
assert x90(m1) == [1382, 1394] and x90(m0) == [], (x90(m1), x90(m0))
assert last_read(m1) == last_read(m0) == 1406
print('active reset : meas=1 plays X90 X90 at qclk 1382/1394, meas=0 skips them; '
      'final readout at qclk 1406 either way')

t1 = load('t1_m0')
reads = [s for s in t1['strobes'] if s['cfg'] == RDRV]
pis = [s for s in t1['strobes'] if s['cfg'] == QDRV][1::2]
waits = [r['cycle'] - p['cycle'] for p, r in zip(pis, reads)]
assert waits == [16 + 5000 * k for k in range(5)], waits
assert len({r['qclk'] for r in reads}) == 1
print(f'runtime delay: pi-pulse -> readout = {waits} clocks '
      f'(= 0, 10, 20, 30, 40 us + 32 ns), one loop, same qclk every iteration')
print('PASS')
PY

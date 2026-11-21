#!/usr/bin/env bash
# Reproducible diagnostic run. Read-only with respect to the reducer (aliquot/).
# Outputs land in diagnostics/records and diagnostics/ledgers; rerun needs fresh
# ledger names because published editions are immutable.
set -euo pipefail
cd "$(dirname "$0")/../.."

REC=diagnostics/records
LED=diagnostics/ledgers
rm -f "$LED"/*.sqlite
mkdir -p "$REC" "$LED"

echo '== 1. original entrypoint: recompute the two repository samples =='
python3 -m aliquot preview examples/baseline.json > "$REC/01_baseline_preview.json"
python3 -m aliquot preview examples/changed.json  > "$REC/02_changed_preview.json"
set +e
python3 -m aliquot preview examples/invalid.json >"$REC/00_invalid_stderr.txt" 2>&1
rc=$?
set -e
test "$rc" -eq 2
echo "invalid.json rejected with status 2 (recorded in 00_invalid_stderr.txt)"

echo '== 2. isolated ledger: publish + replay both samples =='
python3 -m aliquot publish examples/baseline.json "$LED/sample_ledger.sqlite" original
python3 -m aliquot publish examples/changed.json  "$LED/sample_ledger.sqlite" revised
python3 -m aliquot history "$LED/sample_ledger.sqlite" > "$REC/07_sample_history.json"
python3 -m aliquot replay  "$LED/sample_ledger.sqlite" original > "$REC/08_baseline_replay.json"
python3 -m aliquot replay  "$LED/sample_ledger.sqlite" revised  > "$REC/09_revised_replay.json"

echo '== 3. constructed legal control (same station/method; invariants preserved) =='
python3 -m aliquot preview diagnostics/control/control_swap_t3_t4.json \
  > "$REC/03_control_preview.json"
python3 -m aliquot publish diagnostics/control/control_swap_t3_t4.json \
  "$LED/control_ledger.sqlite" control_swap
python3 -m aliquot replay "$LED/control_ledger.sqlite" control_swap \
  > "$REC/04_control_replay.json"

echo '== 4. time-window reconciliation along certified cumulative flow =='
python3 -I diagnostics/tools/reconcile.py \
  baseline="$REC/01_baseline_preview.json" \
  revised="$REC/02_changed_preview.json" \
  control="$REC/03_control_preview.json" \
  > "$REC/05_window_reconciliation.json"

echo '== 5. isolation replay: holding-time attribution =='
python3 -I diagnostics/tools/attribution.py \
  baseline="$REC/01_baseline_preview.json" \
  revised="$REC/02_changed_preview.json" \
  control="$REC/03_control_preview.json" \
  > "$REC/06_attribution.json"

echo '== 6. cross-checks =='
python3 -I - "$REC" <<'PY'
import json, sys
rec = sys.argv[1]
base = json.load(open(f'{rec}/01_baseline_preview.json'))
chg  = json.load(open(f'{rec}/02_changed_preview.json'))
ctl  = json.load(open(f'{rec}/03_control_preview.json'))
spec = [
    (base['flow']['known_liters'], 72, 'baseline known liters'),
    (base['flow']['anchored_liters'], 52, 'baseline anchored prefix'),
    (base['methods']['m1']['supported_liters'], 30, 'baseline m1 liters'),
    (base['methods']['m1']['load_mg'], [20, 50], 'baseline m1 load'),
    (chg['methods']['m1']['supported_liters'], 20, 'revised m1 liters'),
    (chg['methods']['m1']['load_mg'], [0, 30], 'revised m1 load'),
]
for got, want, label in spec:
    assert got == want, (label, got, want)
# control invariants: same certified liters and load closure, shifted support
assert ctl['methods']['m1']['supported_liters'] == 30
assert ctl['methods']['m1']['load_mg'] == [20, 50]
assert [e['assay'] for e in ctl['assays'] if e['state'] == 'supported'] == ['a1', 'a2', 'a3']
assert [e['assay'] for e in base['assays'] if e['state'] == 'supported'] == ['a1', 'a2', 'a4']
# replays must equal previews and stored hashes verified by the entrypoint itself
for pair in (('08_baseline_replay.json', '01_baseline_preview.json'),
             ('09_revised_replay.json', '02_changed_preview.json'),
             ('04_control_replay.json', '03_control_preview.json')):
    assert json.load(open(f'{rec}/{pair[0]}')) == json.load(open(f'{rec}/{pair[1]}')), pair
print('all cross-checks passed')
PY
echo OK

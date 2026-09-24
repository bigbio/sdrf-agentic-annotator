#!/bin/bash
# One iteration of the skills tuning loop.
#
#   ./tune.sh tune  <label> [model-id] [plugin-src]   # iterate here: 8 datasets, deterministic only
#   ./tune.sh eval  <label> [model-id] [plugin-src]   # spend the held-out 4 ONCE, at the end
#
# The judge is deliberately not run: it needs quota, and what a skills change should move is
# validity and completeness, which are deterministic. Treat accuracy as a regression guard
# (it must not fall), never as the target -- it measures agreement with one curator's choices.
set -euo pipefail
cd "$(dirname "$0")"

SPLIT=${1:?tune or eval}
LABEL=${2:?a short name for this iteration, e.g. baseline or tmt-label-rule}
MODEL=${3:-haiku-4.5-skills}   # weakest model: it fails loudest, so missing rules show up fastest
PLUGIN=${4:-}                  # path to the edited sdrf-skills plugin; default = the installed one

ACC=$(awk -F'\t' -v s="$SPLIT" 'NR>1 && $4==s {printf "%s%s", sep, $1; sep=","}' data/split.tsv)
[ -n "$ACC" ] || { echo "no accessions for split '$SPLIT'"; exit 1; }
OUT="outputs-tune/$SPLIT-$LABEL"

echo "split=$SPLIT label=$LABEL model=$MODEL"
echo "datasets: $ACC"
uv run sdrf-bench run --only "$MODEL" --accessions "$ACC" --outputs "$OUT" --workers 1 \
  ${PLUGIN:+--plugin-src "$PLUGIN"}
uv run sdrf-bench score --outputs "$OUT" --no-judge --results "$OUT/runs.jsonl"

uv run python - "$OUT/runs.jsonl" <<'PY'
import json, statistics, sys, collections
rs = [json.loads(l) for l in open(sys.argv[1])]
print(f"\n{'qtype':6s} {'n':>3s} {'valid':>6s} {'compl':>6s} {'accur':>6s} {'errors':>7s} {'clean':>7s}")
by = collections.defaultdict(list)
for r in rs:
    by[r["qtype"]].append(r)
    by["ALL"].append(r)
for q in sorted(by, key=lambda k: (k != "ALL", k)):
    v = by[q]
    m = lambda k: statistics.fmean(x[k] for x in v if x.get(k) is not None)
    ne = [x["n_errors"] for x in v if x.get("n_errors") is not None]
    clean = sum(1 for x in ne if x == 0)
    print(f"{q:6s} {len(v):3d} {m('validity'):6.2f} {m('completeness'):6.2f} {m('accuracy'):6.2f} "
          f"{statistics.fmean(ne) if ne else 0:7.2f} {clean:4d}/{len(ne):<3d}")
print("\nTargets: validity and completeness up, errors down. Accuracy must not fall.")
PY

#!/bin/bash
# Paced Claude runs: one run at a time. When a pass leaves crashed runs (almost always the usage
# limit), wait and resume, across as many usage windows as it takes. Then score (+ judge) and report.
set -u
cd "$(dirname "$0")"
CLAUDE=opus-5-skills,sonnet-5-skills,haiku-4.5-skills,opus-5-raw,sonnet-5-raw,haiku-4.5-raw
WAIT_MINUTES=${WAIT_MINUTES:-30}
# Which pack to run against, and where results land. Defaults keep the original v1 behaviour.
DATA=${DATA:-data}
OUTPUTS=${OUTPUTS:-outputs}
RESULTS=${RESULTS:-results}
stamp() { echo "=== $(date '+%F %T') $*"; }
crashed() {  # crashed runs on datasets still in the manifest (replaced datasets are ignored)
  uv run python - <<'PY'
import csv, glob, os
sel = {r["accession"] for r in csv.DictReader(open(os.environ["DATA"] + "/manifest.tsv"), delimiter="\t")}
models = os.environ.get("CLAUDE", "").split(",")
print(sum(1 for m in models for f in glob.glob(f"{os.environ['OUTPUTS']}/{m}/*/error.json")
          if os.path.basename(os.path.dirname(f)).split("__")[0] in sel))
PY
}
export CLAUDE DATA OUTPUTS RESULTS
for attempt in $(seq 1 60); do
  stamp "Claude pass $attempt (one run at a time)"
  uv run sdrf-bench run --only "$CLAUDE" --workers 1 --data "$DATA" --outputs "$OUTPUTS"
  n=$(crashed)
  [ "$n" -eq 0 ] && break
  stamp "$n runs crashed (usage limit?); waiting $WAIT_MINUTES min"; sleep $((WAIT_MINUTES * 60))
done
for attempt in $(seq 1 60); do
  stamp "score + judge pass $attempt"
  uv run sdrf-bench score --data "$DATA" --outputs "$OUTPUTS" --out "$RESULTS/runs.jsonl"
  grep -q judge_pending "$RESULTS/runs.jsonl" || break
  stamp "judge hit the usage limit; waiting $WAIT_MINUTES min"; sleep $((WAIT_MINUTES * 60))
done
stamp "report"; uv run sdrf-bench report --results "$RESULTS/runs.jsonl" --out "$RESULTS" --data "$DATA"
stamp "done"

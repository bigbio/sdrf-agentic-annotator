#!/bin/bash
# Fast pass: the listed configurations (ORDER), three runs at a time, one paper condition (MANUSCRIPT)
# No judge. Resumes across usage windows; finished runs are skipped.
set -u
cd "$(dirname "$0")"
export SDRF_BENCH_ALLOW_PLUGIN_TOOLS=1
DATA=${DATA:-data}; OUTPUTS=${OUTPUTS:-outputs}; RESULTS=${RESULTS:-results/main}
MANUSCRIPT=${MANUSCRIPT:-off}  # off | on | both (on: only datasets with a CC paper)
ORDER=${ORDER:-sonnet-5-skills,haiku-4.5-skills,opus-5-skills}
stamp() { echo "=== $(date '+%F %T') $*"; }
for m in ${ORDER//,/ }; do
  for attempt in $(seq 1 20); do
    stamp "$m pass $attempt"
    uv run sdrf-bench run --only "$m" --workers 3 --manuscript "$MANUSCRIPT" --data "$DATA" --outputs "$OUTPUTS"
    n=$(ls "$OUTPUTS/$m"/*/error.json 2>/dev/null | wc -l | tr -d ' ')
    [ "$n" -eq 0 ] && break
    stamp "$n crashed (usage limit?); waiting 20 min"; sleep 1200
  done
done
stamp "scoring (no judge)"
uv run sdrf-bench score --data "$DATA" --outputs "$OUTPUTS" --out "$RESULTS/runs.jsonl" --no-judge
stamp "done"

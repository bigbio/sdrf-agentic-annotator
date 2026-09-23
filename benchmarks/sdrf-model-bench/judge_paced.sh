#!/bin/bash
# Score + judge the runs whose cached score.json was removed, resuming across usage windows,
# then re-render the slide. Already-judged runs stay cached and are not re-judged.
set -u
cd "$(dirname "$0")"
DATA=${DATA:-data-v2}; OUTPUTS=${OUTPUTS:-outputs-v2}; RESULTS=${RESULTS:-results-v2}
WAIT_MINUTES=${WAIT_MINUTES:-30}
stamp() { echo "=== $(date '+%F %T') $*"; }
for attempt in $(seq 1 60); do
  stamp "score + judge pass $attempt"
  uv run sdrf-bench score --data "$DATA" --outputs "$OUTPUTS" --out "$RESULTS/runs.jsonl"
  n=$(ls "$OUTPUTS"/*/*/score.json 2>/dev/null | wc -l | tr -d ' ')
  stamp "cached scores: $n/138"
  grep -q judge_pending "$RESULTS/runs.jsonl" || [ "$n" -lt 138 ] || break
  stamp "judge incomplete; waiting $WAIT_MINUTES min"; sleep $((WAIT_MINUTES * 60))
done
stamp "report"; uv run sdrf-bench report --results "$RESULTS/runs.jsonl" --out "$RESULTS" --data "$DATA"
stamp "done"

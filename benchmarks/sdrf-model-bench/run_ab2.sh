#!/bin/bash
# 4-run A/B (one dataset) with the plugin's own tools allowed in the sandbox: the shipped skill (main) and the
# optimized skill (branch), one dataset (PXD000878: fractionated; the shipped skill's worst case) x sonnet + haiku, ms-off, same frozen evidence.
# Arms run one after the other, one run at a time, resuming across usage windows.
set -u
cd "$(dirname "$0")"
export SDRF_BENCH_ALLOW_PLUGIN_TOOLS=1
OLD_SRC=$HOME/.claude/plugins/marketplaces/sdrf-skills          # main @ 13eeff4, untouched
NEW_SRC=/Users/yperez/work/sdrf-workspace/sdrf-skills            # optimize-annotate-offline-path
ACC=PXD000878
MODELS=sonnet-5-skills,haiku-4.5-skills
stamp() { echo "=== $(date '+%F %T') $*"; }
arm() {  # name src
  for attempt in $(seq 1 40); do
    stamp "arm $1 pass $attempt"
    uv run sdrf-bench run --only "$MODELS" --workers 1 --data data-v2 --outputs "outputs-v3-$1" \
      --accessions "$ACC" --manuscript off --plugin-src "$2"
    n=$(ls "outputs-v3-$1"/*/*/usage.json 2>/dev/null | wc -l | tr -d ' ')
    stamp "arm $1 runs done: $n/2"
    [ "$n" -ge 2 ] && return 0
    stamp "incomplete; waiting 30 min"; sleep 1800
  done
}
stamp "old skill source: $(git -C "$OLD_SRC" log --oneline -1)"
stamp "new skill source: $(git -C "$NEW_SRC" log --oneline -1)"
arm old "$OLD_SRC"
arm new "$NEW_SRC"
for a in old new; do
  stamp "scoring $a"; mkdir -p "results-v3-$a"
  uv run sdrf-bench score --data data-v2 --outputs "outputs-v3-$a" --out "results-v3-$a/runs.jsonl" --no-judge
done
stamp "done"

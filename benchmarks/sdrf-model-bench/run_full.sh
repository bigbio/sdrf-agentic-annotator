#!/bin/bash
# Staged full benchmark: Claude arms, a retry pass, then local models, then score + report.
# Safe to re-run: finished runs are skipped, crashed or rate-limited runs are retried.
set -u
cd "$(dirname "$0")"
CLAUDE=opus-5-skills,sonnet-5-skills,haiku-4.5-skills,opus-5-raw,sonnet-5-raw,haiku-4.5-raw
LOCAL=gemma4-12b-think,qwen3-4b-think,gemma2-9b-raw,qwen2.5-3b-raw
stamp() { echo "=== $(date '+%F %T') $*"; }
while pgrep -f "sdrf-bench run" > /dev/null; do sleep 60; done  # never run two matrices at once
stamp "phase 1: Claude"; uv run sdrf-bench run --only "$CLAUDE"
stamp "phase 1b: retry crashed / rate-limited Claude runs"; uv run sdrf-bench run --only "$CLAUDE"
stamp "phase 2: local models (thinking where supported)"; uv run sdrf-bench run --only "$LOCAL"
stamp "phase 2b: retry crashed local runs"; uv run sdrf-bench run --only "$LOCAL"
stamp "phase 3: score + judge"; uv run sdrf-bench score
stamp "phase 4: report"; uv run sdrf-bench report
stamp "done"

# Results: sdrf-skills across three benchmarks

Three independent benchmarks, scored with **one rubric**. The rubric is the deterministic score of
`sdrf-bench score`: validity 20, completeness 15, accuracy 50, specificity 15. It uses the triage
classes of bigbio/sdrf-skills PR #24, and every run is compared against the same curated references.
All figures come from `sdrf-bench report` and share one style.

| Benchmark | Question | Datasets | Figures |
|---|---|---|---|
| **sdrf-model-bench v4** (ours) | Does the redesigned sdrf-skills (`contract` + `build`) beat the prompt alone, and at what cost? | 15 (TMT, LFQ, DIA), frozen in `data-v2/` | `results-v4-off/` |
| **Chengxin Dai**: manual vs skills | How does a skills session compare with a human curator, in quality and time? | 4 (`data-ext/`) | `results-ext-all/slide_dai*`, `backup_9_*` |
| **Jonas Scheid**: sdrf-skills PR #24 | With vs without skills, same model, same session type | 2 (`data-ext/`) | `results-ext-all/slide_jonas*`, `backup_8_*` |

## 1. sdrf-model-bench v4: the redesigned skills

15 datasets, annotated offline from the frozen PRIDE record and the file list, without the paper.
One replicate per dataset. Raw arms are the v2 runs, with prompts unchanged. The v2 skills arm is
the skills as shipped before the redesign.

| model | prompt only | skills v2 | **skills v4** | cost/SDRF v2 → v4 | minutes v2 → v4 | validity v2 → v4 |
|---|---|---|---|---|---|---|
| Opus 5 | 79.4 | 82.0 | **80.2** | $4.90 → **$2.65** | 12.9 → 7.9 | 1.00 → 0.99 |
| Sonnet 5 | 76.1 | 81.1 | **78.7** | $2.88 → **$1.74** | 13.5 → 9.9 | 1.00 → 1.00 |
| Haiku 4.5 | 69.5 | 58.7 | **76.9** | $0.53 → **$0.36** | 7.6 → 5.0 | 0.81 → 1.00 |

- **Haiku improves the most.** It was 11 points below its own prompt-only run in v2 and is now
  7.4 points above it, at the prompt-only cost. It improved on 14 of 15 datasets, and every file
  it writes now validates.
- **Opus and Sonnet got cheaper and faster.** Cost fell 40–46% and time 25–40%, while they stayed
  1–3 points above prompt-only. They are about 2 points below v2, which is within the spread of a
  single replicate. The cells that dropped are the next thing to look at.
- **All three configurations beat the no-evidence baseline**: a file filled with priors scores 64.

Figures: `results-v4-off/slide.png` (headline), `backup_4_components.png` (where the points come
from), `backup_5_cost_vs_quality.png`, and `backup_7_triage.png` (kinds of disagreement).

Reproduce:

```bash
uv run sdrf-bench report --results results-v4/runs.jsonl --manuscript off --deterministic \
    --out results-v4-off --data data-v2
```

## 2. The collaborators' benchmarks, rescored

Their own SDRFs (`external/`) are scored exactly like ours. `import_external.py` lays them out as
an outputs tree, and `sdrf-bench score` does the rest.

| SDRF | PXD005354 | PXD013923 | PXD015744 | PXD019515 | PXD037221 | PXD058436 |
|---|---|---|---|---|---|---|
| Dai, skills session (network + paper) | 82.7 | 81.1 | 88.2 | 93.3 | | |
| human curator time (Dai) | 45 min | 46 min | 35 min | 20 min | | |
| Dai's skills session time | 10.5 min | 3.7 min | 3.1 min | 4.3 min | | |
| Jonas, with skills | | | | | 84.8 | 98.5\* |
| Jonas, without skills | | | | | 84.5 | 92.1\* |

\* The curated PXD058436 reference in sdrf-annotated-datasets was contributed by Jonas
(2026-07-10), and his with-skills file is nearly the same text. Scoring his SDRFs against it is
circular, so the runs are flagged `reference_same_author`, shown in the per-dataset figure, and left
out of the headline slide.

Our six configurations on these six datasets (offline, no paper, one replicate) are in
`results-ext/`. Once the run finishes, they are combined with the collaborators' scores:

```bash
uv run python import_external.py
uv run sdrf-bench score --data data-ext --outputs outputs-external --out results-external/runs.jsonl --no-judge
uv run sdrf-bench report --results results-ext/runs.jsonl results-external/runs.jsonl --deterministic \
    --out results-ext-all --data data-ext
```

**Not comparable, by design:** the collaborators ran their own sessions with network access and
the paper. Ours are offline, from the PRIDE record and file list only. For example, PXD037221 is
iProX-hosted and its record carries no protocol text, so without the paper a model cannot tell
that it is TMT.

## Rubric changes in this round

- **Reference-fault-neutral validity.** A validator error class that the curated reference fails
  too is not counted against a run. The classes are cached per dataset as
  `truth/<acc>.validation.json`, and each run records `reference_shared_errors`. The motivating case
  is the SILAC references: they repeat (source name, assay name) across channels, and parse_sdrf
  rejects every file that follows the convention.
- **`report --deterministic`** ranks on the deterministic score alone. Use it whenever judged and
  unjudged runs are mixed: the v2 raw arms were judged, v4 and the collaborators were not, and
  mixing the two would move a configuration by up to 6 points.
- **`report --manuscript on|off`** keeps one condition only.

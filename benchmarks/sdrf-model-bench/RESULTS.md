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

### Our six configurations on their datasets

Offline, no paper, one replicate. Figures in `results-ext-all/`.

**Dai's four datasets** (`slide_dai.png`):

| SDRF | score | cost/SDRF | minutes |
|---|---|---|---|
| Dai, skills session (network + paper) | **86** | n/a | 5 (human curator: 36) |
| Opus 5 + skills | **86** | $3.38 | 9 |
| Sonnet 5 + skills | 81 | $1.95 | 11 |
| Opus 5, prompt only | 78 | $6.64 | 22 |
| Sonnet 5, prompt only | 77 | $2.81 | 18 |
| Haiku 4.5 + skills | 76 | $0.31 | 4 |
| Haiku 4.5, prompt only | 61 | $0.83 | 12 (1 run over context) |

- **Offline Opus + skills matches Dai's own session.** It had no paper and no network; Dai had
  both. Each model scores higher with skills than with the prompt alone: +8 (Opus), +4 (Sonnet),
  +15 (Haiku).
- **The skills are also cheaper and faster than the prompt alone on large files.** The prompt-only
  arm has to write every row itself: PXD005354 has 1,560 rows. The skills arm writes two small
  tables and `build` expands them. That is half the cost for Opus, and 22 minutes down to 9.
- **Every configuration beats the human curator's time** (`backup_9_collaborators_time.png`):
  3–22 minutes against 20–46.

**Jonas's PXD037221** (`slide_jonas.png`): Jonas's two SDRFs score 85, and every offline
configuration scores 20. The dataset is hosted on iProX, and its record carries no protocol text.
Without the paper nothing reveals that the design is TMT 10-plex, so no row aligns with the
reference and only validity scores. This shows what the offline setup cannot recover; it says
nothing about the skills. PXD058436 is circular (above), so it appears only in the per-dataset
figure.

**Missing run:** Opus 5 prompt-only on PXD058436. Its run hung during a continuation call and was
stopped after about 45 minutes with no output, so it is not scored. That dataset is excluded from
the slides anyway.

Reproduce:

```bash
uv run python import_external.py
uv run sdrf-bench score --data data-ext --outputs outputs-external --out results-external/runs.jsonl --no-judge
uv run sdrf-bench report --results results-ext/runs.jsonl results-external/runs.jsonl --deterministic \
    --collaborators-only --out results-ext-all --data data-ext
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
- **Context overflow is a result, not a crash.** "Prompt is too long" from the CLI is recorded
  as a finished run flagged `context_limited`, scored on what the model wrote, and not retried.
- **`report --collaborators-only`** renders only the per-collaborator figures. A pooled slide
  would average configurations over different sets of datasets.

## Independent review of the collaborators' SDRFs

The session's review gate ran a fresh adversarial reviewer on each of the eight files, with none of
the scores or references. Five passed. Three failed, and the findings go back to their authors:

- **Dai PXD013923:** the 54 `*_P0x` files are labelled phospho-enriched, but they are the
  non-enriched whole-proteome aliquots; no channel is annotated as the DMSO control.
- **Dai PXD019515:** HeLa rows lack disease and sex (Cellosaurus CVCL_0030).
- **Jonas PXD037221 with skills:** the N-terminal TMT modification is missing from the search
  settings.

The files are scored as delivered, and the benchmark does not edit them.

# SDRF model benchmark — design

Date: 2026-09-18 · Status: approved (brainstorming), implementation in progress

## Goal

Measure how well different LLMs produce an SDRF for a proteomics dataset, and what it
costs in tokens, money and time. The results produce one workshop slide, and the whole
benchmark can be handed to a third party who has models we cannot access.

## Questions answered

1. Which model produces the best SDRF?
2. How much do the SDRF skills add on top of the same model? (skills arm vs raw arm)
3. How much does the manuscript help? (ablation: the same dataset with and without it)
4. Does poor PRIDE metadata hurt, and does the manuscript make up for it? (covariate)
5. Do TMT, LFQ and DIA differ in difficulty?

## Matrix

- **Datasets:** 12, with 4 each of TMT, LFQ and DIA. Within each type, 2 have rich PRIDE metadata and 2 poor.
- **Manuscript:** each dataset runs twice, `ms-on` (Methods and sample figure legends in context) and `ms-off` (withheld).
- **Model-arms:** 9 in total.
  - Claude opus-5, sonnet-5 and haiku-4.5, each in both the `skills` and `raw` arms.
  - Ollama gemma4:12b, gemma2:9b and qwen2.5:3b, in the `raw` arm only.
  - One collaborator slot, left empty.
- **Total:** 12 × 2 × 9 = **216 runs**, one replicate each.
- **Optional variance probe:** 2 datasets × 3 replicates, 72 extra runs.

## Arms

- **raw:** a standalone loop of draft → `parse_sdrf validate` → repair, with at most 2
  repairs. Every raw model gets the same prompt, the same evidence text and the same
  validator feedback.
- **skills:** `claude -p --output-format json` in a temporary workspace holding the
  evidence files, with the sdrf-skills plugin loaded. Allowed tools: Read, Write, Edit,
  Glob, Grep, Skill and `Bash(parse_sdrf:*)`. No MCP servers, no WebFetch or WebSearch.
  The agent sees the same frozen evidence as the raw arm and nothing live.
- **Ontology access is the same in both arms:** the offline ontology validation inside
  `parse_sdrf`. A snapshot of candidate terms is deliberately *not* provided, because a
  candidate list built from the truth terms gives the answer away.

## Evidence (frozen once, never re-fetched)

Stored per dataset in `data/evidence/<PXD>/`:

- `pride.json`: PRIDE v3 project record (title, description, protocols, organisms,
  organism parts, diseases, instruments, PTMs, quantification, keywords).
- `files.json`: raw file names only, from the PRIDE file list.
- `manuscript.txt`: the EuropePMC full-text Methods section plus any figure or table
  legends that mention samples, truncated so the whole prompt fits the evidence budget.
- `meta.json`: quantification type, PRIDE quality score and tier, PMCID, licence, and
  the reason the dataset was selected.

**Evidence budget:** at most 24,000 tokens (estimated as characters ÷ 4) for the
evidence, applied the same way to every model. Ollama's `num_ctx` is set explicitly on
every call; its default window silently truncates. If a model's context window is
smaller than the prompt, the run is flagged `context_limited` and not scored silently.

## Dataset selection

Candidates come from `sdrf-annotated-datasets/datasets/PXD*/PXD*.sdrf.tsv`. The filters,
applied in order:

1. The truth SDRF is the canonical file, has 60 rows or fewer, and has at least one data file.
2. The truth file was not produced with sdrf-skills or the annotator: no commit touching
   it mentions `sdrf-skills`, `annotator`, `agentic` or `Co-Authored-By: Claude`.
3. The dataset has no deposited `*sdrf*` file in PRIDE. A deposited SDRF would be the answer.
4. The manuscript is open access in EuropePMC under a `cc*` licence, which is required
   before its text can be redistributed.
5. Quantification type comes from the truth SDRF: any TMT label means TMT; label-free
   plus DIA in `comment[proteomics data acquisition method]` means DIA; any other
   label-free dataset is LFQ. SILAC and iTRAQ are excluded.
6. PRIDE quality score is the fraction of these fields that are filled in: organisms,
   organism parts, diseases, instruments, PTMs, quantification methods, sample protocol
   of 200 characters or more, data protocol of 200 characters or more. Within each
   quantification type, the top third is `rich` and the bottom third is `poor`.
7. Diversity: at least 3 non-human organisms across the 12, and no more than 2
   cell-line-only studies.

Selection uses a fixed seed, and the manifest is committed at `data/manifest.tsv`.

## Scoring

**Row alignment:** rows are matched on `comment[data file]` normalised (basename,
lowercase, no extension). For TMT, the key is (file, `comment[label]`).

**Deterministic score (80% of the headline):**

| component | weight | definition |
|---|---|---|
| validity | 0.20 | `parse_sdrf validate`: 1.0 if clean, −0.1 per distinct error type, floor 0; 0 if the output is missing or unparseable |
| completeness | 0.15 | share of the truth file's non-infrastructure columns that are present, counting repeated columns by multiplicity; aligned rows ÷ truth rows is a multiplier |
| accuracy | 0.50 | mean cell agreement over the key fields, on aligned rows |
| specificity | 0.15 | 1 − share of key-field cells where the truth has a real value and the output says `not available` or `not applicable` |

The key fields are organism, organism part, disease, cell type, label, instrument,
cleavage agent, modification parameters, precursor and fragment mass tolerance,
fraction identifier and technical replicate.

Cell agreement:
- same accession = 1.0
- same label but no accession, or a different accession with the same label = 0.5
- wrong = 0
- modifications are compared as sets of (NT, MT, PP, TA) with Jaccard similarity
- tolerances are compared numerically after unit conversion (ppm and Da must match units)
- numbers and identifiers must match exactly

(The parent/child ontology credit in the approved design needs live OLS. It is replaced
by the label-match credit so scoring stays offline and deterministic.)

**Judge score (20% of the headline):** a single call to sonnet-5 at temperature 0. The
judge gets the truth SDRF, the output SDRF with the model's name removed, and a rubric,
and returns JSON with factor fidelity, design fidelity and free-text adequacy, each 0–10.
The judge is optional. The deterministic and judge scores are always stored separately,
and the headline can fall back to deterministic only.

**Flags:**
- `contamination_suspect`: ms-off, poor PRIDE tier, and a deterministic score of 80 or more.
- `context_limited`: see the evidence section.
- `failed`: no parseable SDRF was produced.

## Cost accounting

Every run records input, output, cache-read and cache-write tokens, wall-clock time and
the model's context window. API cost is computed from the pinned `pricing.yaml`; for
the skills arm, the CLI's `total_cost_usd` is used. Ollama runs report token counts and
minutes, not dollars.

## Hand-off pack

`benchmarks/sdrf-model-bench/` is self-contained. It does not import anything from
`sdrf_agentic_annotator`, so the whole directory plus `data/` can be shared as a tarball.

- `models.yaml`: the roster. Providers are `anthropic`, `ollama`, `openai` (compatible),
  `claude-code` (skills arm) and `custom` (`module:function` returning text, or text
  plus a usage dict).
- `run`, `score`, `report`: command-line entry points, with resume.
- `SUBMISSION.md`: a door for anyone who doesn't use our runner. They write
  `outputs/<model_id>/<PXD>__<ms-on|ms-off>/sdrf.tsv` plus `usage.json` and we score them
  centrally.

## Report

Written to `results/`: `runs.jsonl`, `summary.tsv` and `slide.svg`/`slide.png` (16:9).

- **Main panel:** a dumbbell chart per model from raw score to skills score, with
  tokens and cost or minutes for each SDRF.
- **Side panels:** score by quantification type, and the manuscript effect.
- **Backup plots:** PRIDE tier, score components, flags, and how well the judge agrees
  with the deterministic score.

## Out of scope

- Live PRIDE, EuropePMC or OLS during runs.
- Parent/child ontology reasoning.
- Techsdrf raw-file analysis.
- Datasets without a manuscript (these are covered by the ablation instead).

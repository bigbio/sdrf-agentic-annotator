# Fast annotation: per-step models and an evidence sheet

Date: 2026-11-24. Status: approved in conversation (options 1 + 2), test on 10 datasets first.

## Why

The goal is to annotate 2,000 PRIDE projects in 48 hours, about 42 per hour. Campaign 6 (10 jobs,
`deepseek-v4-flash` for every step, 100 agents at once) produced about 6 per hour.

Measured on Campaign 6 (job s01, gateway log and execution trace):

| step | turns per dataset (median) | time between turns (median) | request size (median) | wall time (median) |
|---|---|---|---|---|
| annotate | 76 | 272 s | 233 kB | 7.7 h |
| review | 58 | 285 s | 181 kB | 4.8 h |

On 2026-11-24, with Campaign 6b's 100 agents running, a 47k-token request took 208-291 s on
`deepseek-v4-flash` (a 20-token request timed out at 300 s). The same request took 2.3 s on
`gemini-3.8-flash-eu`, 3.9-6.5 s on `openai/DeepSeek-V4-Flash-0731` and 8-30 s on `zai-org/GLM-5.3-Flash`.
Almost all of a turn is waiting in the queue of one saturated model.

So there are two levers, and both are needed:

1. **Per-turn latency**: send each step to a model that is not saturated.
2. **Turns and request size**: give the annotate agent the facts it now spends most of its turns finding.

## Goals

- Annotate and review can use different models, chosen by parameter.
- A plain (non-model) step writes an evidence sheet that the annotate agent starts from.
- Measured on 10 datasets: wall time, requests and request size per step, review verdict, and
  agreement with the Campaign 6 SDRFs of the same datasets.

## Non-goals

- No change to the review skill or the revise loop (the reviewer stays independent and does not
  see the sheet, so an error in the sheet cannot pass unnoticed through both).
- No change to SDRF_STAMP or to what counts as a final SDRF (review verdict PASS).
- No new model for review until it is shown not to be worse than the current one
  (decision of 2026-10-29).

## Anti-goals

- Faster but wrong: a sheet value that the agent copies without evidence. Every sheet value carries
  its source sentence or file, and values found by a pattern are marked to be confirmed, as the
  prefill already does.
- A sheet so large that it becomes another manuscript (cap: about 12 kB of text).

## Approaches considered

1. Per-step models only (configuration). Fixes latency, leaves 76 turns of 230 kB.
2. Per-step models plus an evidence sheet built with plain NLP (chosen). Fixes latency and cuts
   turns and request size; about a day of work.
3. Rewrite the agent into a few structured extraction calls. Largest gain, too large for the deadline.

## Design

### Part 1: a model per step

- New parameters `annotate_model` (SDRF_ANNOTATE, SDRF_REVISE) and `review_model` (SDRF_REVIEW);
  both default to `model`, so existing runs do not change.
- Set through a `withName` selector in the `agent` scope of `conf/base.config` (Nextflow 26.10
  agent scope accepts a per-step `model`). If the selector does not work for agents, fall back to the
  `model` directive in each agent module, read from the parameter.
- `scripts/run_annotate.sh` writes all models used into `models_<name>.json` (one pi provider,
  several model ids) and passes the two parameters.
- Test settings: annotate and revise on `gemini-3.8-flash-eu`; review on
  `openai/DeepSeek-V4-Flash-0731` (fast, and the same model family as the Campaign 6 reviewer, so
  the review bar does not drop; its 18 requests/min cap is enough for 10 datasets). The review model
  for the 2,000 run is chosen after the test, from measured latency and rate limits.

### Part 2: the evidence sheet

A new script `bin/sdrf_sheet.py`, run inside SDRF_PREFILL after `sdrf_prefill.py`, reading
`evidence/manuscript.txt`, `evidence/pride.json`, `evidence/files.json` and `<pxd>.prefill.json`.
It writes `<pxd>.sheet.md` (for the agent) and `<pxd>.sheet.json` (for tests and measurement).
No model is called. Sections:

1. **Methods excerpt**: the manuscript split at headings (Methods, Materials and methods,
   Experimental procedures, Sample preparation, LC-MS/MS, Mass spectrometry, Data analysis, Database
   search); paragraphs kept in that order, cut at about 6 kB, sentences with ontology hits or
   search settings kept first if it has to be cut.
2. **Term matches**: whole-word matches of ontology labels in the methods excerpt, title and the
   PRIDE protocols, against the sdrf-pipelines ontology caches: cell lines (CLO, BTO cell lines),
   tissues (UBERON, BTO), cell types (CL), diseases (MONDO, EFO), modifications (UNIMOD),
   instruments (PSI-MS), labels. Each hit: label, accession, count, first sentence. Labels shorter
   than 4 characters only case-sensitive; a stop list of generic labels (cell, protein, control,
   sample, ...). Organisms come from the PRIDE record (prefill), not from text matching.
3. **Search settings by pattern**: precursor and fragment tolerance (ppm, Da, mmu), missed
   cleavages, fixed and variable modifications phrases, number of fractions, DDA/DIA, gradient
   length; each with its sentence, marked `confirm`.
4. **Design from file names**: raw file names split on `_ - .`; tokens shared by all files dropped;
   positions that vary listed with their values (candidate conditions); tokens that look like
   fractions (`F01`, `fr3`), replicates (`R1`, `rep2`, `BR`, `TR`) or channels named.
5. **Similar SDRFs**: up to two SDRFs from the sdrf-annotated-datasets corpus that share organism,
   instrument and label with this dataset and, where possible, a matched cell line, tissue or disease;
   their header and first three rows, as an example of the column set, not of the values.
   The corpus index (`assets/corpus_index.tsv`: accession, organism, instrument, label, cell line,
   organism part, disease, columns) is built once by `bin/build_corpus_index.py` from a checkout of
   the corpus and passed by parameter `corpus_index`.

The ontology caches are passed as a directory parameter `ontology_dir` (the parquet files of
sdrf-pipelines `data/ontologies`); the script reads them with pandas/pyarrow if the runner image has
them, otherwise the sheet leaves out section 2 and says so.

### Prompt change

SDRF_ANNOTATE gets the sheet next to the prefill: read `<pxd>.sheet.md` first; it holds the methods
of the manuscript and the candidate values with their sentences; open `evidence/manuscript.txt`
only for a fact the sheet does not hold; confirm every `confirm` value before using it; record in
the manifest the sentence that supports each value. Parameter `sheet` (default true) turns it off.

## Test on 10 datasets

Ten datasets from Campaign 6 with a review-PASS final, chosen to cover cell line, tissue, TMT or
SILAC, DIA, and more than 20 raw files. Two new runs, each its own job, proxy and results folder
in the Codon iteration of Campaign 6:

- **B**: per-step models, no sheet.
- **C**: per-step models and the sheet.
- **A** (baseline): the Campaign 6 results of the same datasets (not re-run; their timings were
  taken under heavy load, which is stated in the report).

Measured per dataset and step: wall time (trace), number of requests and request size (gateway
log), review verdict, and agreement with the Campaign 6 final SDRF on organism, organism part,
cell line or cell type, disease, instrument, label, cleavage agent, modifications, precursor and
fragment tolerance, dissociation method, factor columns, and the data file to sample mapping.
Every disagreement is read by hand before it is counted against either side.

Success: C finishes annotate plus review in a median of 1 hour or less per dataset at 10 at once,
agrees with A on at least 90% of the compared fields (after reading the disagreements), and its
review PASS rate is not lower than A's.

## Left to the builder

- Exact heading patterns, stop list and cut rules of the sheet; unit tests with a few real
  manuscripts from the evidence folders of Campaign 6.
- Whether the runner image has pandas and pyarrow; if not, read the parquet files in the prefill
  container or convert the caches to TSV once.
- The `withName` selector syntax in the agent scope, checked with a stub run.

## Open after the test

- The review model for the 2,000 run and the sustained rate limits of the chosen models.
- Whether the reviewer should also get a sheet (it would cut its 58 turns; it also weakens its
  independence).

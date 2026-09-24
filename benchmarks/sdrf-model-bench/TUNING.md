# Tuning the skills against the benchmark

The benchmark can be used as an optimization loop for `sdrf-skills`: change the skill, re-run a
subset, see which quality component moved. `tune.sh` is one iteration of that loop.

```bash
./tune.sh tune baseline                      # 8 datasets, the installed plugin
./tune.sh tune tmt-label-rule ../my-plugin   # same 8, an edited plugin
./tune.sh eval tmt-label-rule ../my-plugin   # the held-out 4 -- once, at the end
```

## What to optimize

**Optimize validity and completeness. Treat accuracy as a regression guard, not a target.**

Validity is objectively checkable: the file either satisfies the templates or it does not.
Accuracy measures agreement with one curator's choices, and the benchmark's own LLM judge
disagrees with it systematically — the skills arm loses accuracy (0.80 → 0.73 on Opus/Sonnet)
while winning the judge by 10–16 points. Tuning against accuracy would teach the skills to imitate
the reference files' arbitrary decisions. Watch it, but do not chase it.

## The split

`data/split.tsv` holds 8 tuning datasets and 4 held out, stratified by quantification type and by
repository metadata quality. **Do not look at the eval four while iterating** — with only 12
datasets, a few iterations of feedback are enough to overfit skill text to specific answer keys.

The two halves are not equally hard (see the baseline below: the tuning half starts at 4.07
errors/run, the held-out half at 1.00), so compare eval-after against eval-before, never eval
against tune.

## Baseline — `haiku-4.5-skills`

Taken from the completed 144-run benchmark, so it costs nothing to reproduce. Haiku is the
deliberate tuning model: it fails loudly where larger models paper over gaps, and making a cheap
model competent is the point of the skills.

| split | qtype | n | validity | completeness | accuracy | errors/run | clean runs |
|---|---|---:|---:|---:|---:|---:|---|
| tune | ALL | 16 | 0.66 | 0.63 | 0.67 | 4.07 | 3/15 |
| tune | DIA | 6 | 0.67 | 0.88 | 0.86 | 5.17 | 0/6 |
| tune | LFQ | 6 | 0.60 | 0.59 | 0.55 | 2.80 | 2/5 |
| tune | TMT | 4 | 0.72 | 0.32 | 0.57 | 4.00 | 1/4 |
| eval | ALL | 8 | 0.79 | 0.59 | 0.63 | 1.00 | 3/7 |
| eval | DIA | 2 | 0.90 | 0.93 | 0.79 | 1.00 | 0/2 |
| eval | LFQ | 2 | 0.80 | 0.61 | 0.71 | 2.00 | 1/2 |
| eval | TMT | 4 | 0.72 | 0.41 | 0.50 | 0.33 | 2/3 |

Known defects to fix first are catalogued in bigbio/sdrf-skills#85.

## Cost

`tune.sh` never calls the judge: the judge needs API quota, and what a skills change should move is
deterministic. One tuning iteration is 16 runs (8 datasets × with/without manuscript); scoring is
local apart from ontology lookups, which use the OLS cache.

## Keeping the loop honest

Truth files must stay human-curated. The selection step (`select.py:automated_truth`) rejects
machine-generated reference SDRFs — three datasets were replaced for this reason. In a tuning loop
that contamination would silently reward the skills for reproducing their own earlier output, so
re-run that check whenever the frozen pack grows.

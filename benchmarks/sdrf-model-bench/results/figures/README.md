# Figures: sdrf-skills, models, cost and experimental design

Eight slides, one style (16:9, PNG at 300 dpi + SVG). All are generated from the scored runs by
`uv run sdrf-bench figures`.

Colours are the same on every slide:
- **vermilion** — sdrf-skills
- **slate** — the same model, prompt only
- **amber** — a collaborator's own session
- **black** — the human curator

**Setup behind every number**
- **Models:** Claude Opus 5, Sonnet 5 and Haiku 4.5.
- **Evidence:** each model annotated from the frozen PRIDE record and the raw-file list only:
  offline, no paper, one run per dataset.
- **Score (0–100):** agreement with the curated SDRF in
  [sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets). It is made of
  validity 20, completeness 15, accuracy 50 and specificity 15. Style differences and faults in
  the reference are not charged to the run.
- **Datasets:** 15 benchmark datasets (6 LFQ, 5 DIA, 4 TMT), plus 6 from Chengxin Dai's and Jonas
  Scheid's benchmarks.

---

## 1. Impact of sdrf-skills per model

![](fig1_skills_impact.png)

**sdrf-skills lifts every model, most of all the smallest.**

| model | 15 benchmark datasets | Dai's 4 datasets |
|---|---|---|
| Haiku 4.5 | +7 (69 → 77) | +16 (61 → 76) |
| Sonnet 5 | +3 (76 → 79) | +4 (77 → 81) |
| Opus 5 | +1 (79 → 80) | +8 (78 → 86) |

On Dai's datasets, offline Opus with skills matches Dai's own skills session (86), even though
that session had network access and the paper.

*Speaker note:* the gain is biggest where the model knows least. The skills carry the SDRF
knowledge, so a small model no longer has to recall it.

## 2. What it costs

![](fig2_cost_vs_quality.png)

**Skills buy quality: free for Haiku, a premium for Opus and Sonnet.**

| model | score | cost per SDRF |
|---|---|---|
| Haiku 4.5, prompt only | 69 | $0.37 |
| **Haiku 4.5 + skills** | **77** | **$0.36** |
| Sonnet 5, prompt only | 76 | $0.57 |
| Sonnet 5 + skills | 79 | $1.74 |
| Opus 5, prompt only | 79 | $1.11 |
| Opus 5 + skills | 80 | $2.65 |

**Haiku 4.5 + skills is the value point:** Sonnet-level quality at a sixth of Opus's price.

![](fig3_time_and_cost_vs_human.png)

**From 36 minutes of curation to a few minutes and a few dollars.** On Chengxin Dai's four
datasets (12 to 1,560 rows):

| who | minutes per SDRF | cost per SDRF |
|---|---|---|
| **Human curator** | **36** (20–46) | — |
| Dai's own sdrf-skills session | 5 | — |
| Haiku 4.5 + skills | 4 | $0.31 |
| Opus 5 + skills | 9 | $3.38 |

That makes Haiku with skills about 10× faster than a curator, for about 30 cents.

*Speaker note:* our minutes are wall time with three runs in parallel on one laptop.

## 3. Quality of the models

![](fig4_quality_breakdown.png)

**Where the points are won and lost.**
- **Validity is solved:** every configuration earns the full 20 points.
- **The differences are in *correct values* (accuracy):** about 60% of scored cells match the
  curators and about a quarter are wrong, for every model with skills.
- **Prompt-only Haiku is the outlier:** 48% correct, 35% wrong.
- **The skills arm more often leaves a field blank than guesses it.** That costs coverage but not
  correctness.

## 4. sdrf-skills: what changed, and what to optimise next

![](fig5_skills_before_after.png)

**The redesign: cheaper, faster, and Haiku no longer breaks.** Same 15 datasets, sdrf-skills
before (v2) and after (bigbio/sdrf-skills #91–#98):

| | Opus 5 | Sonnet 5 | Haiku 4.5 |
|---|---|---|---|
| cost per SDRF | $4.90 → $2.65 | $2.88 → $1.74 | $0.53 → $0.36 |
| minutes | 13 → 8 | 14 → 10 | 8 → 5 |
| score | 82 → 80 | 81 → 79 | **59 → 77** |
| files that validate | 100% → 99% | 100% → 100% | **81% → 100%** |

What produced it:

| change | what it does |
|---|---|
| **`contract`** | one call returns the exact column set, value forms and permissions of a template union, so the model stops reading templates |
| **`build`** | the model writes two small tables (samples and technical settings); `build` expands them into the SDRF deterministically, with row, fraction and channel logic, and refuses to guess a channel map |
| **One entry point** | `sdrf-annotate` with independent review always on; 10 skills consolidated into 4 |
| **Progressive disclosure** | a short core plus 17 reference files read on demand, so a SKILL.md no longer sits in every turn |
| **Tools callable in a locked-down sandbox** | a `sdrf-tools` console script; no plugin-root variable is needed |

![](fig6_where_to_optimise.png)

**Where sdrf-skills still loses points, and what fixes it.** Accuracy per field (skills runs):

| priority | idea | target | status |
|---|---|---|---|
| 1 | **Read search settings from the deposited search files, never from the paper.** Modifications, tolerances and cleavage agent are among the weakest fields (47–67%) yet are recorded verbatim in MaxQuant `mqpar.xml`/`summary.txt`, FragPipe `fragger.params`, DIA-NN logs and PD `.msf`. | `sdrf-tools search-params` | done: sdrf-skills #99. Next: fetch these small files into the benchmark evidence and measure the gain |
| 2 | **Ground sample metadata before writing it.** Cell type (35%), disease (46%) and organism part (50%) are the weakest fields, and the skills arm is *below* prompt-only on disease and organism part. Look up cell lines in Cellosaurus (disease, sex, age, cell type come with the record) and take tissue and disease from the paper's sample table. Prefer `not available` over a plausible guess. | sample metadata | next |
| 3 | **Classify the design first, then load its playbook.** TMT, SILAC, DIA, single-cell and immunopeptidomics each need different rows (channels, labels, windows, isolation). One short routing step would load only the matching reference. | design | idea |
| 4 | **Read remote `.msf`/`.pdResult` by byte range.** Proteome Discoverer results are multi-GB SQLite files; the search settings sit in one table. | `search-params` remote mode | idea |
| 5 | **Cache ontology lookups across runs.** A shared, offline cache of OLS terms would cut the most frequent tool calls and make runs reproducible. | cost | idea |
| 6 | **Check the reference before trusting a disagreement.** The benchmark found curated SDRFs that collapse TMT channels, use malformed accessions, pair `HCD` with the wrong accession (MS:1002481 instead of MS:1000422), or fail validation themselves. Feed these back to sdrf-annotated-datasets. | references | ongoing |

## 5. Experimental designs: difficulty and cost

![](fig7_design_difficulty.png)

**Some experimental designs are much harder to annotate.**
- **Easy:**
  - Label-free and DIA land around 77–83 with skills.
  - Single-cell and immunopeptidomics score highest (85–94), but these are one dataset each,
    both with clear file naming.
- **Hard, TMT (64–65):**
  - A TMT SDRF has one row per channel, so the channel-to-sample map must be recovered.
  - One of the five TMT datasets (PXD037221) has no protocol text in its record, and no offline
    run recognises it as TMT. Without it, TMT is 75–77.
- **Hard, SILAC:** prompt-only Haiku collapses to 18; with skills it reaches 65.
- **Cost:** prompt-only cost explodes on SILAC ($6.56) and immunopeptidomics ($9.15), because
  there the model writes hundreds of rows. With skills the cost stays near $1.4–2.8 for every design.

![](fig8_cost_vs_size.png)

**sdrf-skills cost stays flat as the SDRF grows.**
- **Prompt-only:** the model writes every row, so cost grows about 36× for 100× more rows.
- **sdrf-skills:** the model writes two small tables and `build` expands them, so cost grows about
  1.5× for 100× more rows.
- **Crossover:** at about 200 rows, sdrf-skills becomes the cheaper option. Large studies (fractionated,
  multiplexed, many samples) are where the skills pay for themselves.

---

**Regenerate:**

```bash
uv run sdrf-bench figures   # reads results/main, results/collaborators, results/history
```

**Caveats**
- **Agreement, not truth.** Scores measure agreement with one curated SDRF, not objective truth.
- **One replicate.** Differences of 1–2 points are within run-to-run spread.
- **Small design groups.** Design categories with one dataset are indicative only.
- **Timing and cost sources.** Times for the human curator and for Dai's session come from Dai's
  own measurements; costs are Claude Code's `total_cost_usd`.

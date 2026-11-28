# Fast annotation Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the wall time per dataset by giving each agent step its own model and by giving the annotate agent an evidence sheet built without a model, then measure it on 10 datasets.

**Architecture:** Two parameters route SDRF_ANNOTATE/SDRF_REVISE and SDRF_REVIEW to different models through `withName` selectors in the `agent` scope. A new plain script `bin/sdrf_sheet.py`, run inside SDRF_PREFILL, writes `<pxd>.sheet.md` and `<pxd>.sheet.json` from the evidence that `sdrf-tools fetch` already downloads, ontology label caches and a corpus index; the annotate prompt tells the agent to start from it.

**Tech Stack:** Nextflow 26.10.3 agents (pi runner), Python 3 (stdlib; pandas/pyarrow only to read parquet caches), pytest.

**Spec:** `docs/design/2026-11-24-fast-annotation-design.md`

## Global Constraints

- Defaults leave existing runs unchanged: `annotate_model` and `review_model` default to `model`; `sheet` defaults to `true` but the sheet step must never fail the prefill task (any exception: write a sheet that says which section failed).
- No model is called by `bin/sdrf_sheet.py` or `bin/build_corpus_index.py`.
- Sheet text (`<pxd>.sheet.md`) at most 12,000 characters; methods excerpt at most 6,000 characters.
- Every sheet value carries its source (sentence, file name, or corpus accession); pattern-found values are marked `confirm`.
- Organisms come from the prefill (PRIDE record), never from text matching.
- The reviewer does not get the sheet.
- Python tests follow `tests/python/test_sdrf_prefill.py`: `PYTHONPATH=<sdrf-skills checkout>:bin python -m pytest tests/python`.

## Review Focus

- A manuscript with no recognisable Methods heading (PRIDE-only datasets, `manuscript.txt` empty or missing): sheet still written from PRIDE protocols, excerpt section says "no manuscript methods found". Test in Task 2.
- Ontology labels that are common words or short codes (`PC-3` vs `PC`, `CA`, `ALL`, `serum`): no hit for labels under 4 characters unless the exact case matches; generic stop list applied. Test in Task 3.
- Hundreds of raw files with a long shared prefix and a timestamp token: design section lists at most 8 varying positions and at most 12 values each, timestamps (digits of length >= 6) dropped. Test in Task 2.
- No corpus match with the same organism, instrument and label: section says so; never pads with unrelated SDRFs. Test in Task 4.
- Ontology cache directory missing or pandas absent in the image: sheet written without term matches and says why. Test in Task 3.

---

### Task 1: A model per agent step

**Files:**
- Modify: `nextflow.config` (params `annotate_model = null`, `review_model = null`, `sheet = true`, `ontology_dir = null`, `corpus_index = null`)
- Modify: `nextflow_schema.json` (the five params, in the group that holds `model` / `prefill`)
- Modify: `conf/base.config` (agent scope selectors)
- Modify: `docs/usage.md` (one paragraph: per-step models)

**Interfaces:**
- Produces: `params.annotate_model`, `params.review_model`, `params.sheet`, `params.ontology_dir`, `params.corpus_index` used by Tasks 5 and 6.

- [ ] **Step 1:** In the `agent` scope add
  `withName: 'SDRF_ANNOTATE|SDRF_REVISE|SDRF_REFINE' { model = params.annotate_model ?: params.model }` and
  `withName: 'SDRF_REVIEW' { model = params.review_model ?: params.model }`.
- [ ] **Step 2: Verify the selector resolves.** Run `nextflow config -flat . --annotate_model a/x --review_model b/y | grep -i model` with NXF_VER=26.10.3 and check both selectors print with the given values. Then run `nf-test test tests/default.nf.test` (stub) and check it passes unchanged. If `nextflow config` rejects `withName` in the agent scope, put `model params.annotate_model ?: params.model` (resp. review) as a directive in each agent module instead and repeat the check.
- [ ] **Step 3:** `nf-core pipelines lint --dir .` passes the schema check for the new params.
- [ ] **Step 4: Commit** `feat: choose the model of the annotate and review agents separately`.

### Task 2: Sheet core: methods excerpt, search settings, file-name design

**Files:**
- Create: `bin/sdrf_sheet.py`
- Test: `tests/python/test_sdrf_sheet.py`

**Interfaces:**
- Produces:
  - `methods_excerpt(text: str, limit: int = 6000) -> dict` → `{"found": bool, "headings": [str], "text": str}`
  - `search_settings(text: str) -> list[dict]` → items `{"field": str, "value": str, "sentence": str, "basis": "text", "confirm": True}`; fields: `precursor_tolerance`, `fragment_tolerance`, `missed_cleavages`, `fractions`, `acquisition`, `gradient_minutes`
  - `filename_design(files: list[str], max_positions: int = 8, max_values: int = 12) -> dict` → `{"positions": [{"index": int, "values": [str], "kind": "condition"|"fraction"|"replicate"}], "dropped": [str]}`

- [ ] **Step 1: Write the failing tests**
  - `test_methods_excerpt_keeps_methods_only`: a text with "Introduction ... Materials and Methods ... Cell culture ... LC-MS/MS ... Results ..." → `found` True, text contains the LC-MS/MS paragraph, not the Results paragraph.
  - `test_methods_excerpt_no_heading`: "" and a text with no heading → `found` False, `text` "".
  - `test_methods_excerpt_cut`: 20 kB of methods → `len(text) <= 6000`, sentences with "ppm" or "trypsin" kept first.
  - `test_search_settings`: "Precursor mass tolerance was set to 10 ppm and fragment tolerance to 0.02 Da, allowing up to two missed cleavages." → precursor `10 ppm`, fragment `0.02 Da`, missed cleavages `2`, each with the sentence and `confirm` True. Also "20 mmu" fragment and "fractionated into 12 fractions" → fractions `12`.
  - `test_filename_design`: `["2019_HeLa_ctrl_R1_F01.raw", "2019_HeLa_ctrl_R2_F02.raw", "2019_HeLa_drug_R1_F01.raw", "2019_HeLa_drug_R2_F02.raw"]` → positions: ctrl/drug as condition, R1/R2 replicate, F01/F02 fraction; "2019" and "HeLa" dropped as shared.
  - `test_filename_design_timestamps_and_caps`: 300 names with a 14-digit timestamp token → timestamp dropped, at most 8 positions, at most 12 values each.
- [ ] **Step 2:** Run `PYTHONPATH=<sdrf-skills>:bin python -m pytest tests/python/test_sdrf_sheet.py -v` → fails (module missing).
- [ ] **Step 3: Implement the three functions.** Headings matched case-insensitively at line start: `materials? and methods|methods|experimental (procedures|section)|sample preparation|lc-?ms(/ms)?|mass spectrometry|data (analysis|processing)|database search|proteomic analysis`; a section ends at `results|discussion|references|acknowledg|conclusion`. Tolerance regex accepts `±`, `+/-`, `ppm|Da|mmu|Th`; number words one to five for missed cleavages. Tokens split on `[_\-. ]`, extension dropped; fraction `^(f|fr|frac)\d+$`, replicate `^(r|rep|br|tr|bio|tech)\d+$` (case-insensitive).
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5: Commit** `feat: evidence sheet core (methods excerpt, search settings, file-name design)`.

### Task 3: Ontology term matches

**Files:**
- Modify: `bin/sdrf_sheet.py`
- Test: `tests/python/test_sdrf_sheet.py`, fixture `tests/data/ontologies/` (small TSVs `clo.tsv`, `uberon.tsv`, `mondo.tsv`, `unimod.tsv` with columns `accession, label, ontology`)

**Interfaces:**
- Produces:
  - `load_terms(ontology_dir: str | None) -> tuple[dict[str, list[dict]], str | None]` → (`{category: [{"label", "accession"}]}`, reason when unavailable). Reads `<name>.parquet` with pandas, else `<name>.tsv` with csv.
  - `term_matches(text: str, terms: dict) -> dict[str, list[dict]]` → per category items `{"label", "accession", "count", "sentence"}`, sorted by count.
- Categories and sources: `cell_line` (clo; bto labels ending in "cell" or containing "cell line"), `organism_part` (uberon, bto others), `cell_type` (cl), `disease` (mondo, efo disease terms by `EFO:`/`MONDO:` prefix), `modification` (unimod), `instrument` (psi-ms labels under instrument model names; filter: label contains a vendor or model word list `Orbitrap|Exploris|Q Exactive|timsTOF|TripleTOF|Synapt|LTQ|Astral|Eclipse|Lumos|Fusion|ZenoTOF|Xevo`).

- [ ] **Step 1: Write the failing tests**
  - `test_term_matches_whole_word`: "HeLa and PC-3 cells, liver tissue, breast carcinoma, Oxidation" with fixture terms → HeLa, PC-3, liver, breast carcinoma, Oxidation found with accessions and sentence.
  - `test_short_labels_case_sensitive`: label `CA` and `ALL` in terms, text "all samples were ca. 10" → no hit; "patients with ALL" → hit.
  - `test_stop_list`: labels `cell`, `protein`, `control`, `sample` and `serum` in terms, text mentioning all five → `serum` reported as organism part, the other four never reported.
  - `test_load_terms_missing_dir`: `load_terms(None)` and a non-existent path → empty dict and a reason string.
- [ ] **Step 2:** Tests fail.
- [ ] **Step 3: Implement.** Build one compiled alternation per category (labels escaped, longest first, `(?<![\w-])label(?![\w-])`, `re.IGNORECASE` only for labels of 4+ characters); count hits; keep the first sentence (split on `(?<=[.!?])\s+`).
- [ ] **Step 4:** Tests pass. Then time `term_matches` on a 100 kB `manuscript.txt` with the full sdrf-pipelines caches (`~/work/sdrf-workspace/sdrf-pipelines/data/ontologies`): under 20 s; if not, restrict efo/ncit to disease-like labels.
- [ ] **Step 5: Commit** `feat: ontology term matches in the evidence sheet`.

### Task 4: Corpus index and similar SDRFs

**Files:**
- Create: `bin/build_corpus_index.py`
- Modify: `bin/sdrf_sheet.py`
- Test: `tests/python/test_sdrf_sheet.py` (fixture: three tiny SDRFs under `tests/data/corpus/datasets/<acc>/<acc>.sdrf.tsv`)

**Interfaces:**
- Produces:
  - `build_corpus_index.py CORPUS_DIR OUT.tsv`: one row per `datasets/*/*.sdrf.tsv` (sandbox excluded): `accession, path, organism, instrument, label, cell_line, organism_part, disease, columns` (multi-values `|`-joined, NT= names only, lower-cased).
  - `similar_sdrfs(index_path: str | None, facts: dict, corpus_root: str | None, k: int = 2) -> list[dict]` → `{"accession", "shared": [str], "header": [str], "rows": [[str]]}` (header plus first 3 rows), where `facts` = `{"organism", "instrument", "label", "cell_line", "organism_part", "disease"}` (lower-case strings from prefill and term matches).
- Rule: candidates must share organism, instrument and label; rank by number of shared cell line / organism part / disease; ties by accession descending (newer first). If `corpus_root` is None, return rows from the index only (header from `columns`, no rows).

- [ ] **Step 1: Write the failing tests** `test_build_index` (3 fixtures → 3 rows, correct organism/instrument/label), `test_similar_requires_core_match` (no shared label → `[]`), `test_similar_ranks_by_shared_biology`.
- [ ] **Step 2:** Tests fail.
- [ ] **Step 3:** Implement both.
- [ ] **Step 4:** Tests pass. Build the real index from `origin/main` of sdrf-annotated-datasets into `assets/corpus_index.tsv`; check row count equals the number of non-sandbox SDRFs and file size is under 5 MB.
- [ ] **Step 5: Commit** `feat: corpus index of annotated SDRFs and similar-SDRF lookup` (including `assets/corpus_index.tsv`).

### Task 5: Render the sheet and wire it into SDRF_PREFILL

**Files:**
- Modify: `bin/sdrf_sheet.py` (CLI and `render`)
- Modify: `modules/local/sdrf_prefill/main.nf` (run the sheet, new outputs)
- Modify: `modules/local/sdrf_annotate/main.nf` (input `sheet: Path?`, prompt text)
- Modify: `workflows/sdrf_agentic_annotator.nf` (pass the sheet; empty when `params.sheet` is false)
- Test: `tests/python/test_sdrf_sheet.py`, `tests/default.nf.test` (stub)

**Interfaces:**
- Consumes: Tasks 2-4 functions; `params.sheet`, `params.ontology_dir`, `params.corpus_index` from Task 1.
- Produces: CLI `sdrf_sheet.py EVIDENCE_DIR PREFILL.json OUT_PREFIX [--ontology-dir DIR] [--corpus-index TSV]` writing `OUT_PREFIX.sheet.md` and `OUT_PREFIX.sheet.json`; `render(sheet: dict, limit: int = 12000) -> str`. SDRF_PREFILL output record gains `sheet: file("${pxd}.sheet.md")`.

- [ ] **Step 1: Write the failing tests** `test_render_cap` (a sheet with 30 kB of content → `len(render(...)) <= 12000`, sections in order: Methods excerpt, Term matches, Search settings, Design from file names, Similar SDRFs, each item with its source), `test_cli_never_fails` (evidence dir with empty manuscript and a corrupt ontology dir → exit 0, both files written, the sheet names the failed section).
- [ ] **Step 2:** Tests fail. **Step 3:** Implement `render` and the CLI (each section built in its own try/except). Cut order when over the limit: similar SDRF rows, then term matches beyond top 5 per category, then the excerpt.
- [ ] **Step 4:** In SDRF_PREFILL, after `sdrf_prefill.py`, run `sdrf_sheet.py evidence ${pxd}.prefill.json ${pxd} ${ontology_dir ? "--ontology-dir " + ontology_dir : ''} ${corpus_index ? "--corpus-index " + corpus_index : ''} || echo "sheet failed" > ${pxd}.sheet.md`; pass `ontology_dir` and `corpus_index` as path inputs (optional). In SDRF_ANNOTATE add to the prompt, when `sheet` is set: "Read ${sheet} first. It holds the methods of the manuscript and candidate values, each with its source sentence or file. Open evidence/manuscript.txt only for a fact the sheet does not hold. Values marked confirm were found by a pattern: confirm them before use. The similar SDRFs show a column set, not values for this dataset. Record in the manifest the sentence that supports each value."
- [ ] **Step 5:** Python tests pass; `nf-test test tests/default.nf.test` passes; `nf-core pipelines lint` passes.
- [ ] **Step 6:** Run `sdrf_sheet.py` on the evidence folders of 5 Campaign 6 datasets (copied from Codon results) and read each sheet by hand: correct methods excerpt, no junk term matches, size within the cap. Fix and add a regression test for anything wrong.
- [ ] **Step 7: Commit** `feat: give the annotate agent an evidence sheet built without a model`; push the branch (no PR yet).

### Task 6: Test on 10 datasets on Codon

**Files (Codon, Campaign 6 iteration, not the repo):** `accessions/fast10.txt`, `scripts/run_annotate.sh` (models file lists both models; passes `--annotate_model`, `--review_model` from env `ANNOTATE_MODEL`, `REVIEW_MODEL`), `scripts/compare_fast10.py`.

- [ ] **Step 1:** Choose 10 Campaign 6 review-PASS datasets covering cell line, tissue, TMT or SILAC, DIA, and one with more than 20 raw files; record why each was chosen in the iteration README.
- [ ] **Step 2:** Check the runner image has pandas and pyarrow (`singularity exec <sif> python -c "import pandas, pyarrow"`); if not, convert the needed caches to TSV once into the iteration `tmp/ontologies/`.
- [ ] **Step 3:** Clone `feat/fast-annotation` into `pipeline_fast`; launch run B (`--sheet false`) and run C (`--sheet true --ontology_dir ... --corpus_index ...`), each with `ANNOTATE_MODEL=gemini-3.8-flash-eu REVIEW_MODEL=openai/DeepSeek-V4-Flash-0731 MAX_PARALLEL=10`, own job, own limiter (RATE_LIMIT 18 for the capped review model is shared: run B and C one after the other, or set the limiter per model if the proxy allows).
- [ ] **Step 4:** `compare_fast10.py` reports per dataset and arm (A = Campaign 6 results): wall time per step (trace), requests and median request size per step (gateway log), review verdict, field agreement with A on the fields listed in the spec. Read every disagreement by hand and classify it (A wrong, B/C wrong, both acceptable).
- [ ] **Step 5:** Report to the user against the success criteria in the spec; update the iteration README and INDEX status; dispatch the cleanup auditor.

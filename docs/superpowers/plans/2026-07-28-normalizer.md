# SDRF Harness — Deposited-SDRF Normalizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Auto-apply the deterministic light repairs that stand between author-deposited SDRFs and `parse_sdrf` (ms-proteomics) validation — add `technology type`, add `comment[proteomics data acquisition method]` (DDA/DIA), strip trailing whitespace, pad ragged rows, and fix `comment[fraction identifier]` = `not applicable` → `1` — so a large class of deposited SDRFs flow through the loop to merge instead of escalating.

**Architecture:** A pure `normalizer.normalize_sdrf(text, acquisition)`; acquisition (DDA/DIA) inferred from project metadata (`fetcher.infer_acquisition`) and carried on `Bundle.acquisition`. Wired transparently into `run.build_get_sdrf_text` (which already loads the bundle), so the loop needs no change. Matches the manual repair that fixed the earlier deposited-SDRF batch.

**Tech Stack:** Python 3.11 stdlib + `pytest`.

## Global Constraints

- Package `sdrf_harness` under `src/`; Python 3.11+.
- `normalize_sdrf` is pure (text→text); never uses pandas (raw tab-separated lines).
- Column order: inserted `technology type` goes immediately after `assay name`; `comment[proteomics data acquisition method]` immediately after `technology type`. If `assay name` is absent, append both at the end of the header (still valid — a fallback that never crashes).
- Acquisition CV values: DDA → `NT=Data-dependent acquisition;AC=PRIDE:0000627`; DIA → `NT=Data-independent acquisition;AC=PRIDE:0000450`.
- Tests must not hit network; no Claude/tool attribution in commits.

---

### Task 1: `infer_acquisition` + `Bundle.acquisition`

**Files:**
- Modify: `src/sdrf_harness/models.py` (add `acquisition` field), `src/sdrf_harness/fetcher.py`
- Test: `tests/test_infer_acquisition.py`

**Interfaces:**
- Produces: `Bundle.acquisition: str` (default `"DDA"`); `infer_acquisition(project_json: dict) -> str` returning `"DIA"` if any of the project title, keywords, or `dataProcessingProtocol` contains a DIA signal (`dia`, `data-independent`, `data independent`, `swath`, case-insensitive), else `"DDA"`. `parse_pride_project` sets `bundle.acquisition = infer_acquisition(project_json)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_infer_acquisition.py
from sdrf_harness.fetcher import infer_acquisition, parse_pride_project

def test_dia_from_title():
    assert infer_acquisition({"title": "SWATH quantification of X"}) == "DIA"

def test_dia_from_keywords():
    assert infer_acquisition({"keywords": ["data-independent acquisition", "plasma"]}) == "DIA"

def test_default_dda():
    assert infer_acquisition({"title": "Label-free shotgun proteome"}) == "DDA"

def test_bundle_carries_acquisition():
    proj = {"accession": "PXD1", "title": "DIA analysis", "organisms": []}
    b = parse_pride_project(proj, [{"fileName": "a.raw"}])
    assert b.acquisition == "DIA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_infer_acquisition.py -v`
Expected: FAIL with `ImportError: cannot import name 'infer_acquisition'`

- [ ] **Step 3: Write minimal implementation**

In `src/sdrf_harness/models.py`, add to `Bundle` (after `deposited_sdrf_url`):
```python
    acquisition: str = "DDA"
```

In `src/sdrf_harness/fetcher.py`, add near the top-level functions:
```python
_DIA_SIGNALS = ("data-independent", "data independent", "swath", "dia")

def infer_acquisition(project_json: dict) -> str:
    hay = " ".join([
        str(project_json.get("title", "")),
        " ".join(str(k) for k in (project_json.get("keywords") or [])),
        str(project_json.get("dataProcessingProtocol", "")),
    ]).lower()
    return "DIA" if any(s in hay for s in _DIA_SIGNALS) else "DDA"
```
And in `parse_pride_project`, add `acquisition=infer_acquisition(project_json)` to the `Bundle(...)` construction.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_infer_acquisition.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/models.py src/sdrf_harness/fetcher.py tests/test_infer_acquisition.py
git commit -m "feat: infer_acquisition (DDA/DIA) + Bundle.acquisition"
```

---

### Task 2: `normalize_sdrf`

**Files:**
- Create: `src/sdrf_harness/normalizer.py`
- Test: `tests/test_normalizer.py`

**Interfaces:**
- Produces: `ACQ_CV: dict[str,str]` (`{"DDA": "NT=Data-dependent acquisition;AC=PRIDE:0000627", "DIA": "NT=Data-independent acquisition;AC=PRIDE:0000450"}`); `normalize_sdrf(text: str, acquisition: str = "DDA") -> str` that: strips trailing whitespace from every cell; pads short rows to header length with `not available`; if `technology type` missing, inserts it (value `proteomic profiling by mass spectrometry`) right after `assay name` (else appends at header end); if `comment[proteomics data acquisition method]` missing, inserts it (value `ACQ_CV[acquisition]`) right after `technology type` (else appends); replaces `comment[fraction identifier]` cells equal to `not applicable` with `1`. Returns the rebuilt TSV text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalizer.py
from sdrf_harness.normalizer import normalize_sdrf

def _cols(text): return text.splitlines()[0].split("\t")

def test_adds_technology_type_and_acquisition():
    text = ("source name\tassay name\tcomment[data file]\n"
            "s1\trun 1\ta.raw\n")
    out = normalize_sdrf(text, acquisition="DIA")
    cols = _cols(out)
    assert "technology type" in cols
    assert "comment[proteomics data acquisition method]" in cols
    # order: assay name -> technology type -> acquisition method
    assert cols.index("technology type") == cols.index("assay name") + 1
    assert cols.index("comment[proteomics data acquisition method]") == cols.index("technology type") + 1
    row = out.splitlines()[1].split("\t")
    assert row[cols.index("technology type")] == "proteomic profiling by mass spectrometry"
    assert row[cols.index("comment[proteomics data acquisition method]")] == \
        "NT=Data-independent acquisition;AC=PRIDE:0000450"

def test_strips_whitespace_and_pads_ragged():
    text = "source name\tassay name\tcomment[data file]\ns1 \trun 1\n"
    out = normalize_sdrf(text)
    row = out.splitlines()[1].split("\t")
    assert row[0] == "s1"                      # trailing space stripped
    assert len(row) == len(_cols(out))         # padded to header width

def test_fixes_fraction_identifier_not_applicable():
    text = ("source name\tassay name\tcomment[proteomics data acquisition method]\t"
            "technology type\tcomment[fraction identifier]\tcomment[data file]\n"
            "s1\trun 1\tNT=Data-dependent acquisition;AC=PRIDE:0000627\t"
            "proteomic profiling by mass spectrometry\tnot applicable\ta.raw\n")
    out = normalize_sdrf(text)
    cols = _cols(out); row = out.splitlines()[1].split("\t")
    assert row[cols.index("comment[fraction identifier]")] == "1"

def test_idempotent_when_already_complete():
    text = ("source name\tassay name\ttechnology type\t"
            "comment[proteomics data acquisition method]\tcomment[data file]\n"
            "s1\trun 1\tproteomic profiling by mass spectrometry\t"
            "NT=Data-dependent acquisition;AC=PRIDE:0000627\ta.raw\n")
    assert normalize_sdrf(text) == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_normalizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.normalizer'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/normalizer.py
from __future__ import annotations

ACQ_CV = {
    "DDA": "NT=Data-dependent acquisition;AC=PRIDE:0000627",
    "DIA": "NT=Data-independent acquisition;AC=PRIDE:0000450",
}


def _insert_after(header, rows, anchor, name, value):
    if name in header:
        return header, rows
    idx = (header.index(anchor) + 1) if anchor in header else len(header)
    header = header[:idx] + [name] + header[idx:]
    rows = [r[:idx] + [value] + r[idx:] for r in rows]
    return header, rows


def normalize_sdrf(text: str, acquisition: str = "DDA") -> str:
    lines = text.splitlines()
    if not lines:
        return text
    header = [c.strip() for c in lines[0].split("\t")]
    rows = [[c.strip() for c in ln.split("\t")] for ln in lines[1:] if ln != ""]
    rows = [r + ["not available"] * (len(header) - len(r)) if len(r) < len(header) else r
            for r in rows]
    header, rows = _insert_after(header, rows, "assay name", "technology type",
                                 "proteomic profiling by mass spectrometry")
    header, rows = _insert_after(header, rows, "technology type",
                                 "comment[proteomics data acquisition method]",
                                 ACQ_CV.get(acquisition, ACQ_CV["DDA"]))
    if "comment[fraction identifier]" in header:
        fi = header.index("comment[fraction identifier]")
        for r in rows:
            if fi < len(r) and r[fi] == "not applicable":
                r[fi] = "1"
    return "\t".join(header) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_normalizer.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/normalizer.py tests/test_normalizer.py
git commit -m "feat: normalize_sdrf — add technology type + acquisition, strip/pad/fraction fixes"
```

---

### Task 3: Wire the normalizer into the fetch step

**Files:**
- Modify: `src/sdrf_harness/run.py`
- Test: `tests/test_run_cli.py` (append)

**Interfaces:**
- Consumes: `normalize_sdrf` (normalizer), existing `build_get_sdrf_text`.
- Produces: `build_get_sdrf_text` now, when a deposited SDRF is fetched, returns `normalize_sdrf(text, b.acquisition)` instead of the raw text; returns `None` unchanged when there is no bundle/SDRF.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_run_cli.py
def test_get_sdrf_text_normalizes(tmp_path, monkeypatch):
    from sdrf_harness import run as runmod
    from sdrf_harness.models import Bundle
    # a bundle whose fetched SDRF lacks technology type + acquisition
    b = Bundle(accession="PXD9", repository="pride", deposited_sdrf="sdrf.tsv",
               deposited_sdrf_url="https://x/sdrf.tsv", acquisition="DIA")
    (tmp_path / "PXD9.bundle.json").write_text(b.to_json())
    monkeypatch.setattr(runmod, "fetch_deposited_sdrf",
                        lambda bundle, ym=None, session=None: "source name\tassay name\tcomment[data file]\ns1\tr\ta.raw\n")
    getter = runmod.build_get_sdrf_text(tmp_path)
    out = getter("PXD9")
    cols = out.splitlines()[0].split("\t")
    assert "technology type" in cols
    assert "comment[proteomics data acquisition method]" in cols
    assert "NT=Data-independent acquisition;AC=PRIDE:0000450" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_run_cli.py::test_get_sdrf_text_normalizes -v`
Expected: FAIL (technology type not added — raw text returned)

- [ ] **Step 3: Write minimal implementation**

In `src/sdrf_harness/run.py`: add `from .normalizer import normalize_sdrf` to the imports, and change `build_get_sdrf_text`'s `_get` so that after fetching:
```python
        b = Bundle.from_json(bpath.read_text())
        text = fetch_deposited_sdrf(b)
        return normalize_sdrf(text, b.acquisition) if text is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_run_cli.py -v` then `python -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/run.py tests/test_run_cli.py
git commit -m "feat: normalize deposited SDRFs in the fetch step before validation"
```

---

## Exit criteria

- `python -m pytest` green.
- Re-dogfood the 5-accession batch: the datasets that previously escalated with `parse_sdrf: validation errors` due to missing `technology type` / acquisition columns now **merge** (or escalate only for a genuinely different reason).

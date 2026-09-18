# SDRF Model Benchmark Implementation Plan

> **For agentic workers:** Implement task-by-task with a test cycle per task. Steps use checkbox (`- [ ]`) syntax.
> Every code block starts with a `# file: <path>` line (paths relative to `benchmarks/sdrf-model-bench/`).

**Goal:** A self-contained, shareable benchmark that scores LLM-generated SDRFs (Claude raw and
skills arms, Ollama, and third-party models) against curated ground truth, records tokens, cost and
time, and renders a single workshop slide.

**Architecture:** A standalone Python package `sdrf_model_bench` under `benchmarks/sdrf-model-bench/`
with no imports from `sdrf_agentic_annotator`. The pipeline is `select → freeze → run → score → report`,
and each stage reads and writes plain files in `data/`, `outputs/` and `results/`, so any stage can be
re-run or replaced (for example a collaborator submitting outputs directly).

**Tech Stack:** Python ≥3.11, `anthropic` SDK, `requests`, `pyyaml`, `matplotlib`, pytest. External
CLIs: `parse_sdrf` (sdrf-pipelines) and `claude` (Claude Code, skills arm only).

**Spec:** `docs/design/2026-09-18-model-benchmark-design.md`

## Global Constraints

- The package must not import `sdrf_agentic_annotator`.
- Never write SDRFs with pandas. Read and write them as raw TSV text.
- Opus 5 and Sonnet 5 reject `temperature`, so it is never sent to Claude models. Ollama uses `temperature: 0`.
- Opus 5 server-side `fallbacks` stay **off**, because a fallback would mix models inside one run. A refusal counts as a failed run.
- Always pass Ollama `num_ctx` explicitly.
- Evidence budget: 24,000 estimated tokens (characters ÷ 4).
- Validation runs `parse_sdrf validate-sdrf --use_ols_cache_only`, with at most 2 at a time (a machine RAM limit).
- The skills arm uses `--bare --plugin-dir <sanitised copy> --strict-mcp-config`, and the agent cannot read the home directory.
- Scoring weights: validity 0.20, completeness 0.15, accuracy 0.50, specificity 0.15. Headline = 0.8 × deterministic + 0.2 × judge. If there is no judge score, headline = deterministic.
- Commit messages must not mention AI assistants or tooling (enforced by a hook).

**Deviation from spec, found while checking the tools:** Sonnet 5 has no temperature control, so the
judge makes 3 calls and takes the median (the original brainstorm design), not a single call at
temperature 0. Validity counts distinct error *messages* with digits normalised, not error types. With
types, missing-column errors would collapse into one type and a file missing many required columns
would get almost no penalty.

---

## File map

| file | responsibility |
|---|---|
| `pyproject.toml`, `models.yaml`, `pricing.yaml` | package + roster + price table |
| `src/sdrf_model_bench/config.py` | roster/pricing loading, cost computation |
| `src/sdrf_model_bench/sdrf_io.py` | raw TSV read, ontology-cell parsing |
| `src/sdrf_model_bench/score.py` | row alignment + deterministic score |
| `src/sdrf_model_bench/validator.py` | `parse_sdrf` wrapper |
| `src/sdrf_model_bench/providers.py` | `generate(messages) -> Completion` per provider |
| `src/sdrf_model_bench/evidence.py` | frozen evidence loading, token estimate |
| `src/sdrf_model_bench/prompts.py` | raw-arm prompt with evidence budget |
| `src/sdrf_model_bench/rawloop.py` | draft → validate → repair loop |
| `src/sdrf_model_bench/skills_arm.py` | sanitised plugin, workspace, `claude -p` run + audit |
| `src/sdrf_model_bench/judge.py` | reference-guided LLM judge |
| `src/sdrf_model_bench/select.py` | quant typing, truth filters, stratified selection |
| `src/sdrf_model_bench/freeze.py` | PRIDE/EuropePMC fetch, methods extraction, quality score |
| `src/sdrf_model_bench/runner.py` | run matrix, resume, per-run outputs |
| `src/sdrf_model_bench/scoring_run.py` | score an outputs tree → `results/runs.jsonl` |
| `src/sdrf_model_bench/report.py` | aggregation + slide + backup plots |
| `src/sdrf_model_bench/cli.py` | `sdrf-bench select/freeze/run/score/report/pack` |
| `README.md`, `SUBMISSION.md` | hand-off docs |

---

### Task 1: Scaffold, roster, pricing

**Interfaces — Produces:** `ModelSpec`, `load_models(path) -> list[ModelSpec]`,
`load_pricing(path) -> dict`, `cost_usd(pricing, model, usage) -> float | None`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_config.py
from pathlib import Path

import pytest

from sdrf_model_bench.config import cost_usd, load_models, load_pricing

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_roster_loads_and_is_consistent():
    specs = load_models(ROOT / "models.yaml")
    ids = [s.id for s in specs]
    assert len(ids) == len(set(ids))
    assert {s.arm for s in specs} == {"raw", "skills"}
    assert all(s.provider == "claude-code" for s in specs if s.arm == "skills")
    assert all("num_ctx" in s.options for s in specs if s.provider == "ollama")


def test_skills_arm_requires_claude_code(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("models:\n  - {id: x, provider: anthropic, model: m, arm: skills}\n")
    with pytest.raises(ValueError, match="skills arm"):
        load_models(p)


def test_cost_uses_cache_multipliers():
    pricing = {"m": {"input": 2.0, "output": 10.0}}
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000}
    assert cost_usd(pricing, "m", usage) == pytest.approx(2.0 + 1.0 + 0.2 + 2.5)
    assert cost_usd(pricing, "unknown", usage) is None


def test_shipped_pricing_covers_claude_roster():
    pricing = load_pricing(ROOT / "pricing.yaml")
    for s in load_models(ROOT / "models.yaml"):
        if s.provider in ("anthropic", "claude-code"):
            assert s.model in pricing
```

- [ ] **Step 2: Run it** — `cd benchmarks/sdrf-model-bench && uv run --extra dev pytest tests/test_config.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```toml
# file: pyproject.toml
[project]
name = "sdrf-model-bench"
version = "1.0.0"
description = "Benchmark LLMs on producing SDRF-Proteomics files"
requires-python = ">=3.11"
dependencies = ["requests>=2.31", "pyyaml>=6", "anthropic>=0.60", "matplotlib>=3.8"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
sdrf-bench = "sdrf_model_bench.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```yaml
# file: models.yaml
# The benchmark roster. Each entry is one "model-arm".
#   provider: anthropic | ollama | openai | claude-code | custom
#   arm:      raw (standalone draft/validate/repair loop) | skills (Claude Code + sdrf-skills)
#   context_window: the model's maximum context, used to flag context-limited runs
# To add your own model, copy the "your-model" entry, set enabled: true, and point
# options.callable at a function `generate(messages, **options) -> str | (str, usage_dict)`.
models:
  - {id: opus-5-skills,    provider: claude-code, model: claude-opus-5,    arm: skills, context_window: 1000000}
  - {id: sonnet-5-skills,  provider: claude-code, model: claude-sonnet-5,  arm: skills, context_window: 1000000}
  - {id: haiku-4.5-skills, provider: claude-code, model: claude-haiku-4-5, arm: skills, context_window: 200000}
  - {id: opus-5-raw,       provider: anthropic,   model: claude-opus-5,    arm: raw,    context_window: 1000000}
  - {id: sonnet-5-raw,     provider: anthropic,   model: claude-sonnet-5,  arm: raw,    context_window: 1000000}
  - {id: haiku-4.5-raw,    provider: anthropic,   model: claude-haiku-4-5, arm: raw,    context_window: 200000}
  - {id: gemma4-12b-raw,   provider: ollama, model: "gemma4:12b", arm: raw, context_window: 262144, options: {num_ctx: 40960}}
  - {id: gemma2-9b-raw,    provider: ollama, model: "gemma2:9b",  arm: raw, context_window: 8192,   options: {num_ctx: 8192}}
  - {id: qwen2.5-3b-raw,   provider: ollama, model: "qwen2.5:3b", arm: raw, context_window: 32768,  options: {num_ctx: 32768}}
  - id: your-model-raw
    provider: custom
    model: your-model-name
    arm: raw
    context_window: 128000
    enabled: false
    options: {callable: "my_provider:generate"}
```

```yaml
# file: pricing.yaml
# USD per million tokens, Anthropic first-party API (reference cached 2026-06-24).
# Cache reads bill at 0.1x input, 5-minute cache writes at 1.25x input.
# Re-check against the live pricing page before publishing numbers.
models:
  claude-opus-5:    {input: 5.0, output: 25.0}
  claude-sonnet-5:  {input: 2.0, output: 10.0}
  claude-haiku-4-5: {input: 1.0, output: 5.0}
```

```python
# file: src/sdrf_model_bench/__init__.py
"""Benchmark LLMs on producing SDRF-Proteomics files."""

__version__ = "1.0.0"
```

```python
# file: src/sdrf_model_bench/config.py
"""Roster and price-table loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ARMS = ("raw", "skills")
PROVIDERS = ("anthropic", "ollama", "openai", "claude-code", "custom")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    model: str
    arm: str
    context_window: int | None = None
    options: dict = field(default_factory=dict)
    enabled: bool = True


def load_models(path: Path, include_disabled: bool = False) -> list[ModelSpec]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    specs: list[ModelSpec] = []
    seen: set[str] = set()
    for raw in data.get("models", []):
        spec = ModelSpec(
            id=raw["id"],
            provider=raw["provider"],
            model=raw.get("model", ""),
            arm=raw.get("arm", "raw"),
            context_window=raw.get("context_window"),
            options=dict(raw.get("options") or {}),
            enabled=raw.get("enabled", True),
        )
        if spec.provider not in PROVIDERS:
            raise ValueError(f"{spec.id}: unknown provider {spec.provider!r} (known: {PROVIDERS})")
        if spec.arm not in ARMS:
            raise ValueError(f"{spec.id}: unknown arm {spec.arm!r} (known: {ARMS})")
        if spec.arm == "skills" and spec.provider != "claude-code":
            raise ValueError(f"{spec.id}: the skills arm requires provider 'claude-code'")
        if spec.id in seen:
            raise ValueError(f"duplicate model id {spec.id!r}")
        seen.add(spec.id)
        if spec.enabled or include_disabled:
            specs.append(spec)
    return specs


def load_pricing(path: Path) -> dict[str, dict[str, float]]:
    return (yaml.safe_load(Path(path).read_text()) or {}).get("models", {})


def cost_usd(pricing: dict, model: str, usage: dict) -> float | None:
    """API cost of one run in USD, or None when the model has no price (local models)."""
    p = pricing.get(model)
    if not p:
        return None
    per_in = p["input"] / 1e6
    return (
        usage.get("input_tokens", 0) * per_in
        + usage.get("output_tokens", 0) * p["output"] / 1e6
        + usage.get("cache_read_input_tokens", 0) * per_in * p.get("cache_read_multiplier", 0.1)
        + usage.get("cache_creation_input_tokens", 0) * per_in * p.get("cache_write_multiplier", 1.25)
    )
```

- [ ] **Step 4: Run** — same command → PASS.
- [ ] **Step 5: Commit** — `git add benchmarks/sdrf-model-bench && git commit -m "Scaffold SDRF model benchmark with roster and pricing"`

---

### Task 2: SDRF reading and deterministic scoring

**Interfaces — Produces:** `read_sdrf(text) -> (header, rows)`, `column_values(header, row, name) -> list[str]`,
`parse_term(cell) -> (label, accession)`, `score_deterministic(truth_text, pred_text, validity) -> dict`
with keys `validity, completeness, accuracy, specificity, deterministic, n_truth_rows, n_aligned, field_accuracy`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_score.py
import pytest

from sdrf_model_bench.score import (
    file_key, mods_agreement, score_deterministic, term_agreement, tolerance_agreement,
)
from sdrf_model_bench.sdrf_io import parse_term, read_sdrf

H = ("source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\t"
     "comment[data file]\tcomment[label]\tcomment[modification parameters]\t"
     "comment[modification parameters]\tcomment[precursor mass tolerance]\n")


def row(i, organism="homo sapiens", disease="NT=breast carcinoma;AC=EFO:0000305",
        label="AC=MS:1002038;NT=label free sample", tol="10 ppm", mods=None):
    mods = mods or ["NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed",
                    "NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable"]
    return f"s{i}\t{organism}\t{disease}\trun{i}\tfile{i}.raw\t{label}\t{mods[0]}\t{mods[1]}\t{tol}\n"


TRUTH = H + row(1) + row(2)


def test_read_sdrf_keeps_duplicate_columns():
    header, rows = read_sdrf(TRUTH)
    assert header.count("comment[modification parameters]") == 2
    assert len(rows) == 2


def test_parse_term():
    assert parse_term("NT=Breast Carcinoma;AC=efo_0000305") == ("breast carcinoma", "EFO:0000305")
    assert parse_term("Homo sapiens") == ("homo sapiens", "")


def test_term_agreement_levels():
    t = "NT=breast carcinoma;AC=EFO:0000305"
    assert term_agreement(t, t) == 1.0
    assert term_agreement(t, "breast carcinoma") == 0.5
    assert term_agreement(t, "NT=breast carcinoma;AC=EFO:9999999") == 0.5
    assert term_agreement(t, "NT=lung carcinoma;AC=EFO:0001071") == 0.0
    assert term_agreement("homo sapiens", "Homo sapiens") == 1.0


def test_tolerance_and_mods():
    assert tolerance_agreement("10 ppm", "10.0ppm") == 1.0
    assert tolerance_agreement("10 ppm", "0.01 Da") == 0.0
    a = ["NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed"]
    assert mods_agreement(a, ["NT=carbamidomethyl;TA=C;MT=fixed"]) == 1.0
    assert mods_agreement(a, a + ["NT=Oxidation;TA=M;MT=Variable"]) == 0.5


def test_file_key_normalises():
    assert file_key("ftp://x/y/File1.RAW") == file_key("file1.raw") == "file1"
    assert file_key("a.mzML.gz") == "a"


def test_self_score_is_perfect():
    s = score_deterministic(TRUTH, TRUTH, validity=1.0)
    assert s["deterministic"] == pytest.approx(100.0)


def test_missing_rows_and_not_available_are_penalised():
    pred = H + row(1, disease="not available")
    s = score_deterministic(TRUTH, pred, validity=1.0)
    assert s["n_aligned"] == 1
    assert s["completeness"] == pytest.approx(0.5)
    assert s["specificity"] < 1.0
    assert s["deterministic"] < 80


def test_empty_prediction_scores_zero():
    s = score_deterministic(TRUTH, "", validity=0.0)
    assert s["deterministic"] == 0.0
```

- [ ] **Step 2: Run** — `uv run --extra dev pytest tests/test_score.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/sdrf_io.py
"""Raw-text SDRF reading. SDRFs repeat column names on purpose, so no pandas here."""

from __future__ import annotations

NA_VALUES = {"", "not available", "not applicable", "na", "n/a", "none"}


def read_sdrf(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return [], []
    header = [h.strip().lower() for h in lines[0].split("\t")]
    rows = []
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.split("\t")]
        cells += [""] * (len(header) - len(cells))
        rows.append(cells[: len(header)])
    return header, rows


def column_values(header: list[str], row: list[str], name: str) -> list[str]:
    return [row[i] for i, h in enumerate(header) if h == name]


def first_value(header: list[str], row: list[str], name: str) -> str | None:
    vals = column_values(header, row, name)
    return vals[0] if vals else None


def is_na(value: str | None) -> bool:
    return value is None or value.strip().lower() in NA_VALUES


def parse_kv(cell: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in cell.split(";"):
        if "=" in part:
            key, val = part.split("=", 1)
            out[key.strip().upper()] = val.strip()
    return out


def parse_term(cell: str) -> tuple[str, str]:
    """(lowercased label, normalised accession) from an ontology cell or a plain label."""
    kv = parse_kv(cell)
    if "NT" in kv or "AC" in kv:
        return kv.get("NT", "").lower(), kv.get("AC", "").upper().replace("_", ":")
    return cell.strip().lower(), ""
```

```python
# file: src/sdrf_model_bench/score.py
"""Deterministic comparison of a predicted SDRF against a curated reference."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sdrf_model_bench.sdrf_io import column_values, first_value, is_na, parse_kv, parse_term, read_sdrf

KEY_FIELDS = [
    "characteristics[organism]",
    "characteristics[organism part]",
    "characteristics[disease]",
    "characteristics[cell type]",
    "comment[label]",
    "comment[instrument]",
    "comment[cleavage agent details]",
    "comment[modification parameters]",
    "comment[precursor mass tolerance]",
    "comment[fragment mass tolerance]",
    "comment[fraction identifier]",
    "comment[technical replicate]",
]
EXACT_FIELDS = {"comment[fraction identifier]", "comment[technical replicate]"}
TOLERANCE_FIELDS = {"comment[precursor mass tolerance]", "comment[fragment mass tolerance]"}
MOD_FIELD = "comment[modification parameters]"
INFRA_COLUMNS = {
    "source name", "assay name", "comment[data file]", "comment[file uri]",
    "comment[sdrf version]", "comment[sdrf template]", "comment[sdrf annotation tool]",
}
WEIGHTS = {"validity": 0.20, "completeness": 0.15, "accuracy": 0.50, "specificity": 0.15}
FILE_EXTENSIONS = (".gz", ".zip", ".raw", ".mzml", ".mzxml", ".wiff", ".d", ".mgf", ".scan")
TOL_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-z]+)\s*$", re.I)


def file_key(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    changed = True
    while changed:
        changed = False
        for ext in FILE_EXTENSIONS:
            if base.endswith(ext) and len(base) > len(ext):
                base = base[: -len(ext)]
                changed = True
    return base


def term_agreement(truth: str, pred: str) -> float:
    t_label, t_acc = parse_term(truth)
    p_label, p_acc = parse_term(pred)
    if t_acc and p_acc and t_acc == p_acc:
        return 1.0
    if t_label and t_label == p_label:
        return 0.5 if t_acc else 1.0
    return 0.0


def tolerance_agreement(truth: str, pred: str) -> float:
    t, p = TOL_RE.match(truth or ""), TOL_RE.match(pred or "")
    if not t or not p:
        return 1.0 if (truth or "").strip().lower() == (pred or "").strip().lower() else 0.0
    same_unit = t.group(2).lower() == p.group(2).lower()
    return 1.0 if same_unit and abs(float(t.group(1)) - float(p.group(1))) < 1e-9 else 0.0


def _mod_parts(cell: str) -> tuple[str, str, str, str]:
    kv = parse_kv(cell)
    return (
        kv.get("AC", "").upper().replace("_", ":"),
        kv.get("NT", "").lower(),
        kv.get("MT", "").lower(),
        "".join(sorted(kv.get("TA", "").upper().replace(",", ""))),
    )


def mods_agreement(truth_cells: list[str], pred_cells: list[str]) -> float:
    truth = [_mod_parts(c) for c in truth_cells if not is_na(c)]
    pred = [_mod_parts(c) for c in pred_cells if not is_na(c)]
    if not truth and not pred:
        return 1.0
    unmatched = list(pred)
    matched = 0
    for t_ac, t_nt, t_mt, t_ta in truth:
        for i, (p_ac, p_nt, p_mt, p_ta) in enumerate(unmatched):
            same_mod = (t_ac and t_ac == p_ac) or (t_nt and t_nt == p_nt)
            if same_mod and t_mt == p_mt and t_ta == p_ta:
                matched += 1
                del unmatched[i]
                break
    return matched / (len(truth) + len(pred) - matched)


def _row_keys(header, rows, use_label: bool) -> dict[tuple[str, str], list[list[str]]]:
    keyed: dict[tuple[str, str], list[list[str]]] = defaultdict(list)
    for r in rows:
        data_file = first_value(header, r, "comment[data file]") or ""
        label = parse_term(first_value(header, r, "comment[label]") or "")[0] if use_label else ""
        keyed[(file_key(data_file), label)].append(r)
    return keyed


def align_rows(t_header, t_rows, p_header, p_rows) -> list[tuple[list[str], list[str]]]:
    labels = " ".join(first_value(t_header, r, "comment[label]") or "" for r in t_rows).lower()
    use_label = "tmt" in labels or "itraq" in labels
    truth, pred = _row_keys(t_header, t_rows, use_label), _row_keys(p_header, p_rows, use_label)
    pairs = []
    for key, t_list in truth.items():
        pairs.extend(zip(t_list, pred.get(key, [])))
    return pairs


def _cell_agreement(field: str, truth_row, t_header, pred_row, p_header) -> float | None:
    if field == MOD_FIELD:
        t_cells = column_values(t_header, truth_row, field)
        if all(is_na(c) for c in t_cells):
            return None
        return mods_agreement(t_cells, column_values(p_header, pred_row, field))
    truth = first_value(t_header, truth_row, field)
    if is_na(truth):
        return None
    pred = first_value(p_header, pred_row, field) or ""
    if field in EXACT_FIELDS:
        return 1.0 if truth.strip().lower() == pred.strip().lower() else 0.0
    if field in TOLERANCE_FIELDS:
        return tolerance_agreement(truth, pred)
    return term_agreement(truth, pred)


def _explicit_na(field: str, pred_row, p_header) -> bool:
    vals = column_values(p_header, pred_row, field)
    return bool(vals) and all(v.strip().lower() in ("not available", "not applicable") for v in vals)


def score_deterministic(truth_text: str, pred_text: str, validity: float) -> dict:
    t_header, t_rows = read_sdrf(truth_text)
    p_header, p_rows = read_sdrf(pred_text)
    pairs = align_rows(t_header, t_rows, p_header, p_rows) if p_rows else []

    t_cols = Counter(h for h in t_header if h not in INFRA_COLUMNS)
    p_cols = Counter(p_header)
    col_share = sum(min(n, p_cols[c]) for c, n in t_cols.items()) / max(1, sum(t_cols.values()))
    row_share = len(pairs) / max(1, len(t_rows))
    completeness = col_share * row_share if p_rows else 0.0

    per_field: dict[str, list[float]] = defaultdict(list)
    counted = explicit_na = 0
    for t_row, p_row in pairs:
        for field in KEY_FIELDS:
            agreement = _cell_agreement(field, t_row, t_header, p_row, p_header)
            if agreement is None:
                continue
            per_field[field].append(agreement)
            counted += 1
            explicit_na += _explicit_na(field, p_row, p_header)
    all_cells = [a for vals in per_field.values() for a in vals]
    accuracy = sum(all_cells) / len(all_cells) if all_cells else 0.0
    specificity = 1 - explicit_na / counted if counted else 0.0

    components = {
        "validity": validity if p_rows else 0.0,
        "completeness": completeness,
        "accuracy": accuracy,
        "specificity": specificity,
    }
    deterministic = 100 * sum(WEIGHTS[k] * v for k, v in components.items())
    return {
        **components,
        "deterministic": deterministic,
        "n_truth_rows": len(t_rows),
        "n_aligned": len(pairs),
        "field_accuracy": {f: sum(v) / len(v) for f, v in per_field.items()},
    }
```

- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "Add row-aligned deterministic SDRF scoring"` (after `git add`).

---

### Task 3: Validator wrapper

**Interfaces — Produces:** `ValidationResult(errors, warnings, raw)`, `parse_output(text)`,
`distinct_errors(errors) -> list[str]`, `validity_score(result) -> float`,
`validate(path, templates=(), parse_sdrf="parse_sdrf") -> ValidationResult`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_validator.py
import sys

from sdrf_model_bench.validator import distinct_errors, parse_output, validate, validity_score

OUT = """ERROR: Required column 'comment[label]' is missing from the SDRF file
ERROR: Row 3: bad value
ERROR: Row 4: bad value
WARNING: Term: foo in column 'characteristics[organism]', is not found
There were validation errors."""


def test_parse_and_distinct():
    res = parse_output(OUT)
    assert len(res.errors) == 3 and len(res.warnings) == 1
    assert distinct_errors(res.errors) == [
        "Required column 'comment[label]' is missing from the SDRF file", "Row #: bad value"]
    assert validity_score(res) == 0.8


def test_clean_output_scores_one():
    assert validity_score(parse_output("Most seems to be fine. There were only warnings.")) == 1.0


def test_validity_floor_is_zero():
    res = parse_output("\n".join(f"ERROR: missing col{chr(97 + i)}" for i in range(15)))
    assert validity_score(res) == 0.0


def test_validate_runs_the_given_binary(tmp_path):
    fake = tmp_path / "fake_parse_sdrf"
    fake.write_text(f"#!{sys.executable}\nimport sys\nprint('ERROR: ' + ' '.join(sys.argv[1:]))\n")
    fake.chmod(0o755)
    res = validate(tmp_path / "x.tsv", templates=["human"], parse_sdrf=str(fake))
    assert "validate-sdrf" in res.errors[0] and "--use_ols_cache_only" in res.errors[0]
    assert "-t human" in res.errors[0]


def test_crash_is_an_error(tmp_path):
    fake = tmp_path / "crash"
    fake.write_text(f"#!{sys.executable}\nraise SystemExit('Traceback: boom')\n")
    fake.chmod(0o755)
    assert validate(tmp_path / "x.tsv", parse_sdrf=str(fake)).errors
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/validator.py
"""Thin wrapper over `parse_sdrf validate-sdrf` (sdrf-pipelines)."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

# One validation holds ~2 GB with ontologies loaded; cap concurrency (override via env).
_SLOTS = threading.BoundedSemaphore(int(os.environ.get("SDRF_BENCH_VALIDATE_CONCURRENCY", "2")))


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: str = ""


def parse_output(text: str) -> ValidationResult:
    res = ValidationResult(raw=text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ERROR:"):
            res.errors.append(line[len("ERROR:"):].strip())
        elif line.startswith("WARNING:"):
            res.warnings.append(line[len("WARNING:"):].strip())
    return res


def distinct_errors(errors: list[str]) -> list[str]:
    return sorted({re.sub(r"\d+", "#", e) for e in errors})


def validity_score(result: ValidationResult) -> float:
    return max(0.0, 1.0 - 0.1 * len(distinct_errors(result.errors)))


def validate(path: Path, templates=(), parse_sdrf: str = "parse_sdrf", timeout: int = 900) -> ValidationResult:
    cmd = [parse_sdrf, "validate-sdrf", "-s", str(path), "--use_ols_cache_only"]
    for t in templates:
        cmd += ["-t", t]
    with _SLOTS:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ValidationResult(errors=[f"validator failed to run: {exc}"])
    res = parse_output(proc.stdout + "\n" + proc.stderr)
    if proc.returncode != 0 and not res.errors:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        res.errors.append(f"validator crashed: {tail[0]}")
    return res
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add parse_sdrf validator wrapper".

---

### Task 4: Providers

**Interfaces — Consumes:** `ModelSpec`. **Produces:** `Completion(text, usage, stop_reason, wall_s)`,
`make_generate(spec) -> Callable[[list[dict]], Completion]`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_providers.py
import sys
import types

import pytest

from sdrf_model_bench.config import ModelSpec
from sdrf_model_bench.providers import (
    Completion, anthropic_generate, custom_generate, make_generate, ollama_generate, openai_generate,
)

MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls, self.trust_env = payload, [], True

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResp(self.payload)


def test_ollama_sets_num_ctx_and_reads_counts():
    s = FakeSession({"message": {"content": "out"}, "prompt_eval_count": 11, "eval_count": 7, "done_reason": "stop"})
    c = ollama_generate(MSGS, model="m", num_ctx=8192, session=s)
    url, kw = s.calls[0]
    assert url.endswith("/api/chat")
    assert kw["json"]["options"] == {"num_ctx": 8192, "temperature": 0}
    assert (c.text, c.usage["input_tokens"], c.usage["output_tokens"]) == ("out", 11, 7)
    assert s.trust_env is False


def test_openai_usage():
    s = FakeSession({"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    c = openai_generate(MSGS, model="m", base_url="http://h/v1", session=s)
    assert c.usage == {"input_tokens": 3, "output_tokens": 2}


def test_anthropic_splits_system_and_reads_usage():
    captured = {}
    usage = types.SimpleNamespace(input_tokens=5, output_tokens=6,
                                  cache_read_input_tokens=None, cache_creation_input_tokens=1)
    msg = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="tsv")],
                                usage=usage, stop_reason="end_turn")

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return msg

    class Messages:
        def stream(self, **kw):
            captured.update(kw)
            return Stream()

    client = types.SimpleNamespace(messages=Messages())
    c = anthropic_generate(MSGS, model="claude-sonnet-5", client=client)
    assert captured["system"] == "sys" and captured["messages"] == [MSGS[1]]
    assert "temperature" not in captured
    assert c.usage == {"input_tokens": 5, "output_tokens": 6,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1}


def test_custom_accepts_str_or_tuple(tmp_path, monkeypatch):
    (tmp_path / "myprov.py").write_text(
        "def plain(messages, **kw):\n    return 'a'\n"
        "def rich(messages, **kw):\n    return 'b', {'input_tokens': 1}\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert custom_generate(MSGS, callable="myprov:plain").text == "a"
    assert custom_generate(MSGS, callable="myprov:rich").usage == {"input_tokens": 1}


def test_make_generate_rejects_skills_provider():
    with pytest.raises(ValueError):
        make_generate(ModelSpec(id="x", provider="claude-code", model="m", arm="skills"))


def test_completion_is_a_dataclass():
    assert Completion("t", {}).stop_reason == ""
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/providers.py
"""`generate(messages) -> Completion` for every supported raw-arm provider.

Messages are OpenAI-style `[{"role": "system"|"user"|"assistant", "content": str}]`.
Every provider reports usage with the same keys so cost and token plots line up.
"""

from __future__ import annotations

import importlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from sdrf_model_bench.config import ModelSpec


@dataclass
class Completion:
    text: str
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    wall_s: float = 0.0


Generate = Callable[[list[dict]], Completion]


def _session(session=None):
    sess = session or requests.Session()
    sess.trust_env = False  # never route local/API traffic through an inherited proxy
    return sess


def anthropic_generate(messages, *, model: str, max_tokens: int = 64000, client=None, **_opts) -> Completion:
    """Claude via the official SDK. No temperature (rejected by Opus 5 / Sonnet 5) and no
    server-side fallbacks (a fallback would mix models inside one benchmark run)."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic(max_retries=4)
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": chat}
    if system:
        kwargs["system"] = system
    t0 = time.monotonic()
    with client.messages.stream(**kwargs) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    u = msg.usage
    usage = {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
    }
    return Completion(text, usage, msg.stop_reason or "", time.monotonic() - t0)


def ollama_generate(messages, *, model: str, num_ctx: int, host: str = "http://localhost:11434",
                    timeout: int = 3600, session=None, **_opts) -> Completion:
    """Local Ollama. `num_ctx` is mandatory: Ollama's default window silently truncates prompts."""
    payload = {"model": model, "messages": list(messages), "stream": False,
               "options": {"num_ctx": int(num_ctx), "temperature": 0}}
    t0 = time.monotonic()
    resp = _session(session).post(host.rstrip("/") + "/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    d = resp.json()
    usage = {"input_tokens": d.get("prompt_eval_count", 0), "output_tokens": d.get("eval_count", 0)}
    return Completion(d["message"]["content"] or "", usage, d.get("done_reason", ""), time.monotonic() - t0)


def openai_generate(messages, *, model: str, base_url: str, api_key_env: str = "OPENAI_API_KEY",
                    timeout: int = 1800, session=None, **_opts) -> Completion:
    """Any OpenAI-compatible /chat/completions endpoint (vLLM, LiteLLM, hosted APIs)."""
    key = os.environ.get(api_key_env, "not-needed")
    t0 = time.monotonic()
    resp = _session(session).post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": list(messages)},
        timeout=timeout,
    )
    resp.raise_for_status()
    d = resp.json()
    choice = d["choices"][0]
    u = d.get("usage") or {}
    usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
    return Completion(choice["message"]["content"] or "", usage, choice.get("finish_reason") or "",
                      time.monotonic() - t0)


def custom_generate(messages, *, callable: str, **opts) -> Completion:
    """Collaborator hook: `module:function(messages, **options) -> str | (str, usage_dict)`."""
    module, name = callable.split(":", 1)
    fn = getattr(importlib.import_module(module), name)
    t0 = time.monotonic()
    out = fn(list(messages), **opts)
    text, usage = (out, {}) if isinstance(out, str) else (out[0], dict(out[1] or {}))
    return Completion(text, usage, "", time.monotonic() - t0)


def make_generate(spec: ModelSpec) -> Generate:
    opts = dict(spec.options)
    if spec.provider == "anthropic":
        return lambda m: anthropic_generate(m, model=spec.model, **opts)
    if spec.provider == "ollama":
        return lambda m: ollama_generate(m, model=spec.model, **opts)
    if spec.provider == "openai":
        return lambda m: openai_generate(m, model=spec.model, **opts)
    if spec.provider == "custom":
        return lambda m: custom_generate(m, **opts)
    raise ValueError(f"{spec.id}: provider {spec.provider!r} has no raw-arm generate()")
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add raw-arm model providers with token accounting".

---

### Task 5: Evidence, prompts, raw loop

**Interfaces — Produces:** `Evidence`, `load_evidence(data_dir, acc)`, `estimate_tokens(text)`,
`build_messages(ev, manuscript, budget_tokens=24000) -> (messages, info)` where
`info = {"evidence_tokens", "prompt_tokens", "truncated"}`, `extract_tsv(text) -> str | None`,
`RawResult`, `run_raw(generate, messages, workdir, validate_fn, max_repairs=2) -> RawResult`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_rawloop.py
import json

from sdrf_model_bench.evidence import estimate_tokens, load_evidence
from sdrf_model_bench.prompts import build_messages
from sdrf_model_bench.providers import Completion
from sdrf_model_bench.rawloop import extract_tsv, run_raw
from sdrf_model_bench.validator import ValidationResult

GOOD = "source name\tcomment[data file]\ns1\ta.raw\n"


def make_ev(tmp_path, manuscript="M" * 400):
    d = tmp_path / "evidence" / "PXD1"
    d.mkdir(parents=True)
    (d / "pride.json").write_text(json.dumps({"title": "T", "projectDescription": "D" * 100,
                                              "organisms": [{"name": "Homo sapiens (human)"}]}))
    (d / "files.json").write_text(json.dumps(["a.raw", "b.raw"]))
    (d / "manuscript.txt").write_text(manuscript)
    (d / "meta.json").write_text(json.dumps({"accession": "PXD1"}))
    return load_evidence(tmp_path, "PXD1")


def test_manuscript_toggle(tmp_path):
    ev = make_ev(tmp_path)
    on, _ = build_messages(ev, manuscript=True)
    off, _ = build_messages(ev, manuscript=False)
    assert "M" * 400 in on[-1]["content"]
    assert "M" * 400 not in off[-1]["content"] and "a.raw" in off[-1]["content"]


def test_budget_truncates_manuscript_first(tmp_path):
    ev = make_ev(tmp_path, manuscript="x" * 400_000)
    msgs, info = build_messages(ev, manuscript=True, budget_tokens=2000)
    assert info["truncated"] and info["evidence_tokens"] <= 2000
    assert "Homo sapiens" in msgs[-1]["content"]
    assert estimate_tokens("abcd") == 1


def test_extract_tsv_from_fence_and_prose():
    assert extract_tsv(f"Here:\n```tsv\n{GOOD}```\nbye") == GOOD
    assert extract_tsv("no table here") is None
    assert extract_tsv("Source name\tx\n") is None  # header only


def test_repair_loop_feeds_errors_back(tmp_path):
    replies = iter(["oops, no table", f"```tsv\n{GOOD}```", f"```tsv\n{GOOD}```"])
    seen = []

    def gen(msgs):
        seen.append(msgs)
        return Completion(next(replies), {"input_tokens": 10, "output_tokens": 2})

    results = iter([ValidationResult(errors=["Row 1: bad"]), ValidationResult()])
    r = run_raw(gen, [{"role": "user", "content": "go"}], tmp_path, lambda p: next(results))
    assert r.turns == 3 and r.sdrf == GOOD and not r.validation.errors
    assert r.usage == {"input_tokens": 30, "output_tokens": 6}
    assert "Row #: bad" in seen[2][-1]["content"]


def test_repair_budget_is_respected(tmp_path):
    gen = lambda m: Completion("nothing", {})  # noqa: E731
    r = run_raw(gen, [{"role": "user", "content": "go"}], tmp_path, lambda p: ValidationResult(), max_repairs=1)
    assert r.turns == 2 and r.sdrf is None
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/evidence.py
"""Frozen per-dataset evidence bundles (written by `freeze`, never re-fetched at run time)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Evidence:
    accession: str
    pride: dict
    files: list[str]
    manuscript: str
    meta: dict


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def evidence_dir(data_dir: Path, accession: str) -> Path:
    return Path(data_dir) / "evidence" / accession


def load_evidence(data_dir: Path, accession: str) -> Evidence:
    d = evidence_dir(data_dir, accession)
    ms = d / "manuscript.txt"
    return Evidence(
        accession=accession,
        pride=json.loads((d / "pride.json").read_text()),
        files=json.loads((d / "files.json").read_text()),
        manuscript=ms.read_text() if ms.exists() else "",
        meta=json.loads((d / "meta.json").read_text()),
    )
```

```python
# file: src/sdrf_model_bench/prompts.py
"""The raw-arm prompt. Identical for every raw model; only the evidence varies."""

from __future__ import annotations

from sdrf_model_bench.evidence import Evidence, estimate_tokens

SYSTEM = """You annotate proteomics datasets in the SDRF-Proteomics format.

An SDRF is a tab-separated table with one row per raw file and sample (for multiplexed
labelling such as TMT: one row per raw file and channel). Use these columns when the
evidence supports them, in this order, and add factor value[...] columns for the
variables the study compares:

source name, characteristics[organism], characteristics[organism part],
characteristics[disease], characteristics[cell type], characteristics[biological replicate],
assay name, technology type, comment[data file], comment[technical replicate],
comment[fraction identifier], comment[label], comment[instrument],
comment[cleavage agent details], comment[modification parameters] (repeat the column once
per modification), comment[precursor mass tolerance], comment[fragment mass tolerance],
comment[proteomics data acquisition method], factor value[<variable>]

Cell conventions:
- ontology terms as key=value pairs, e.g. NT=breast carcinoma;AC=EFO:0000305
- organism as the NCBI taxonomy name in lower case, e.g. homo sapiens
- label e.g. AC=MS:1002038;NT=label free sample or AC=MS:1002616;NT=TMT126
- modification e.g. NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed
- tolerance e.g. 10 ppm or 0.02 Da
- write 'not available' only when the evidence really does not say
- comment[data file] must use the exact raw file names given

Reply with the complete SDRF inside one ```tsv fenced block and nothing else."""

PRIDE_FIELDS = [
    ("Title", "title"), ("Description", "projectDescription"),
    ("Sample processing protocol", "sampleProcessingProtocol"),
    ("Data processing protocol", "dataProcessingProtocol"),
]
PRIDE_LISTS = [
    ("Organisms", "organisms"), ("Organism parts", "organismParts"), ("Diseases", "diseases"),
    ("Instruments", "instruments"), ("Modifications", "identifiedPTMStrings"),
    ("Quantification", "quantificationMethods"), ("Experiment types", "experimentTypes"),
]


def _names(items) -> str:
    out = []
    for it in items or []:
        out.append(it.get("name", "") if isinstance(it, dict) else str(it))
    return "; ".join(x for x in out if x)


def render_pride(pride: dict, text_limit: int | None = None) -> str:
    lines = []
    for label, key in PRIDE_FIELDS:
        val = (pride.get(key) or "").strip()
        if text_limit is not None:
            val = val[:text_limit]
        if val:
            lines.append(f"{label}: {val}")
    for label, key in PRIDE_LISTS:
        val = _names(pride.get(key))
        if val:
            lines.append(f"{label}: {val}")
    kw = pride.get("keywords")
    if kw:
        lines.append("Keywords: " + (", ".join(kw) if isinstance(kw, list) else str(kw)))
    return "\n".join(lines)


def build_messages(ev: Evidence, manuscript: bool, budget_tokens: int = 24000) -> tuple[list[dict], dict]:
    """Assemble the prompt. Over budget, the manuscript is cut first, then the PRIDE free text."""
    files = "\n".join(ev.files)
    pride = render_pride(ev.pride)
    ms = ev.manuscript if manuscript else ""
    fixed = estimate_tokens(files)
    truncated = False
    room = budget_tokens - fixed - estimate_tokens(pride)
    if ms and estimate_tokens(ms) > room:
        ms = ms[: max(0, room) * 4]
        truncated = True
    if fixed + estimate_tokens(pride) + estimate_tokens(ms) > budget_tokens:
        limit = 4000
        while limit > 200 and fixed + estimate_tokens(render_pride(ev.pride, limit)) > budget_tokens:
            limit //= 2
        pride = render_pride(ev.pride, limit)
        truncated = True

    parts = [f"Dataset: {ev.accession}", "", "## Repository metadata (PRIDE)", pride, "",
             f"## Raw files ({len(ev.files)})", files]
    if ms:
        parts += ["", "## Manuscript excerpt (methods and sample-related legends)", ms]
    parts += ["", "Create the SDRF for this dataset."]
    user = "\n".join(parts)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    info = {
        "evidence_tokens": estimate_tokens(pride) + fixed + estimate_tokens(ms),
        "prompt_tokens": estimate_tokens(SYSTEM) + estimate_tokens(user),
        "truncated": truncated,
    }
    return messages, info
```

```python
# file: src/sdrf_model_bench/rawloop.py
"""Raw arm: draft -> validate -> repair, identical for every model."""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sdrf_model_bench.validator import ValidationResult, distinct_errors

FENCE_RE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.S)
NO_TABLE = "No SDRF table was found. Reply with the complete SDRF inside one ```tsv fenced block."
FIX = "The SDRF validator reported these errors. Fix them and reply with the complete corrected SDRF:\n"


def extract_tsv(text: str) -> str | None:
    blocks = [b for b in FENCE_RE.findall(text or "") if "source name" in b.lower()]
    lines = (blocks[0] if blocks else text or "").splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.lower().lstrip().startswith("source name") and "\t" in ln), None)
    if start is None:
        return None
    out = []
    for ln in lines[start:]:
        if "\t" not in ln:
            break
        out.append(ln.rstrip("\r"))
    return "\n".join(out) + "\n" if len(out) >= 2 else None


@dataclass
class RawResult:
    sdrf: str | None
    usage: dict = field(default_factory=dict)
    turns: int = 0
    wall_s: float = 0.0
    stop_reasons: list[str] = field(default_factory=list)
    validation: ValidationResult | None = None
    transcript: list[dict] = field(default_factory=list)


def run_raw(generate, messages: list[dict], workdir: Path, validate_fn, max_repairs: int = 2) -> RawResult:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    msgs = list(messages)
    usage: Counter = Counter()
    result = RawResult(sdrf=None)
    t0 = time.monotonic()
    for turn in range(max_repairs + 1):
        completion = generate(msgs)
        usage.update(completion.usage)
        result.turns = turn + 1
        result.stop_reasons.append(completion.stop_reason)
        msgs = msgs + [{"role": "assistant", "content": completion.text}]
        tsv = extract_tsv(completion.text)
        if tsv is None:
            feedback = NO_TABLE
        else:
            path = workdir / "sdrf.tsv"
            path.write_text(tsv)
            result.sdrf, result.validation = tsv, validate_fn(path)
            if not result.validation.errors:
                break
            feedback = FIX + "\n".join(distinct_errors(result.validation.errors)[:30])
        if turn < max_repairs:
            msgs = msgs + [{"role": "user", "content": feedback}]
    result.usage = dict(usage)
    result.wall_s = time.monotonic() - t0
    result.transcript = msgs
    return result
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add raw-arm prompt and repair loop".

---

### Task 6: Skills arm

**Interfaces — Produces:** `LeakError`, `build_sanitized_plugin(src, dest, forbidden) -> Path`,
`prepare_workspace(ws, ev_dir, manuscript) -> list[str]`, `build_command(...) -> list[str]`,
`parse_stream(lines, workspace) -> dict` (keys `usage, cost_usd, num_turns, is_error, tool_calls, leak_suspect`),
`run_skills(spec, ev_dir, manuscript, templates, run_dir, plugin_src, forbidden, claude_bin) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_skills_arm.py
import json

import pytest

from sdrf_model_bench.skills_arm import (
    LeakError, build_command, build_sanitized_plugin, parse_stream, prepare_workspace,
)


def fake_plugin(root, leak=False):
    (root / "skills" / "sdrf-annotate").mkdir(parents=True)
    (root / "skills" / "sdrf-annotate" / "SKILL.md").write_text("annotate " + ("PXD000001" if leak else ""))
    (root / "spec" / "sdrf-proteomics").mkdir(parents=True)
    (root / "spec" / "sdrf-proteomics" / "TERMS.tsv").write_text("t")
    (root / "annotations").mkdir()
    (root / "annotations" / "PXD000001.sdrf.tsv").write_text("truth!")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "sdrf-skills", "hooks": "./h.json"}))
    return root


def test_sanitized_plugin_drops_data_and_hooks(tmp_path):
    src = fake_plugin(tmp_path / "src")
    dest = build_sanitized_plugin(src, tmp_path / "clean", forbidden=["PXD000001"])
    assert (dest / "skills" / "sdrf-annotate" / "SKILL.md").exists()
    assert not (dest / "annotations").exists()
    assert "hooks" not in json.loads((dest / ".claude-plugin" / "plugin.json").read_text())


def test_leak_audit_raises(tmp_path):
    src = fake_plugin(tmp_path / "src", leak=True)
    with pytest.raises(LeakError, match="PXD000001"):
        build_sanitized_plugin(src, tmp_path / "clean", forbidden=["PXD000001"])


def test_workspace_respects_manuscript_flag(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    for n in ("pride.json", "files.json", "manuscript.txt", "meta.json"):
        (ev / n).write_text("{}")
    assert sorted(prepare_workspace(tmp_path / "w1", ev, manuscript=False)) == ["files.json", "pride.json"]
    assert "manuscript.txt" in prepare_workspace(tmp_path / "w2", ev, manuscript=True)


def test_command_is_locked_down(tmp_path):
    cmd = build_command("claude", "claude-opus-5", tmp_path / "p", "do it")
    joined = " ".join(cmd)
    for flag in ("--bare", "--strict-mcp-config", "--plugin-dir", "--no-session-persistence"):
        assert flag in cmd
    assert "WebFetch" in joined and "Read(~/**)" in joined and "Bash(parse_sdrf validate-sdrf:*)" in joined


def test_parse_stream_usage_and_leaks(tmp_path):
    ws = str(tmp_path)
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": f"{ws}/evidence/pride.json"}},
            {"type": "tool_use", "name": "Glob", "input": {"pattern": "**/*.tsv", "path": "/Users/x/data"}}]}}),
        "not json",
        json.dumps({"type": "result", "is_error": False, "num_turns": 7, "total_cost_usd": 0.42,
                    "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900,
                              "cache_creation_input_tokens": 10}}),
    ]
    out = parse_stream(lines, ws)
    assert out["cost_usd"] == 0.42 and out["num_turns"] == 7
    assert out["usage"]["cache_read_input_tokens"] == 900
    assert out["leak_suspect"] and len(out["tool_calls"]) == 2
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/skills_arm.py
"""Skills arm: Claude Code headless with only the sdrf-skills plugin, offline, sandboxed to a workspace.

Isolation, from strongest to weakest:
  * --bare: no user hooks, CLAUDE.md, other plugins, memory; --strict-mcp-config: no MCP servers.
  * a sanitised plugin copy: no bundled annotations/examples, audited for benchmark accessions.
  * permissions: web tools and subagents denied; Read denied under the home directory, where the
    curated datasets live; Bash only for `parse_sdrf validate-sdrf`.
  * post-hoc audit: any file tool touching a path outside the workspace flags the run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

KEEP = ["skills", "spec/sdrf-proteomics", "criteria", "scripts", "tools",
        "data/cell_line_manifest.tsv", ".claude-plugin/plugin.json"]
EVIDENCE_FILES = ["pride.json", "files.json"]
PATH_KEYS = ("file_path", "path", "notebook_path")
ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "TodoWrite",
           "Bash(parse_sdrf validate-sdrf:*)"]
DENIED = ["WebFetch", "WebSearch", "Agent", "Task", "Read(~/**)", "Glob(~/**)", "Grep(~/**)"]

PROMPT = """Create an SDRF-Proteomics file for the proteomics dataset {accession}.

Everything you may use is in ./evidence/: {listing}. There is no network access, so do not try to
fetch anything. Follow the SDRF skills (start with the sdrf-annotate skill). Validate with:
  parse_sdrf validate-sdrf -s ./output.sdrf.tsv --use_ols_cache_only{templates}
Write the final SDRF to ./output.sdrf.tsv. Do not ask questions: make your best judgement and finish."""


class LeakError(RuntimeError):
    pass


def build_sanitized_plugin(src: Path, dest: Path, forbidden) -> Path:
    src, dest = Path(src), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for rel in KEEP:
        s = src / rel
        if s.is_dir():
            shutil.copytree(s, dest / rel, ignore=shutil.ignore_patterns("*.sdrf.tsv", "__pycache__"))
        elif s.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, dest / rel)
    manifest = dest / ".claude-plugin" / "plugin.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        data.pop("hooks", None)
        manifest.write_text(json.dumps(data, indent=2))
    hits = []
    needles = [a for a in forbidden if a]
    for f in dest.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="ignore")
            hits += [f"{a} in {f.relative_to(dest)}" for a in needles if a in text]
    if hits:
        raise LeakError("benchmark accessions found in plugin copy: " + "; ".join(hits[:10]))
    return dest


def prepare_workspace(ws: Path, ev_dir: Path, manuscript: bool) -> list[str]:
    target = Path(ws) / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    names = EVIDENCE_FILES + (["manuscript.txt"] if manuscript else [])
    copied = []
    for n in names:
        if (Path(ev_dir) / n).exists():
            shutil.copy2(Path(ev_dir) / n, target / n)
            copied.append(n)
    return copied


def build_command(claude_bin: str, model: str, plugin_dir: Path, prompt: str) -> list[str]:
    return [
        claude_bin, "-p", prompt,
        "--bare", "--plugin-dir", str(plugin_dir), "--strict-mcp-config",
        "--model", model, "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--permission-mode", "dontAsk",
        "--allowedTools", *ALLOWED,
        "--disallowedTools", *DENIED,
    ]


def _outside(path: str, workspace: str) -> bool:
    return os.path.isabs(path) and not os.path.realpath(path).startswith(os.path.realpath(workspace))


def parse_stream(lines, workspace: str) -> dict:
    out = {"usage": {}, "cost_usd": None, "num_turns": 0, "is_error": True, "tool_calls": [], "leak_suspect": False}
    for line in lines:
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") != "tool_use":
                    continue
                inp = block.get("input") or {}
                out["tool_calls"].append({"name": block.get("name"), "input": inp})
                if any(_outside(str(inp.get(k, "")), workspace) for k in PATH_KEYS):
                    out["leak_suspect"] = True
        elif ev.get("type") == "result":
            u = ev.get("usage") or {}
            out["usage"] = {k: u.get(k, 0) or 0 for k in (
                "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
            out["cost_usd"] = ev.get("total_cost_usd")
            out["num_turns"] = ev.get("num_turns", 0)
            out["is_error"] = bool(ev.get("is_error"))
    return out


def run_skills(model: str, ev_dir: Path, accession: str, manuscript: bool, templates, run_dir: Path,
               plugin_dir: Path, claude_bin: str = "claude", timeout: int = 2700) -> dict:
    ws = Path(run_dir) / "workspace"
    if str(ws.resolve()).startswith(str(Path.home().resolve())):
        raise RuntimeError(f"skills workspace {ws} is under $HOME, which the agent cannot read; "
                           "set --outputs to a path outside the home directory")
    copied = prepare_workspace(ws, ev_dir, manuscript)
    local_plugin = ws / ".plugin"
    shutil.copytree(plugin_dir, local_plugin, dirs_exist_ok=True)
    tmpl = "".join(f" -t {t}" for t in templates)
    prompt = PROMPT.format(accession=accession, listing=", ".join(copied), templates=tmpl)
    cmd = build_command(claude_bin, model, local_plugin, prompt)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout)
        stdout, returncode = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, returncode = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), -1
    (Path(run_dir) / "transcript.jsonl").write_text(stdout)
    parsed = parse_stream(stdout.splitlines(), str(ws))
    out_file = ws / "output.sdrf.tsv"
    return {
        **parsed,
        "sdrf": out_file.read_text() if out_file.exists() else None,
        "wall_s": time.monotonic() - t0,
        "returncode": returncode,
    }
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add sandboxed skills arm".

---

### Task 7: Judge

**Interfaces — Consumes:** `Completion`. **Produces:** `judge(generate, truth_tsv, pred_tsv, n=3) -> dict`
with keys `judge` (0–100 or None), `factor_fidelity`, `design_fidelity`, `free_text`, `usage`, `raw`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_judge.py
import json

from sdrf_model_bench.judge import judge
from sdrf_model_bench.providers import Completion


def test_median_of_three_and_blind_prompt():
    scores = iter([(10, 10, 10), (6, 4, 2), (8, 6, 4)])
    prompts = []

    def gen(msgs):
        prompts.append(msgs[-1]["content"])
        f, d, t = next(scores)
        return Completion(json.dumps({"factor_fidelity": f, "design_fidelity": d, "free_text": t}),
                          {"input_tokens": 1, "output_tokens": 1})

    r = judge(gen, "REF", "PRED")
    assert (r["factor_fidelity"], r["design_fidelity"], r["free_text"]) == (8, 6, 4)
    assert r["judge"] == 60.0 and r["usage"]["input_tokens"] == 3
    assert "REF" in prompts[0] and "PRED" in prompts[0]


def test_unparseable_judge_is_none():
    r = judge(lambda m: Completion("I refuse", {}), "a", "b")
    assert r["judge"] is None
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/judge.py
"""Reference-guided LLM judge for what exact matching cannot see. The judge never sees model names."""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter

RUBRIC = """You grade an SDRF-Proteomics annotation against a curated reference for the same dataset.
Ignore column order, letter case and formatting. Score each criterion from 0 to 10:
- factor_fidelity: do the factor value columns capture the same experimental comparison as the reference?
- design_fidelity: does the sample-to-file (and channel) mapping match: samples, biological and
  technical replicates, fractions, labels?
- free_text: are free-text characteristics (treatment, individual, time, sample description)
  faithful to the reference?
Reply with only JSON: {"factor_fidelity": n, "design_fidelity": n, "free_text": n, "rationale": "<= 40 words"}"""
KEYS = ("factor_fidelity", "design_fidelity", "free_text")
MAX_CHARS = 40_000


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {k: float(d[k]) for k in KEYS}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def judge(generate, truth_tsv: str, pred_tsv: str, n: int = 3) -> dict:
    user = (f"## Reference SDRF\n```tsv\n{truth_tsv[:MAX_CHARS]}\n```\n\n"
            f"## Annotation to grade\n```tsv\n{pred_tsv[:MAX_CHARS]}\n```")
    msgs = [{"role": "system", "content": RUBRIC}, {"role": "user", "content": user}]
    usage: Counter = Counter()
    parsed, raw = [], []
    for _ in range(n):
        c = generate(msgs)
        usage.update(c.usage)
        raw.append(c.text)
        p = _parse(c.text)
        if p:
            parsed.append(p)
    out = {"usage": dict(usage), "raw": raw, "judge": None, **{k: None for k in KEYS}}
    if parsed:
        for k in KEYS:
            out[k] = statistics.median(p[k] for p in parsed)
        out["judge"] = round(10 * sum(out[k] for k in KEYS) / len(KEYS), 2)
    return out
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add reference-guided judge".

---

### Task 8: Selection and freezing

**Interfaces — Produces:** `quant_type(header, rows) -> str | None`, `truth_ok(text) -> bool`,
`made_with_ai(repo, path) -> bool`, `pride_quality(pride) -> float`, `extract_methods(xml) -> str`,
`raw_file_names(files) -> list[str]`, `has_deposited_sdrf(files) -> bool`, `pick_balanced(pool, seed) -> list[dict]`,
`freeze_dataset(acc, truth_path, data_dir, session) -> dict` (raises `SkipDataset`).

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_select_freeze.py
import pytest

from sdrf_model_bench.freeze import extract_methods, has_deposited_sdrf, pride_quality, raw_file_names
from sdrf_model_bench.sdrf_io import read_sdrf
from sdrf_model_bench.select import pick_balanced, quant_type, truth_ok


def qt(label, acq="NT=Data-Dependent Acquisition;AC=PRIDE:0000627"):
    return quant_type(*read_sdrf(f"source name\tcomment[label]\tcomment[proteomics data acquisition method]\n"
                                 f"s\t{label}\t{acq}\n"))


def test_quant_type():
    assert qt("AC=MS:1002616;NT=TMT126") == "TMT"
    assert qt("AC=MS:1002038;NT=label free sample") == "LFQ"
    assert qt("label free sample", "NT=Data-Independent Acquisition;AC=PRIDE:0000450") == "DIA"
    assert qt("label free sample", "NT=SWATH MS") == "DIA"
    assert qt("SILAC heavy") is None


def test_truth_ok_limits_rows():
    head = "source name\tcomment[data file]\n"
    assert truth_ok(head + "s\ta.raw\n")
    assert not truth_ok(head + "".join(f"s{i}\tf{i}.raw\n" for i in range(61)))
    assert not truth_ok("source name\tx\ns\ty\n")


def test_pride_quality():
    full = {k: [{"name": "x"}] for k in ("organisms", "organismParts", "diseases", "instruments",
                                         "identifiedPTMStrings", "quantificationMethods")}
    full.update(sampleProcessingProtocol="p" * 200, dataProcessingProtocol="d" * 200)
    assert pride_quality(full) == 1.0
    assert pride_quality({"organisms": [{"name": "x"}]}) == pytest.approx(1 / 8)


def test_files_helpers():
    files = [{"fileName": "a.raw", "fileCategory": {"value": "RAW"}},
             {"fileName": "b.txt", "fileCategory": {"value": "OTHER"}},
             {"fileName": "x.sdrf.tsv", "fileCategory": {"value": "EXPERIMENTAL DESIGN"}}]
    assert raw_file_names(files) == ["a.raw"]
    assert has_deposited_sdrf(files)


def test_extract_methods_prefers_methods_and_sample_legends():
    xml = """<article><body>
      <sec><title>Introduction</title><p>Background.</p></sec>
      <sec><title>Materials and Methods</title><p>Cells were lysed. TMT labelling.</p></sec>
      <sec><title>Results</title><p>Stuff.</p>
        <fig><caption><p>Samples from 3 patients per condition.</p></caption></fig>
        <fig><caption><p>A volcano plot.</p></caption></fig></sec>
    </body></article>"""
    text = extract_methods(xml)
    assert "Cells were lysed" in text and "3 patients" in text
    assert "Background" not in text and "volcano" not in text


def test_pick_balanced_is_stratified_and_seeded():
    pool = [{"accession": f"P{t}{i}", "qtype": t, "quality": i / 10, "non_human": i % 3 == 0,
             "cell_line_only": False} for t in ("TMT", "LFQ", "DIA") for i in range(9)]
    a, b = pick_balanced(pool, seed=7), pick_balanced(pool, seed=7)
    assert [x["accession"] for x in a] == [x["accession"] for x in b]
    assert len(a) == 12
    for t in ("TMT", "LFQ", "DIA"):
        tiers = sorted(x["tier"] for x in a if x["qtype"] == t)
        assert tiers == ["poor", "poor", "rich", "rich"]
    assert sum(x["non_human"] for x in a) >= 3
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/select.py
"""Ground-truth filtering, quantification typing and stratified, seeded selection."""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

from sdrf_model_bench.sdrf_io import column_values, first_value, is_na, read_sdrf

MAX_ROWS = 60
DIA_RE = re.compile(r"data.independent|\bdia\b|swath", re.I)
AI_RE = re.compile(r"sdrf-skills|annotator|agentic|co-authored-by:\s*claude|generated with claude", re.I)
QTYPES = ("TMT", "LFQ", "DIA")


def quant_type(header, rows) -> str | None:
    labels = " ".join(v for r in rows for v in column_values(header, r, "comment[label]")).lower()
    if "tmt" in labels:
        return "TMT"
    if any(x in labels for x in ("silac", "itraq", "dimethyl")):
        return None
    if "label free" in labels or "label-free" in labels:
        acq = " ".join(v for r in rows
                       for v in column_values(header, r, "comment[proteomics data acquisition method]"))
        return "DIA" if DIA_RE.search(acq) else "LFQ"
    return None


def truth_ok(text: str) -> bool:
    header, rows = read_sdrf(text)
    return "comment[data file]" in header and 1 <= len(rows) <= MAX_ROWS


def made_with_ai(repo: Path, path: Path) -> bool:
    log = subprocess.run(["git", "-C", str(repo), "log", "--format=%B", "--", str(path)],
                         capture_output=True, text=True).stdout
    return bool(AI_RE.search(log))


def describe_truth(text: str) -> dict:
    header, rows = read_sdrf(text)
    organism = (first_value(header, rows[0], "characteristics[organism]") or "").lower() if rows else ""
    cell_lines = [first_value(header, r, "characteristics[cell line]") for r in rows]
    return {
        "qtype": quant_type(header, rows),
        "n_rows": len(rows),
        "organism": organism,
        "non_human": bool(organism) and "homo sapiens" not in organism,
        "cell_line_only": bool(rows) and all(not is_na(c) for c in cell_lines),
        "templates": sorted({t for r in rows for v in column_values(header, r, "comment[sdrf template]")
                             for t in [v.split("NT=")[-1].split(";")[0].strip()] if t}),
    }


def iter_candidates(datasets_dir: Path):
    for path in sorted(Path(datasets_dir).glob("PXD*/PXD*.sdrf.tsv")):
        if path.name != f"{path.parent.name}.sdrf.tsv":
            continue
        text = path.read_text(errors="replace")
        if not truth_ok(text):
            continue
        info = describe_truth(text)
        if info["qtype"]:
            yield {"accession": path.parent.name, "truth_path": str(path), **info}


def pick_balanced(pool: list[dict], seed: int, per_type: int = 4) -> list[dict]:
    """Per quant type, split the pool into quality tertiles and draw half rich, half poor;
    then swap in non-human studies until >=3 and cap cell-line-only studies at 2."""
    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[dict]] = {}
    for qtype in QTYPES:
        items = sorted((p for p in pool if p["qtype"] == qtype), key=lambda p: (p["quality"], p["accession"]))
        third = max(1, len(items) // 3)
        for tier, part in (("poor", items[:third]), ("rich", items[-third:])):
            part = [dict(p, tier=tier) for p in part]
            rng.shuffle(part)
            buckets[(qtype, tier)] = part
    k = per_type // 2
    chosen = {key: items[:k] for key, items in buckets.items()}
    spare = {key: items[k:] for key, items in buckets.items()}

    def count(pred):
        return sum(pred(x) for items in chosen.values() for x in items)

    def swap(want, avoid, stop):
        for key in sorted(chosen):
            for i, x in enumerate(chosen[key]):
                if stop():
                    return
                if avoid(x):
                    alt = next((s for s in spare[key] if want(s)), None)
                    if alt:
                        spare[key].remove(alt)
                        chosen[key][i] = alt

    swap(lambda s: s["non_human"] and not s["cell_line_only"], lambda x: not x["non_human"],
         lambda: count(lambda x: x["non_human"]) >= 3)
    swap(lambda s: not s["cell_line_only"], lambda x: x["cell_line_only"],
         lambda: count(lambda x: x["cell_line_only"]) <= 2)
    return [x for key in sorted(chosen) for x in chosen[key]]
```

```python
# file: src/sdrf_model_bench/freeze.py
"""One-time evidence capture from PRIDE and Europe PMC. Runs never touch the network."""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from sdrf_model_bench.evidence import evidence_dir

PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{acc}"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
METHODS_RE = re.compile(r"method|experimental|materials|procedure|sample prep", re.I)
SAMPLE_RE = re.compile(r"sample|patient|donor|cohort|cell|tissue|condition|replicate|tmt|channel|treat", re.I)
QUALITY_LISTS = ("organisms", "organismParts", "diseases", "instruments", "identifiedPTMStrings",
                 "quantificationMethods")


class SkipDataset(Exception):
    pass


def pride_quality(pride: dict) -> float:
    checks = [bool(pride.get(k)) for k in QUALITY_LISTS]
    checks += [len(pride.get(k) or "") >= 200 for k in ("sampleProcessingProtocol", "dataProcessingProtocol")]
    return sum(checks) / len(checks)


def raw_file_names(files: list[dict]) -> list[str]:
    return sorted(f["fileName"] for f in files if (f.get("fileCategory") or {}).get("value") == "RAW")


def has_deposited_sdrf(files: list[dict]) -> bool:
    return any("sdrf" in f.get("fileName", "").lower() for f in files)


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def extract_methods(xml: str) -> str:
    root = ET.fromstring(xml)
    body = root.find(".//body")
    if body is None:
        return ""
    parts = []
    for sec in body.iter("sec"):
        title = sec.find("title")
        if title is not None and METHODS_RE.search(_text(title)):
            parts.append(_text(sec))
    if not parts:
        parts.append(_text(body))
    for cap in root.iter("caption"):
        t = _text(cap)
        if SAMPLE_RE.search(t):
            parts.append("Legend: " + t)
    return "\n\n".join(dict.fromkeys(parts))


def fetch_json(session, url, **params):
    r = session.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_files(session, acc: str) -> list[dict]:
    files, page = [], 0
    while True:
        batch = fetch_json(session, PRIDE.format(acc=acc) + "/files", pageSize=100, page=page)
        files += batch
        if len(batch) < 100:
            return files
        page += 1


def find_manuscript(session, pride: dict) -> dict | None:
    for ref in pride.get("references") or []:
        pmid = ref.get("pubmedID")
        if not pmid:
            continue
        res = fetch_json(session, f"{EPMC}/search", query=f"EXT_ID:{pmid} AND SRC:MED",
                         resultType="core", format="json")["resultList"]["result"]
        if not res or not res[0].get("pmcid"):
            continue
        license_ = (res[0].get("license") or "").lower()
        if not license_.startswith("cc"):
            continue
        r = session.get(f"{EPMC}/{res[0]['pmcid']}/fullTextXML", timeout=60)
        if r.status_code == 200 and r.text.lstrip().startswith("<"):
            return {"pmid": pmid, "pmcid": res[0]["pmcid"], "license": license_, "xml": r.text}
    return None


def freeze_dataset(acc: str, truth_path: Path, data_dir: Path, session=None, extra_meta: dict | None = None) -> dict:
    session = session or requests.Session()
    pride = fetch_json(session, PRIDE.format(acc=acc))
    files = fetch_files(session, acc)
    if has_deposited_sdrf(files):
        raise SkipDataset("deposited SDRF in PRIDE")
    raws = raw_file_names(files)
    if not raws:
        raise SkipDataset("no RAW files listed")
    ms = find_manuscript(session, pride)
    if not ms:
        raise SkipDataset("no CC-licensed open-access full text")
    methods = extract_methods(ms["xml"])
    if len(methods) < 500:
        raise SkipDataset("methods text too short")
    d = evidence_dir(data_dir, acc)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pride.json").write_text(json.dumps(pride, indent=1, sort_keys=True))
    (d / "files.json").write_text(json.dumps(raws, indent=1))
    (d / "manuscript.txt").write_text(methods)
    meta = {"accession": acc, "pmid": ms["pmid"], "pmcid": ms["pmcid"], "license": ms["license"],
            "pride_quality": pride_quality(pride), "n_raw_files": len(raws), **(extra_meta or {})}
    (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    truth_dir = Path(data_dir) / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(truth_path, truth_dir / f"{acc}.sdrf.tsv")
    return meta
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add dataset selection and evidence freezing".

---

### Task 9: Runner and scoring of output trees

**Interfaces — Consumes:** everything above. **Produces:** `load_manifest(path) -> list[dict]`,
`plan_runs(specs, manifest, replicates) -> list[RunKey]`, `execute_run(key, spec, cfg) -> dict`
(writes `outputs/<model_id>/<run>/{sdrf.tsv, usage.json}`), `score_tree(outputs, data_dir, validate_fn, judge_fn) -> list[dict]`
(writes `score.json` per run and returns records).

Output contract (also the collaborator submission format):

```
outputs/<model_id>/<ACCESSION>__ms-<on|off>__r<replicate>/
    sdrf.tsv       # the model's SDRF (may be absent -> failed)
    usage.json     # {"model_id","provider","model","arm","usage":{...},"cost_usd","wall_s",
                   #  "flags":[...], "context_window", "prompt_tokens"}
```

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_runner.py
import json

from sdrf_model_bench.config import ModelSpec
from sdrf_model_bench.providers import Completion
from sdrf_model_bench.runner import RunConfig, RunKey, execute_run, load_manifest, plan_runs
from sdrf_model_bench.scoring_run import score_tree
from sdrf_model_bench.validator import ValidationResult

TRUTH = "source name\tcharacteristics[organism]\tcomment[data file]\ns1\thomo sapiens\ta.raw\n"


def setup_data(tmp_path):
    data = tmp_path / "data"
    ev = data / "evidence" / "PXD1"
    ev.mkdir(parents=True)
    (ev / "pride.json").write_text(json.dumps({"title": "T"}))
    (ev / "files.json").write_text(json.dumps(["a.raw"]))
    (ev / "manuscript.txt").write_text("methods")
    (ev / "meta.json").write_text(json.dumps({"accession": "PXD1", "tier": "poor", "qtype": "LFQ", "templates": []}))
    (data / "truth").mkdir()
    (data / "truth" / "PXD1.sdrf.tsv").write_text(TRUTH)
    (data / "manifest.tsv").write_text("accession\tqtype\ttier\nPXD1\tLFQ\tpoor\n")
    return data


def test_plan_runs_crosses_everything(tmp_path):
    data = setup_data(tmp_path)
    specs = [ModelSpec("a", "ollama", "m", "raw", options={"num_ctx": 1}),
             ModelSpec("b", "claude-code", "m", "skills")]
    keys = plan_runs(specs, load_manifest(data / "manifest.tsv"), replicates={"PXD1": 2})
    assert len(keys) == 2 * 2 * 2
    assert RunKey("a", "PXD1", True, 1).dirname == "PXD1__ms-on__r1"


def test_execute_and_score_end_to_end(tmp_path):
    data = setup_data(tmp_path)
    spec = ModelSpec("fake-raw", "custom", "fake", "raw", context_window=100_000)
    calls = []

    def gen(msgs):
        calls.append(msgs)
        return Completion(f"```tsv\n{TRUTH}```", {"input_tokens": 100, "output_tokens": 10})

    cfg = RunConfig(data_dir=data, outputs=tmp_path / "out", pricing={},
                    validate_fn=lambda p, t=(): ValidationResult(), generate_factory=lambda s: gen)
    rec = execute_run(RunKey("fake-raw", "PXD1", False, 1), spec, cfg)
    assert rec["flags"] == [] and (tmp_path / "out" / "fake-raw" / "PXD1__ms-off__r1" / "sdrf.tsv").exists()
    execute_run(RunKey("fake-raw", "PXD1", False, 1), spec, cfg)  # resume: no new call
    assert len(calls) == 1

    records = score_tree(tmp_path / "out", data, validate_fn=lambda p, t=(): ValidationResult(), judge_fn=None)
    assert len(records) == 1
    r = records[0]
    assert r["deterministic"] == 100.0 and r["headline"] == 100.0
    assert r["qtype"] == "LFQ" and r["manuscript"] is False
    assert "contamination_suspect" in r["flags"]  # ms-off + poor tier + >= 80


def test_context_limited_flag(tmp_path):
    data = setup_data(tmp_path)
    spec = ModelSpec("tiny", "custom", "fake", "raw", context_window=50)
    cfg = RunConfig(data_dir=data, outputs=tmp_path / "out", pricing={},
                    validate_fn=lambda p, t=(): ValidationResult(),
                    generate_factory=lambda s: (lambda m: Completion("nothing", {})))
    rec = execute_run(RunKey("tiny", "PXD1", True, 1), spec, cfg)
    assert "context_limited" in rec["flags"] and "failed" in rec["flags"]
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
# file: src/sdrf_model_bench/runner.py
"""Execute the run matrix. Each run writes a self-describing directory; finished runs are skipped."""

from __future__ import annotations

import csv
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sdrf_model_bench import skills_arm
from sdrf_model_bench.config import ModelSpec, cost_usd
from sdrf_model_bench.evidence import evidence_dir, load_evidence
from sdrf_model_bench.prompts import build_messages
from sdrf_model_bench.providers import make_generate
from sdrf_model_bench.rawloop import run_raw
from sdrf_model_bench.validator import validate

OUTPUT_RESERVE = 8192  # tokens kept free for the SDRF the model has to write
WORKERS = {"ollama": 1, "anthropic": 4, "openai": 4, "custom": 2, "claude-code": 2}


@dataclass(frozen=True)
class RunKey:
    model_id: str
    accession: str
    manuscript: bool
    replicate: int = 1

    @property
    def dirname(self) -> str:
        return f"{self.accession}__ms-{'on' if self.manuscript else 'off'}__r{self.replicate}"


@dataclass
class RunConfig:
    data_dir: Path
    outputs: Path
    pricing: dict
    validate_fn: Callable = validate
    generate_factory: Callable = make_generate
    plugin_dir: Path | None = None
    claude_bin: str = "claude"
    budget_tokens: int = 24000
    max_repairs: int = 2
    extra: dict = field(default_factory=dict)


def load_manifest(path: Path) -> list[dict]:
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def plan_runs(specs: list[ModelSpec], manifest: list[dict], replicates: dict[str, int] | None = None) -> list[RunKey]:
    replicates = replicates or {}
    return [RunKey(s.id, row["accession"], ms, r)
            for s in specs for row in manifest for ms in (True, False)
            for r in range(1, replicates.get(row["accession"], 1) + 1)]


def _write(run_dir: Path, sdrf: str | None, record: dict) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    if sdrf:
        (run_dir / "sdrf.tsv").write_text(sdrf)
    (run_dir / "usage.json").write_text(json.dumps(record, indent=1))
    return record


def execute_run(key: RunKey, spec: ModelSpec, cfg: RunConfig) -> dict:
    run_dir = Path(cfg.outputs) / spec.id / key.dirname
    if (run_dir / "usage.json").exists():
        return json.loads((run_dir / "usage.json").read_text())
    ev = load_evidence(cfg.data_dir, key.accession)
    templates = ev.meta.get("templates") or []
    base = {"model_id": spec.id, "provider": spec.provider, "model": spec.model, "arm": spec.arm,
            "context_window": spec.context_window, "flags": []}
    try:
        if spec.arm == "raw":
            messages, info = build_messages(ev, key.manuscript, cfg.budget_tokens)
            if spec.context_window and info["prompt_tokens"] + OUTPUT_RESERVE > spec.context_window:
                base["flags"].append("context_limited")
            res = run_raw(cfg.generate_factory(spec), messages, run_dir,
                          lambda p: cfg.validate_fn(p, templates), cfg.max_repairs)
            (run_dir / "transcript.json").write_text(json.dumps(res.transcript, indent=1))
            record = {**base, **info, "usage": res.usage, "turns": res.turns, "wall_s": res.wall_s,
                      "stop_reasons": res.stop_reasons, "cost_usd": cost_usd(cfg.pricing, spec.model, res.usage)}
            if "refusal" in res.stop_reasons:
                record["flags"].append("refusal")
            sdrf = res.sdrf
        else:
            res = skills_arm.run_skills(spec.model, evidence_dir(cfg.data_dir, key.accession), key.accession,
                                        key.manuscript, templates, run_dir, cfg.plugin_dir, cfg.claude_bin)
            record = {**base, "usage": res["usage"], "turns": res["num_turns"], "wall_s": res["wall_s"],
                      "cost_usd": res["cost_usd"], "returncode": res["returncode"]}
            if res["leak_suspect"]:
                record["flags"].append("leak_suspect")
            sdrf = res["sdrf"]
    except Exception as exc:  # a crashed run is a scored failure, not a crashed benchmark
        record = {**base, "usage": {}, "wall_s": 0.0, "cost_usd": None, "error": repr(exc),
                  "traceback": traceback.format_exc()}
        sdrf = None
    if not sdrf:
        record["flags"].append("failed")
    return _write(run_dir, sdrf, record)


def run_matrix(specs: list[ModelSpec], keys: list[RunKey], cfg: RunConfig, log=print) -> list[dict]:
    by_id = {s.id: s for s in specs}
    groups: dict[str, list[RunKey]] = {}
    for k in keys:
        groups.setdefault(by_id[k.model_id].provider, []).append(k)
    results: list[dict] = []

    def run_group(provider: str, group: list[RunKey]):
        with ThreadPoolExecutor(max_workers=WORKERS.get(provider, 1)) as pool:
            for rec, k in zip(pool.map(lambda k: execute_run(k, by_id[k.model_id], cfg), group), group):
                log(f"{k.model_id:22s} {k.dirname:32s} flags={rec.get('flags')}")
                results.append(rec)

    with ThreadPoolExecutor(max_workers=len(groups) or 1) as outer:
        list(outer.map(lambda item: run_group(*item), groups.items()))
    return results
```

```python
# file: src/sdrf_model_bench/scoring_run.py
"""Score every run directory under an outputs tree (ours or a collaborator's submission)."""

from __future__ import annotations

import json
from pathlib import Path

from sdrf_model_bench.score import score_deterministic
from sdrf_model_bench.validator import validity_score

JUDGE_WEIGHT = 0.2
CONTAMINATION_THRESHOLD = 80.0


def parse_dirname(name: str) -> tuple[str, bool, int]:
    acc, ms, rep = name.split("__")
    return acc, ms == "ms-on", int(rep.lstrip("r"))


def score_run(run_dir: Path, data_dir: Path, validate_fn, judge_fn=None) -> dict:
    acc, manuscript, rep = parse_dirname(run_dir.name)
    usage = json.loads((run_dir / "usage.json").read_text()) if (run_dir / "usage.json").exists() else {}
    meta = json.loads((Path(data_dir) / "evidence" / acc / "meta.json").read_text())
    truth = (Path(data_dir) / "truth" / f"{acc}.sdrf.tsv").read_text()
    sdrf_path = run_dir / "sdrf.tsv"
    pred = sdrf_path.read_text() if sdrf_path.exists() else ""
    validation = validate_fn(sdrf_path, meta.get("templates") or []) if pred else None
    det = score_deterministic(truth, pred, validity_score(validation) if validation else 0.0)
    judged = judge_fn(truth, pred) if (judge_fn and pred) else None
    judge_score = judged["judge"] if judged else None
    headline = det["deterministic"] if judge_score is None else (
        (1 - JUDGE_WEIGHT) * det["deterministic"] + JUDGE_WEIGHT * judge_score)
    flags = list(usage.get("flags", []))
    if not pred and "failed" not in flags:
        flags.append("failed")
    if not manuscript and meta.get("tier") == "poor" and det["deterministic"] >= CONTAMINATION_THRESHOLD:
        flags.append("contamination_suspect")
    record = {
        "model_id": usage.get("model_id", run_dir.parent.name), "arm": usage.get("arm", "raw"),
        "model": usage.get("model", ""), "provider": usage.get("provider", ""),
        "accession": acc, "manuscript": manuscript, "replicate": rep,
        "qtype": meta.get("qtype"), "tier": meta.get("tier"), "pride_quality": meta.get("pride_quality"),
        **{k: v for k, v in det.items()},
        "judge": judge_score, "judge_detail": judged and {k: judged[k] for k in
                                                          ("factor_fidelity", "design_fidelity", "free_text")},
        "judge_usage": judged and judged["usage"],
        "headline": round(headline, 2),
        "n_errors": len(validation.errors) if validation else None,
        "usage": usage.get("usage", {}), "cost_usd": usage.get("cost_usd"), "wall_s": usage.get("wall_s"),
        "flags": flags,
    }
    (run_dir / "score.json").write_text(json.dumps(record, indent=1))
    return record


def score_tree(outputs: Path, data_dir: Path, validate_fn, judge_fn=None, rescore: bool = False) -> list[dict]:
    records = []
    for run_dir in sorted(Path(outputs).glob("*/*__ms-*__r*")):
        cached = run_dir / "score.json"
        if cached.exists() and not rescore:
            records.append(json.loads(cached.read_text()))
        else:
            records.append(score_run(run_dir, data_dir, validate_fn, judge_fn))
    return records
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add run matrix execution and output scoring".

---

### Task 10: Report and slide

**Interfaces — Consumes:** score records. **Produces:** `summarise(records) -> list[dict]`
(one row per model_id: `arm, base, n, headline, headline_sem, deterministic, judge, tokens, cost_usd,
minutes, by_qtype{TMT,LFQ,DIA}, ms_delta, by_tier{rich,poor}, flags{...}`), `render_slide(summary, path)`,
`render_backups(records, summary, outdir)`.

Before writing the plotting code, load the `dataviz` skill and follow its palette/mark rules; the
code below is the structure it must fill.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_report.py
from sdrf_model_bench.report import render_backups, render_slide, summarise


def rec(model_id, arm, model, acc, ms, score, qtype="TMT", tier="rich", cost=0.1, wall=60, flags=()):
    return {"model_id": model_id, "arm": arm, "model": model, "accession": acc, "manuscript": ms,
            "qtype": qtype, "tier": tier, "headline": score, "deterministic": score, "judge": None,
            "validity": 1, "completeness": 1, "accuracy": score / 100, "specificity": 1,
            "usage": {"input_tokens": 1000, "output_tokens": 500}, "cost_usd": cost, "wall_s": wall,
            "flags": list(flags)}


RECORDS = [
    rec("m-raw", "raw", "m", "P1", True, 60), rec("m-raw", "raw", "m", "P1", False, 40),
    rec("m-skills", "skills", "m", "P1", True, 90), rec("m-skills", "skills", "m", "P1", False, 80),
    rec("local", "raw", "l", "P1", True, 20, cost=None, wall=600, flags=["context_limited"]),
    rec("local", "raw", "l", "P1", False, 10, cost=None, wall=600, flags=["failed"]),
]


def test_summarise():
    rows = {r["model_id"]: r for r in summarise(RECORDS)}
    assert rows["m-raw"]["headline"] == 50 and rows["m-raw"]["ms_delta"] == 20
    assert rows["m-skills"]["base"] == "m" and rows["local"]["cost_usd"] is None
    assert rows["local"]["minutes"] == 10 and rows["local"]["flags"]["failed"] == 1
    assert rows["m-raw"]["tokens"] == 1500


def test_render(tmp_path):
    summary = summarise(RECORDS)
    render_slide(summary, tmp_path / "slide")
    assert (tmp_path / "slide.svg").stat().st_size > 0 and (tmp_path / "slide.png").stat().st_size > 0
    render_backups(RECORDS, summary, tmp_path)
    assert (tmp_path / "backup_components.png").exists()
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `src/sdrf_model_bench/report.py` with:
  - `summarise`: group by `model_id`, compute means, and use SEM across datasets (average replicates and
    manuscript conditions per dataset first, so n is the number of datasets). `ms_delta` is the mean of
    the per-dataset paired differences (ms-on minus ms-off). Tokens are the mean of input + output + cache.
    `cost_usd` is None when every record's cost is None. `minutes` is mean `wall_s` / 60. `flags` is a
    Counter over all flags.
  - `render_slide`: a 16:9 figure with 3 axes (`gridspec` width ratios 3:1:1).
    - **Left** is a dumbbell chart with one row per `base` model, sorted by best score. It draws a raw dot, a
      skills dot, and a connecting line when both exist. The label on the right reads
      `"{score:.0f} · ${cost:.2f} · {tokens/1000:.0f}k tok"`, or `"{minutes:.1f} min"` for local models.
      A `⚠` marks rows whose context_limited or failed count is above zero.
    - **Middle** shows grouped bars for the best arm of each model by qtype.
    - **Right** shows the manuscript delta per model-arm.
    - The title is `"SDRF annotation quality by model"`. The subtitle names the largest skills uplift and
      `n` datasets. Save as `<path>.svg` and `<path>.png` (dpi 200).
  - `render_backups`: `backup_components.png` (stacked mean components per model_id),
    `backup_tier.png` (rich vs poor), `backup_judge_agreement.png` (scatter of deterministic vs judge, only when
    judge scores exist), and `summary.tsv`.

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — "Add summary and workshop slide rendering".

---

### Task 11: CLI, pack and hand-off docs

**Interfaces — Produces:** `sdrf-bench select|freeze|run|score|report|pack`.

- [ ] **Step 1: Write the failing test**

```python
# file: tests/test_cli.py
import tarfile

from sdrf_model_bench.cli import build_parser, pack


def test_parser_has_all_commands():
    p = build_parser()
    for cmd in ("select", "freeze", "run", "score", "report", "pack"):
        assert p.parse_args([cmd]).command == cmd


def test_pack_excludes_outputs(tmp_path):
    root = tmp_path / "bench"
    for rel in ("src/sdrf_model_bench/x.py", "data/manifest.tsv", "outputs/m/r/sdrf.tsv",
                "results/slide.png", "README.md", "models.yaml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x")
    out = pack(root, tmp_path / "pack.tar.gz")
    names = tarfile.open(out).getnames()
    assert any(n.endswith("data/manifest.tsv") for n in names)
    assert not any("/outputs/" in n or "/results/" in n for n in names)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `cli.py` with argparse subcommands:
  - `select --datasets <sdrf-annotated-datasets>/datasets --seed 20260918 --pool-per-type 12 --out data`:
    iterate candidates, shuffle per qtype (seeded), and exclude `made_with_ai`. Call
    `freeze_dataset` until `pool-per-type` datasets per type are frozen, compute tiers with
    `pick_balanced` on the frozen pool, delete the evidence of unpicked datasets, write
    `data/manifest.tsv` (accession, qtype, tier, pride_quality, organism, reason), and update each
    `meta.json` with `qtype`, `tier` and `templates`.
  - `freeze`: re-freeze the accessions listed in the manifest (to refresh evidence explicitly).
  - `run --models models.yaml --only <ids> --outputs <dir> --plugin-src <sdrf-skills> --replicates PXD:3,...`:
    build the sanitised plugin once (forbidden = manifest accessions), then `run_matrix`.
  - `score --outputs <dir> --judge-model claude-sonnet-5 [--no-judge] [--rescore]` → `results/runs.jsonl`.
  - `report --results results/runs.jsonl --out results/`.
  - `pack --out sdrf-model-bench-v1.tar.gz`: tar the package root without `outputs/`, `results/`,
    `.venv/`, `__pycache__`, `.pytest_cache`.
  - Write `README.md` (what it measures, quickstart for collaborators: install, `ollama`/API setup,
    `run --only`, `score`, `report`, and how to add a model), and `SUBMISSION.md` (the output contract
    above plus the rules: same prompt/evidence, no network, report usage honestly, and send the
    `outputs/<model_id>/` tree).

- [ ] **Step 4: Run** full suite `uv run --extra dev pytest -q` → PASS. **Step 5: Commit** — "Add CLI, pack command and hand-off docs".

---

### Task 12: Live smoke run (verification, not unit tests)

- [ ] Run `sdrf-bench select` against the real datasets. Check that the manifest has 12 rows, 4 per qtype
  with 2 rich and 2 poor each, and at least 3 non-human.
- [ ] Run `sdrf-bench run --only qwen2.5-3b-raw` on 1 dataset with ms-off. Check that `num_ctx` shows up
  in Ollama's log and that `usage.json` has non-zero tokens.
- [ ] Score the smoke run and render the report from it.
- [ ] Claude arms: need `ANTHROPIC_API_KEY`. Run one skills-arm run on the smallest dataset and inspect
  `transcript.jsonl` for skill invocation, confirm no `leak_suspect`, and check that `parse_sdrf` was called.
- [ ] Only then launch the full 216-run matrix.

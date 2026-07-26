# SDRF Harness — Phase 0 (Deterministic Spine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LLM-free deterministic pipeline that harvests candidate proteomics datasets, fetches their metadata, validates any deposited/assembled SDRF, and merges passing SDRFs to the corpus branch — coordinated through a shared SQLite work ledger.

**Architecture:** A queue-driven pipeline. A SQLite `ledger` is the single source of truth for each dataset's status; workers `claim` exclusively (leases with TTL). Per dataset: `fetcher` produces a cached metadata `Bundle`; if a deposited SDRF exists it is validated directly; the `validator` wraps `parse_sdrf` + structural checks as the hard gate; the `merger` commits passing SDRFs in batches. The `orchestrator` pulls claimed work through the stages. Every module is deterministic and unit-testable with fixtures.

**Tech Stack:** Python 3.11 (stdlib `sqlite3`, `dataclasses`, `pathlib`, `subprocess`), `pytest`, `requests` (HTTP), the existing `parse_sdrf` CLI (from `sdrf-pipelines`, already installed).

## Global Constraints

- Python 3.11+; standard library preferred; only third-party deps: `pytest`, `requests`.
- Package root: `sdrf-workspace/sdrf-harness/`; importable package name `sdrf_harness`.
- SDRF files: **never** write with pandas `to_csv` (duplicate-header corruption). Write raw tab-separated text lines.
- Vendor-native raw only: accept `.raw/.wiff/.d/.raw.gz/.wiff.gz`; a dataset whose MS files are only peak lists (`.mgf/.mzML/.mzXML/.ms2/.pkl`) is non-annotatable.
- Validation gate command: `parse_sdrf validate-sdrf --sdrf_file <f> -t ms-proteomics --use_ols_cache_only`.
- Corpus branch: `datasets/bulk-lfq-dia-small`; corpus repo path is injected (not hardcoded) as `corpus_dir`.
- No Claude/tool attribution in any commit message or file (public-repo hygiene).
- Tests must not hit the live network — use cached fixtures.

---

### Task 1: Package scaffold + core records

**Files:**
- Create: `sdrf-harness/pyproject.toml`
- Create: `sdrf-harness/src/sdrf_harness/__init__.py`
- Create: `sdrf-harness/src/sdrf_harness/models.py`
- Test: `sdrf-harness/tests/test_models.py`

**Interfaces:**
- Produces: `STATUSES` (frozenset of status strings); `Bundle` dataclass with fields `accession:str, repository:str, organisms:list[tuple[str,str]], instruments:list[str], files:list[dict], deposited_sdrf:str|None, labels:list[str], protocol:dict, gaps:list[str]`; `Bundle.to_json()/from_json()` round-trip; `Verdict` dataclass `passed:bool, errors:list[str], collisions:int, ragged:int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from sdrf_harness.models import Bundle, Verdict, STATUSES

def test_status_set_has_core_states():
    for s in ["candidate", "claimed", "ready", "escalate", "merged", "blocked"]:
        assert s in STATUSES

def test_bundle_json_roundtrip():
    b = Bundle(accession="PXD000001", repository="pride",
               organisms=[("Homo sapiens", "9606")], instruments=["Q Exactive"],
               files=[{"name": "a.raw", "ext": "raw"}], deposited_sdrf=None,
               labels=["control"], protocol={"enzyme": "Trypsin"}, gaps=["organism part"])
    assert Bundle.from_json(b.to_json()) == b

def test_verdict_defaults():
    v = Verdict(passed=True, errors=[], collisions=0, ragged=0)
    assert v.passed and v.collisions == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "sdrf-harness"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = ["requests"]
[project.optional-dependencies]
dev = ["pytest"]
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
[tool.setuptools.packages.find]
where = ["src"]
[tool.pytest.ini_options]
pythonpath = ["src"]
```

```python
# src/sdrf_harness/__init__.py
__version__ = "0.0.1"
```

```python
# src/sdrf_harness/models.py
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict

STATUSES = frozenset({
    "candidate", "claimed", "fetched", "drafted", "validated",
    "ready", "escalate", "merged", "blocked",
})

@dataclass
class Bundle:
    accession: str
    repository: str
    organisms: list = field(default_factory=list)      # list[tuple[name, taxid]]
    instruments: list = field(default_factory=list)
    files: list = field(default_factory=list)           # list[dict{name, ext, size?}]
    deposited_sdrf: str | None = None
    labels: list = field(default_factory=list)
    protocol: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Bundle":
        d = json.loads(s)
        d["organisms"] = [tuple(o) for o in d.get("organisms", [])]
        return cls(**d)

@dataclass
class Verdict:
    passed: bool
    errors: list = field(default_factory=list)
    collisions: int = 0
    ragged: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add pyproject.toml src/sdrf_harness/__init__.py src/sdrf_harness/models.py tests/test_models.py
git commit -m "feat: package scaffold + Bundle/Verdict/STATUSES records"
```

---

### Task 2: Ledger (SQLite state + atomic claims)

**Files:**
- Create: `sdrf-harness/src/sdrf_harness/ledger.py`
- Test: `sdrf-harness/tests/test_ledger.py`

**Interfaces:**
- Consumes: `STATUSES` from `models`.
- Produces: `Ledger(db_path)` with methods: `init_db()`; `add_candidates(rows: list[dict]) -> int` (dict keys `accession, repository, annotatability`; ignores duplicates); `claim(worker_id: str, n: int, lease_seconds: int, now: float) -> list[str]` (atomically moves the `n` highest-`annotatability` `candidate` rows to `claimed`, returns accessions); `set_status(accession, status, **fields)`; `get(accession) -> dict|None`; `reclaim_expired(now: float) -> int` (expired `claimed` leases → `candidate`); `counts() -> dict[str,int]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ledger.py
from sdrf_harness.ledger import Ledger

def test_claim_is_exclusive_and_ordered(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([
        {"accession": "PXD1", "repository": "pride", "annotatability": 0.9},
        {"accession": "PXD2", "repository": "pride", "annotatability": 0.5},
        {"accession": "PXD3", "repository": "massive", "annotatability": 0.7},
    ])
    got = lg.claim("w1", n=2, lease_seconds=600, now=1000.0)
    assert got == ["PXD1", "PXD3"]                       # highest annotatability first
    again = lg.claim("w2", n=2, lease_seconds=600, now=1000.0)
    assert again == ["PXD2"]                             # w1's claims are not re-handed
    assert lg.get("PXD1")["status"] == "claimed"
    assert lg.get("PXD1")["worker_id"] == "w1"

def test_add_candidates_ignores_duplicates(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    assert lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.5}]) == 1
    assert lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9}]) == 0

def test_reclaim_expired_lease(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.5}])
    lg.claim("w1", n=1, lease_seconds=600, now=1000.0)
    assert lg.reclaim_expired(now=1000.0 + 500) == 0     # not yet expired
    assert lg.reclaim_expired(now=1000.0 + 700) == 1     # expired -> back to candidate
    assert lg.get("PXD1")["status"] == "candidate"

def test_set_status_and_counts(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.5}])
    lg.set_status("PXD1", "blocked", block_reason="peak-list-only")
    assert lg.get("PXD1")["status"] == "blocked"
    assert lg.get("PXD1")["block_reason"] == "peak-list-only"
    assert lg.counts()["blocked"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/ledger.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from .models import STATUSES

_COLS = ["accession", "repository", "status", "annotatability", "worker_id",
         "lease_expires_at", "content_hash", "confidence", "route", "block_reason"]

class Ledger:
    def __init__(self, db_path):
        self.db_path = str(db_path)

    def _conn(self):
        c = sqlite3.connect(self.db_path, isolation_level=None)  # autocommit; explicit txns below
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS datasets(
                accession TEXT PRIMARY KEY, repository TEXT, status TEXT DEFAULT 'candidate',
                annotatability REAL DEFAULT 0, worker_id TEXT, lease_expires_at REAL,
                content_hash TEXT, confidence REAL, route TEXT, block_reason TEXT)""")

    def add_candidates(self, rows) -> int:
        n = 0
        with self._conn() as c:
            for r in rows:
                cur = c.execute(
                    "INSERT OR IGNORE INTO datasets(accession, repository, annotatability, status) "
                    "VALUES(?,?,?, 'candidate')",
                    (r["accession"], r["repository"], float(r.get("annotatability", 0))))
                n += cur.rowcount
        return n

    def claim(self, worker_id, n, lease_seconds, now) -> list:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute(
                "SELECT accession FROM datasets WHERE status='candidate' "
                "ORDER BY annotatability DESC, accession ASC LIMIT ?", (n,)).fetchall()
            accs = [r["accession"] for r in rows]
            for a in accs:
                c.execute("UPDATE datasets SET status='claimed', worker_id=?, lease_expires_at=? "
                          "WHERE accession=?", (worker_id, now + lease_seconds, a))
            c.execute("COMMIT")
        return accs

    def set_status(self, accession, status, **fields):
        assert status in STATUSES, status
        sets = ["status=?"]; vals = [status]
        for k, v in fields.items():
            assert k in _COLS, k
            sets.append(f"{k}=?"); vals.append(v)
        vals.append(accession)
        with self._conn() as c:
            c.execute(f"UPDATE datasets SET {', '.join(sets)} WHERE accession=?", vals)

    def get(self, accession):
        with self._conn() as c:
            r = c.execute("SELECT * FROM datasets WHERE accession=?", (accession,)).fetchone()
            return dict(r) if r else None

    def reclaim_expired(self, now) -> int:
        with self._conn() as c:
            cur = c.execute("UPDATE datasets SET status='candidate', worker_id=NULL, lease_expires_at=NULL "
                            "WHERE status='claimed' AND lease_expires_at < ?", (now,))
            return cur.rowcount

    def counts(self) -> dict:
        with self._conn() as c:
            return {r["status"]: r["n"] for r in
                    c.execute("SELECT status, COUNT(*) n FROM datasets GROUP BY status")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_ledger.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/ledger.py tests/test_ledger.py
git commit -m "feat: SQLite ledger with atomic claims and lease reclaim"
```

---

### Task 3: Validator (the hard gate)

**Files:**
- Create: `sdrf-harness/src/sdrf_harness/validator.py`
- Test: `sdrf-harness/tests/test_validator.py`
- Test fixtures: `sdrf-harness/tests/fixtures/good.sdrf.tsv`, `sdrf-harness/tests/fixtures/collide.sdrf.tsv`

**Interfaces:**
- Consumes: `Verdict` from `models`.
- Produces: `structural_check(sdrf_path) -> tuple[int ragged, int collisions]` (collisions on `(source name, biological replicate, technical replicate, fraction identifier)`); `validate(sdrf_path, templates=("ms-proteomics",), run_cli=True) -> Verdict`. When `run_cli` is False, only the structural check runs (network/CLI-free unit path).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validator.py
from pathlib import Path
from sdrf_harness.validator import structural_check, validate

FIX = Path(__file__).parent / "fixtures"

def test_structural_check_detects_ragged_and_collisions():
    ragged, collide = structural_check(FIX / "collide.sdrf.tsv")
    assert collide == 1        # two rows share source/biorep/techrep/fraction
    assert ragged == 0

def test_validate_structural_only_passes_good(tmp_path):
    v = validate(FIX / "good.sdrf.tsv", run_cli=False)
    assert v.passed and v.collisions == 0 and v.ragged == 0

def test_validate_structural_only_fails_collision():
    v = validate(FIX / "collide.sdrf.tsv", run_cli=False)
    assert not v.passed and v.collisions == 1
```

Fixture `tests/fixtures/good.sdrf.tsv` (tab-separated; two distinct fractions):
```
source name	characteristics[organism]	characteristics[biological replicate]	comment[fraction identifier]	comment[technical replicate]	comment[data file]
s1	NT=Homo sapiens;AC=NCBITaxon:9606	1	1	1	a.raw
s1	NT=Homo sapiens;AC=NCBITaxon:9606	1	2	1	b.raw
```

Fixture `tests/fixtures/collide.sdrf.tsv` (two identical coordinates):
```
source name	characteristics[organism]	characteristics[biological replicate]	comment[fraction identifier]	comment[technical replicate]	comment[data file]
s1	NT=Homo sapiens;AC=NCBITaxon:9606	1	1	1	a.raw
s1	NT=Homo sapiens;AC=NCBITaxon:9606	1	1	1	b.raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.validator'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/validator.py
from __future__ import annotations
import subprocess
from collections import Counter
from pathlib import Path
from .models import Verdict

def _col(header, name):
    return header.index(name) if name in header else None

def structural_check(sdrf_path):
    lines = Path(sdrf_path).read_text().splitlines()
    if not lines:
        return 0, 0
    h = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:] if ln.strip()]
    ragged = sum(1 for r in rows if len(r) != len(h))
    sn = 0
    bi, ti, fr = (_col(h, "characteristics[biological replicate]"),
                  _col(h, "comment[technical replicate]"),
                  _col(h, "comment[fraction identifier]"))
    collisions = 0
    if None not in (bi, ti, fr):
        key = Counter((r[sn], r[bi], r[ti], r[fr]) for r in rows if len(r) > max(bi, ti, fr))
        collisions = sum(1 for v in key.values() if v > 1)
    return ragged, collisions

def validate(sdrf_path, templates=("ms-proteomics",), run_cli=True) -> Verdict:
    ragged, collisions = structural_check(sdrf_path)
    errors = []
    if ragged:
        errors.append(f"{ragged} ragged rows")
    if collisions:
        errors.append(f"{collisions} coordinate collisions")
    if run_cli:
        cmd = ["parse_sdrf", "validate-sdrf", "--sdrf_file", str(sdrf_path)]
        for t in templates:
            cmd += ["-t", t]
        cmd += ["--use_ols_cache_only"]
        out = subprocess.run(cmd, capture_output=True, text=True)
        tail = (out.stdout + out.stderr).strip().splitlines()
        last = tail[-1] if tail else ""
        if "Well done" not in last and "only warnings" not in last:
            errors.append("parse_sdrf: " + last[:200])
    return Verdict(passed=not errors, errors=errors, collisions=collisions, ragged=ragged)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_validator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/validator.py tests/test_validator.py tests/fixtures/good.sdrf.tsv tests/fixtures/collide.sdrf.tsv
git commit -m "feat: validator with structural checks + parse_sdrf gate"
```

---

### Task 4: Fetcher (accession → cached Bundle)

**Files:**
- Create: `sdrf-harness/src/sdrf_harness/fetcher.py`
- Test: `sdrf-harness/tests/test_fetcher.py`
- Test fixture: `sdrf-harness/tests/fixtures/pride_PXDTEST.json`

**Interfaces:**
- Consumes: `Bundle` from `models`.
- Produces: `parse_pride_project(project_json: dict, files_json: list) -> Bundle` (pure; no network); `RAW_EXTS`/`PEAKLIST_EXTS` frozensets; `is_annotatable(bundle) -> tuple[bool, str]` (rejects peak-list-only, returns reason). Network fetching lives in `fetch_bundle(accession, repository, cache_dir, session=None)` but the parsing logic is isolated in `parse_pride_project` so tests need no network.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetcher.py
import json
from pathlib import Path
from sdrf_harness.fetcher import parse_pride_project, is_annotatable

FIX = Path(__file__).parent / "fixtures"

def test_parse_pride_project_extracts_core_fields():
    proj = json.load(open(FIX / "pride_PXDTEST.json"))
    b = parse_pride_project(proj, proj["_files"])
    assert b.accession == "PXDTEST"
    assert ("Homo sapiens", "9606") in b.organisms
    assert "Q Exactive" in b.instruments
    assert any(f["ext"] == "raw" for f in b.files)

def test_is_annotatable_rejects_peaklist_only():
    from sdrf_harness.models import Bundle
    b = Bundle(accession="X", repository="pride",
               files=[{"name": "a.mgf", "ext": "mgf"}, {"name": "b.mzML", "ext": "mzml"}])
    ok, reason = is_annotatable(b)
    assert not ok and "peak-list" in reason

def test_is_annotatable_accepts_raw():
    from sdrf_harness.models import Bundle
    b = Bundle(accession="X", repository="pride", organisms=[("Homo sapiens", "9606")],
               files=[{"name": "a.raw", "ext": "raw"}])
    ok, _ = is_annotatable(b)
    assert ok
```

Fixture `tests/fixtures/pride_PXDTEST.json`:
```json
{
  "accession": "PXDTEST",
  "title": "Test human proteome",
  "organisms": [{"name": "Homo sapiens", "accession": "9606"}],
  "instruments": [{"name": "Q Exactive"}],
  "_files": [{"fileName": "a.raw"}, {"fileName": "b.raw"}, {"fileName": "res.mzid"}]
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.fetcher'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/fetcher.py
from __future__ import annotations
import json, re
from pathlib import Path
from .models import Bundle

RAW_EXTS = frozenset({"raw", "wiff", "d", "raw.gz", "wiff.gz"})
PEAKLIST_EXTS = frozenset({"mgf", "mzml", "mzxml", "ms2", "pkl"})

def _ext(name: str) -> str:
    n = name.lower()
    for e in ("raw.gz", "wiff.gz"):
        if n.endswith("." + e):
            return e
    return n.rsplit(".", 1)[-1] if "." in n else ""

def parse_pride_project(project_json: dict, files_json: list) -> Bundle:
    orgs = [(o.get("name"), re.search(r"(\d+)", str(o.get("accession", ""))).group(1)
             if re.search(r"(\d+)", str(o.get("accession", ""))) else "")
            for o in (project_json.get("organisms") or [])]
    instr = [i.get("name") for i in (project_json.get("instruments") or []) if i.get("name")]
    files = [{"name": f.get("fileName", ""), "ext": _ext(f.get("fileName", ""))} for f in files_json]
    deposited = next((f["name"] for f in files if f["name"].lower().endswith(".sdrf.tsv")), None)
    return Bundle(accession=project_json.get("accession", ""), repository="pride",
                  organisms=orgs, instruments=instr, files=files, deposited_sdrf=deposited)

def is_annotatable(bundle: Bundle):
    exts = {f["ext"] for f in bundle.files}
    if exts & RAW_EXTS:
        return True, ""
    if exts & PEAKLIST_EXTS:
        return False, "peak-list-only deposit"
    return False, "no vendor-native raw files"

def fetch_bundle(accession, repository, cache_dir, session=None):
    """Network fetch (PRIDE v3). Caches raw JSON; delegates parsing to parse_pride_project."""
    import requests
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    s = session or requests.Session()
    base = f"https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{accession}"
    proj = s.get(base, timeout=60).json()
    files = s.get(base + "/files/all?pageSize=3000", timeout=120).json()
    files = files if isinstance(files, list) else files.get("_embedded", {}).get("files", [])
    (cache_dir / f"{accession}.project.json").write_text(json.dumps(proj))
    b = parse_pride_project(proj, files)
    (cache_dir / f"{accession}.bundle.json").write_text(b.to_json())
    return b
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_fetcher.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/fetcher.py tests/test_fetcher.py tests/fixtures/pride_PXDTEST.json
git commit -m "feat: fetcher — parse PRIDE project into Bundle + annotatability guard"
```

---

### Task 5: Harvester (annotatability scoring)

**Files:**
- Create: `sdrf-harness/src/sdrf_harness/harvester.py`
- Test: `sdrf-harness/tests/test_harvester.py`

**Interfaces:**
- Consumes: `Bundle` from `models`; `RAW_EXTS`/`PEAKLIST_EXTS`, `is_annotatable` from `fetcher`.
- Produces: `score_annotatability(bundle: Bundle) -> float` in [0,1]: 0.0 if not annotatable; else base 0.4, +0.3 if a deposited SDRF exists, +0.2 if single-organism, +0.1 if organism has a taxid. `to_candidate_row(bundle) -> dict` with keys `accession, repository, annotatability`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harvester.py
from sdrf_harness.models import Bundle
from sdrf_harness.harvester import score_annotatability, to_candidate_row

def _b(**kw):
    d = dict(accession="X", repository="pride", organisms=[("Homo sapiens", "9606")],
             files=[{"name": "a.raw", "ext": "raw"}], deposited_sdrf=None)
    d.update(kw); return Bundle(**d)

def test_peaklist_only_scores_zero():
    assert score_annotatability(_b(files=[{"name": "a.mgf", "ext": "mgf"}])) == 0.0

def test_deposited_sdrf_single_organism_scores_highest():
    s = score_annotatability(_b(deposited_sdrf="x.sdrf.tsv"))
    assert s == 0.4 + 0.3 + 0.2 + 0.1

def test_multi_organism_scores_lower_than_single():
    single = score_annotatability(_b())
    multi = score_annotatability(_b(organisms=[("Homo sapiens", "9606"), ("Mus musculus", "10090")]))
    assert multi < single

def test_to_candidate_row():
    row = to_candidate_row(_b())
    assert row["accession"] == "X" and row["repository"] == "pride" and 0 < row["annotatability"] <= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_harvester.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.harvester'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/harvester.py
from __future__ import annotations
from .models import Bundle
from .fetcher import is_annotatable

def score_annotatability(bundle: Bundle) -> float:
    ok, _ = is_annotatable(bundle)
    if not ok:
        return 0.0
    s = 0.4
    if bundle.deposited_sdrf:
        s += 0.3
    if len(bundle.organisms) == 1:
        s += 0.2
    if bundle.organisms and bundle.organisms[0][1]:
        s += 0.1
    return round(min(s, 1.0), 3)

def to_candidate_row(bundle: Bundle) -> dict:
    return {"accession": bundle.accession, "repository": bundle.repository,
            "annotatability": score_annotatability(bundle)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_harvester.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/harvester.py tests/test_harvester.py
git commit -m "feat: harvester annotatability scoring + candidate rows"
```

---

### Task 6: Merger (write SDRF + batched commit)

**Files:**
- Create: `sdrf-harness/src/sdrf_harness/merger.py`
- Test: `sdrf-harness/tests/test_merger.py`

**Interfaces:**
- Produces: `stage_sdrf(corpus_dir, accession, sdrf_text) -> Path` (writes `datasets/<accession>/<accession>.sdrf.tsv`, refusing to overwrite an existing file, returns the path); `commit_batch(corpus_dir, paths, message) -> str` (git add the given paths + commit, returns commit sha). Uses `subprocess` git; author is injected via env, never hardcoded.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merger.py
import subprocess
from pathlib import Path
import pytest
from sdrf_harness.merger import stage_sdrf, commit_batch

def _git(d, *a): subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)

def _repo(tmp_path):
    d = tmp_path / "corpus"; (d / "datasets").mkdir(parents=True)
    _git(d, "init", "-q"); _git(d, "config", "user.email", "t@t"); _git(d, "config", "user.name", "t")
    (d / "README.md").write_text("x"); _git(d, "add", "."); _git(d, "commit", "-qm", "init")
    return d

def test_stage_writes_and_refuses_overwrite(tmp_path):
    d = _repo(tmp_path)
    p = stage_sdrf(d, "PXD1", "source name\ta.raw\n")
    assert p.read_text().startswith("source name")
    with pytest.raises(FileExistsError):
        stage_sdrf(d, "PXD1", "other")

def test_commit_batch_returns_sha(tmp_path):
    d = _repo(tmp_path)
    p = stage_sdrf(d, "PXD1", "source name\ta.raw\n")
    sha = commit_batch(d, [p], "add PXD1")
    assert len(sha) >= 7
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=d, capture_output=True, text=True).stdout
    assert "add PXD1" in log
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_merger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.merger'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/merger.py
from __future__ import annotations
import subprocess
from pathlib import Path

def stage_sdrf(corpus_dir, accession, sdrf_text) -> Path:
    d = Path(corpus_dir) / "datasets" / accession
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{accession}.sdrf.tsv"
    if p.exists():
        raise FileExistsError(str(p))
    p.write_text(sdrf_text)
    return p

def commit_batch(corpus_dir, paths, message) -> str:
    corpus_dir = Path(corpus_dir)
    rel = [str(Path(p).relative_to(corpus_dir)) for p in paths]
    subprocess.run(["git", "add", *rel], cwd=corpus_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=corpus_dir, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=corpus_dir,
                         capture_output=True, text=True).stdout.strip()
    return sha
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_merger.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/merger.py tests/test_merger.py
git commit -m "feat: merger — stage SDRF (no overwrite) + batched git commit"
```

---

### Task 7: Orchestrator (wire the deposited-SDRF spine)

**Files:**
- Create: `sdrf-harness/src/sdrf_harness/orchestrator.py`
- Test: `sdrf-harness/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Ledger`, `validate` (validator), `stage_sdrf`+`commit_batch` (merger).
- Produces: `process_ready_sdrf(ledger, accession, sdrf_text, corpus_dir, run_cli=True) -> str` — validates `sdrf_text`; on pass, stages + commits it and sets ledger status `merged` (returns `"merged"`); on fail, sets status `escalate` with `block_reason` (returns `"escalate"`). This is the deterministic deposited-SDRF path; Phase 1 adds the assemble+draft branch.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import subprocess
from pathlib import Path
from sdrf_harness.ledger import Ledger
from sdrf_harness.orchestrator import process_ready_sdrf

GOOD = ("source name\tcharacteristics[organism]\tcharacteristics[biological replicate]\t"
        "comment[fraction identifier]\tcomment[technical replicate]\tcomment[data file]\n"
        "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\ta.raw\n"
        "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t2\t1\tb.raw\n")
COLLIDE = GOOD.replace("1\t2\t1\tb.raw", "1\t1\t1\tb.raw")

def _repo(tmp_path):
    d = tmp_path / "corpus"; (d / "datasets").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
    (d / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True, capture_output=True)
    return d

def test_good_sdrf_merges(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9}])
    r = process_ready_sdrf(lg, "PXD1", GOOD, d, run_cli=False)
    assert r == "merged"
    assert lg.get("PXD1")["status"] == "merged"
    assert (d / "datasets" / "PXD1" / "PXD1.sdrf.tsv").exists()

def test_collision_sdrf_escalates(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD2", "repository": "pride", "annotatability": 0.9}])
    r = process_ready_sdrf(lg, "PXD2", COLLIDE, d, run_cli=False)
    assert r == "escalate"
    assert lg.get("PXD2")["status"] == "escalate"
    assert not (d / "datasets" / "PXD2").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.orchestrator'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/orchestrator.py
from __future__ import annotations
import tempfile
from pathlib import Path
from .validator import validate
from .merger import stage_sdrf, commit_batch

def process_ready_sdrf(ledger, accession, sdrf_text, corpus_dir, run_cli=True) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".sdrf.tsv", delete=False) as tf:
        tf.write(sdrf_text); tmp = tf.name
    try:
        verdict = validate(tmp, run_cli=run_cli)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if not verdict.passed:
        ledger.set_status(accession, "escalate", block_reason="; ".join(verdict.errors)[:200])
        return "escalate"
    p = stage_sdrf(corpus_dir, accession, sdrf_text)
    commit_batch(corpus_dir, [p], f"Add {accession} SDRF")
    ledger.set_status(accession, "merged")
    return "merged"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator — deposited-SDRF validate/merge/escalate path"
```

---

## Phase 0 exit criteria

- `python -m pytest` green across all seven modules.
- End-to-end on one real deposited-SDRF dataset (manual, network-on): harvester scores it, fetcher pulls it, orchestrator validates + merges to a scratch clone of the corpus branch.
- Ready to layer Phase 1 (`assembler` for datasets lacking a deposited SDRF, then `drafter`/`grounder`/`router`).

## Deferred to later phases (not in this plan)

`cvmaps` + `assembler` (technical columns for no-deposited-SDRF datasets), `drafter` (local LLM), `grounder`, `router`, `refiner` (Claude), `feedback`, live MassIVE harvest source, the golden-set regression harness. Each becomes its own plan.

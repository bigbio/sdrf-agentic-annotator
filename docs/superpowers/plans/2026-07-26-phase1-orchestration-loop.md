# SDRF Harness — Phase 1 (Orchestration Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the harness *run* end-to-end on deposited-SDRF datasets: harvest candidates into the ledger, then loop claim → fetch → validate → merge/escalate with lease reclaim, exposed as a `run` CLI. The local-LLM drafter is stubbed as the escalation path (Phase 1b, needs the GPU model server).

**Architecture:** Dependency-injected fetch functions keep the loop unit-testable without network. `harvest_accessions` populates the ledger from a fetch function; `run_loop` pulls claimed work through fetch → (deposited-SDRF ? process : escalate); `run.py` wires the real fetchers. Builds on Phase 0/0.5 (`ledger`, `fetcher`, `harvester`, `orchestrator.process_ready_sdrf`, `validator`).

**Tech Stack:** Python 3.11 stdlib + `requests` (network, isolated), `pytest`.

## Global Constraints

- Package `sdrf_harness` under `src/`; Python 3.11+.
- Every network function takes an injectable dependency (a `fetch`/`session` callable) so unit tests pass fakes — no network in tests.
- Reuse existing signatures verbatim: `Ledger.add_candidates/claim/set_status/get/reclaim_expired`, `harvester.to_candidate_row`, `orchestrator.process_ready_sdrf(ledger, accession, sdrf_text, corpus_dir, run_cli)`, `fetcher.Bundle`/`is_annotatable`.
- No Claude/tool attribution in commits.
- Tests must not hit network.

---

### Task 1: `fetch_deposited_sdrf` (download an author-deposited SDRF)

**Files:**
- Modify: `src/sdrf_harness/fetcher.py`
- Test: `tests/test_fetch_deposited.py`

**Interfaces:**
- Produces: `deposited_sdrf_url(accession, ym, filename) -> str` (pure; builds `https://ftp.pride.ebi.ac.uk/pride/data/archive/{ym}/{accession}/{filename}` where `ym` is `YYYY/MM`); `fetch_deposited_sdrf(bundle, ym, session=None) -> str|None` — returns the SDRF text if `bundle.deposited_sdrf` is set (GET via `session`), else `None`. Network isolated in `fetch_deposited_sdrf`; the URL builder is pure and tested.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_deposited.py
from sdrf_harness.fetcher import deposited_sdrf_url, fetch_deposited_sdrf
from sdrf_harness.models import Bundle

def test_url_builder():
    u = deposited_sdrf_url("PXD000001", "2014/01", "PXD000001.sdrf.tsv")
    assert u == "https://ftp.pride.ebi.ac.uk/pride/data/archive/2014/01/PXD000001/PXD000001.sdrf.tsv"

class _Sess:
    def __init__(self, text): self._t = text; self.url = None
    def get(self, url, timeout=0):
        self.url = url
        class R:
            def __init__(s, t): s.text = t
        return R(self._t)

def test_fetch_returns_none_without_deposited():
    b = Bundle(accession="X", repository="pride", deposited_sdrf=None)
    assert fetch_deposited_sdrf(b, "2020/01", session=_Sess("x")) is None

def test_fetch_downloads_when_present():
    b = Bundle(accession="PXD1", repository="pride", deposited_sdrf="PXD1.sdrf.tsv")
    s = _Sess("source name\ta.raw\n")
    txt = fetch_deposited_sdrf(b, "2020/01", session=s)
    assert txt.startswith("source name")
    assert s.url.endswith("/2020/01/PXD1/PXD1.sdrf.tsv")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_fetch_deposited.py -v`
Expected: FAIL with `ImportError: cannot import name 'deposited_sdrf_url'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/sdrf_harness/fetcher.py`:

```python
def deposited_sdrf_url(accession, ym, filename) -> str:
    return f"https://ftp.pride.ebi.ac.uk/pride/data/archive/{ym}/{accession}/{filename}"

def fetch_deposited_sdrf(bundle, ym, session=None):
    if not bundle.deposited_sdrf:
        return None
    if session is None:
        import requests
        session = requests.Session()
    url = deposited_sdrf_url(bundle.accession, ym, bundle.deposited_sdrf)
    return session.get(url, timeout=120).text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_fetch_deposited.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/fetcher.py tests/test_fetch_deposited.py
git commit -m "feat: fetch_deposited_sdrf — download an author-deposited SDRF"
```

---

### Task 2: `harvest_accessions` (populate the ledger)

**Files:**
- Modify: `src/sdrf_harness/harvester.py`
- Test: `tests/test_harvest_accessions.py`

**Interfaces:**
- Consumes: `to_candidate_row` (harvester), `Ledger.add_candidates`.
- Produces: `harvest_accessions(ledger, accessions, fetch_bundle) -> int` — for each accession, call `fetch_bundle(accession)` (injected) → `to_candidate_row(bundle)` → collect → `ledger.add_candidates(rows)`; returns number of new rows inserted. A `fetch_bundle` that raises for one accession is skipped (that accession is not added), not fatal.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harvest_accessions.py
from sdrf_harness.ledger import Ledger
from sdrf_harness.harvester import harvest_accessions
from sdrf_harness.models import Bundle

def _fetch(acc):
    if acc == "BOOM":
        raise RuntimeError("network")
    return Bundle(accession=acc, repository="pride", organisms=[("Homo sapiens", "9606")],
                  files=[{"name": "a.raw", "ext": "raw"}], deposited_sdrf="x.sdrf.tsv")

def test_harvest_adds_candidates_and_skips_failures(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    n = harvest_accessions(lg, ["PXD1", "PXD2", "BOOM"], _fetch)
    assert n == 2
    assert lg.get("PXD1")["status"] == "candidate"
    assert lg.get("BOOM") is None
    assert lg.get("PXD1")["annotatability"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_harvest_accessions.py -v`
Expected: FAIL with `ImportError: cannot import name 'harvest_accessions'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/sdrf_harness/harvester.py`:

```python
def harvest_accessions(ledger, accessions, fetch_bundle) -> int:
    rows = []
    for acc in accessions:
        try:
            b = fetch_bundle(acc)
        except Exception:
            continue
        rows.append(to_candidate_row(b))
    return ledger.add_candidates(rows) if rows else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_harvest_accessions.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/harvester.py tests/test_harvest_accessions.py
git commit -m "feat: harvest_accessions — build candidate rows into the ledger"
```

---

### Task 3: `run_loop` (claim → fetch → process/escalate)

**Files:**
- Modify: `src/sdrf_harness/orchestrator.py`
- Test: `tests/test_run_loop.py`

**Interfaces:**
- Consumes: `Ledger.claim/reclaim_expired/set_status`, `process_ready_sdrf`.
- Produces: `run_loop(ledger, corpus_dir, worker_id, max_n, get_sdrf_text, now, lease_seconds=1800, run_cli=False) -> dict` — first `reclaim_expired(now)`, then `claim(worker_id, max_n, lease_seconds, now)`; for each claimed accession call `get_sdrf_text(accession)` (injected; returns the deposited SDRF text or `None`); if text is not None call `process_ready_sdrf(ledger, accession, text, corpus_dir, run_cli)`; if None set status `escalate` with `block_reason="no deposited SDRF (needs drafter)"`. Returns `{"claimed": n, "merged": a, "escalate": b}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_loop.py
import subprocess
from sdrf_harness.ledger import Ledger
from sdrf_harness.orchestrator import run_loop

GOOD = ("source name\tcharacteristics[organism]\tcharacteristics[biological replicate]\t"
        "comment[technical replicate]\tcomment[fraction identifier]\tcomment[data file]\n"
        "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\ta.raw\n")

def _repo(tmp_path):
    d = tmp_path / "corpus"; (d / "datasets").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
    (d / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True, capture_output=True)
    return d

def test_run_loop_merges_deposited_and_escalates_missing(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9},
                       {"accession": "PXD2", "repository": "pride", "annotatability": 0.8}])
    texts = {"PXD1": GOOD, "PXD2": None}
    res = run_loop(lg, d, "w1", max_n=10, get_sdrf_text=lambda a: texts[a], now=1000.0, run_cli=False)
    assert res == {"claimed": 2, "merged": 1, "escalate": 1}
    assert lg.get("PXD1")["status"] == "merged"
    assert lg.get("PXD2")["status"] == "escalate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_run_loop.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_loop'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/sdrf_harness/orchestrator.py`:

```python
def run_loop(ledger, corpus_dir, worker_id, max_n, get_sdrf_text, now,
             lease_seconds=1800, run_cli=False) -> dict:
    ledger.reclaim_expired(now)
    claimed = ledger.claim(worker_id, max_n, lease_seconds, now)
    merged = escalate = 0
    for acc in claimed:
        text = get_sdrf_text(acc)
        if text is None:
            ledger.set_status(acc, "escalate", block_reason="no deposited SDRF (needs drafter)")
            escalate += 1
            continue
        if process_ready_sdrf(ledger, acc, text, corpus_dir, run_cli=run_cli) == "merged":
            merged += 1
        else:
            escalate += 1
    return {"claimed": len(claimed), "merged": merged, "escalate": escalate}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_run_loop.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/orchestrator.py tests/test_run_loop.py
git commit -m "feat: run_loop — reclaim + claim + process/escalate over the ledger"
```

---

### Task 4: `run` CLI (wire real fetchers)

**Files:**
- Create: `src/sdrf_harness/run.py`
- Test: `tests/test_run_cli.py`

**Interfaces:**
- Consumes: `Ledger`, `harvest_accessions`, `run_loop`, `fetch_bundle`, `fetch_deposited_sdrf` (+ a helper to get `ym` from the project date).
- Produces: `build_get_sdrf_text(cache_dir) -> callable` — returns a function `accession -> str|None` that loads the cached bundle (written by `fetch_bundle`) and fetches its deposited SDRF (real network); `main(argv=None) -> int` CLI: `python -m sdrf_harness.run --accessions-file F --corpus DIR --db D --worker W [--max N]` — reads accessions, `harvest_accessions` (with real `fetch_bundle`), then `run_loop`, prints the result dict. Only `build_get_sdrf_text`'s pure parts and `main`'s arg parsing are unit-tested; the networked closure body is not.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_cli.py
from sdrf_harness.run import parse_args

def test_parse_args_defaults():
    ns = parse_args(["--accessions-file", "a.txt", "--corpus", "/c", "--db", "l.db", "--worker", "w1"])
    assert ns.accessions_file == "a.txt" and ns.corpus == "/c" and ns.worker == "w1" and ns.max == 25

def test_parse_args_max_override():
    ns = parse_args(["--accessions-file", "a.txt", "--corpus", "/c", "--db", "l.db",
                     "--worker", "w1", "--max", "5"])
    assert ns.max == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sdrf-harness && python -m pytest tests/test_run_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sdrf_harness.run'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sdrf_harness/run.py
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .ledger import Ledger
from .harvester import harvest_accessions
from .orchestrator import run_loop
from .fetcher import fetch_bundle, fetch_deposited_sdrf, Bundle

def parse_args(argv):
    p = argparse.ArgumentParser(prog="sdrf_harness.run")
    p.add_argument("--accessions-file", required=True)
    p.add_argument("--corpus", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--worker", required=True)
    p.add_argument("--max", type=int, default=25)
    return p.parse_args(argv)

def build_get_sdrf_text(cache_dir):
    def _get(accession):
        bpath = Path(cache_dir) / f"{accession}.bundle.json"
        if not bpath.exists():
            return None
        b = Bundle.from_json(bpath.read_text())
        ppath = Path(cache_dir) / f"{accession}.project.json"
        ym = "2020/01"
        if ppath.exists():
            import re
            m = re.search(r'"publicationDate"\s*:\s*"(\d{4})-(\d{2})', ppath.read_text())
            if m:
                ym = f"{m.group(1)}/{m.group(2)}"
        return fetch_deposited_sdrf(b, ym)
    return _get

def main(argv=None) -> int:
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    cache_dir = Path(ns.db).parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lg = Ledger(ns.db); lg.init_db()
    accs = [l.strip() for l in Path(ns.accessions_file).read_text().splitlines() if l.strip()]
    added = harvest_accessions(lg, accs, lambda a: fetch_bundle(a, "pride", cache_dir))
    import time
    res = run_loop(lg, ns.corpus, ns.worker, ns.max,
                   get_sdrf_text=build_get_sdrf_text(cache_dir), now=time.time(), run_cli=True)
    print(json.dumps({"harvested": added, **res}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sdrf-harness && python -m pytest tests/test_run_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd sdrf-harness
git add src/sdrf_harness/run.py tests/test_run_cli.py
git commit -m "feat: run CLI — harvest accessions then run the orchestration loop"
```

---

## Exit criteria

- `python -m pytest` green (adds ~7 tests).
- Smoke: `python -m sdrf_harness.run --accessions-file <file-of-deposited-SDRF-PXDs> --corpus <scratch-clone> --db /tmp/l.db --worker w1 --max 3` harvests, merges the deposited-SDRF datasets that pass, escalates the rest — the harness running end-to-end with no LLM.

## Deferred: Phase 1b (needs the GPU model server)

`drafter/` (local-LLM sample-map + characteristics from filenames/labels), `grounder/` (verify proposed terms), and wiring the drafter as the `escalate` handler in `run_loop`. Build once the served model endpoint is available; the loop already has the escalation seam.

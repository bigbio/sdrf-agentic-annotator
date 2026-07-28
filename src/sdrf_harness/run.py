from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .fetcher import Bundle, fetch_bundle, fetch_deposited_sdrf
from .harvester import harvest_accessions
from .ledger import Ledger
from .normalizer import normalize_sdrf
from .orchestrator import run_loop


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
        text = fetch_deposited_sdrf(b)
        return normalize_sdrf(text, b.acquisition) if text is not None else None

    return _get


def main(argv=None) -> int:
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    cache_dir = Path(ns.db).parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lg = Ledger(ns.db)
    lg.init_db()
    accs = [l.strip() for l in Path(ns.accessions_file).read_text().splitlines() if l.strip()]
    added = harvest_accessions(lg, accs, lambda a: fetch_bundle(a, "pride", cache_dir))
    import time

    res = run_loop(
        lg,
        ns.corpus,
        ns.worker,
        ns.max,
        get_sdrf_text=build_get_sdrf_text(cache_dir),
        now=time.time(),
        run_cli=True,
    )
    print(json.dumps({"harvested": added, **res}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

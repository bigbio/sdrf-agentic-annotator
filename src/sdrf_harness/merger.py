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
                         capture_output=True, text=True, check=True).stdout.strip()
    return sha

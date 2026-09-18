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

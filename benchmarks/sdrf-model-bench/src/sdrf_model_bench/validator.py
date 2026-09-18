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

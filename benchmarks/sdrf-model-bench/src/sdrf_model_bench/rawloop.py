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

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
    deposited_sdrf_url: str | None = None
    acquisition: str = "DDA"
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

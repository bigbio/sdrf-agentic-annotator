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

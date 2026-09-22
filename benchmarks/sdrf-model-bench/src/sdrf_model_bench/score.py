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


#: What a model that never opens the evidence would still write: the commonest value in proteomics.
#: comment[label] is deliberately absent -- it carries the row identity the aligner needs, so
#: overwriting it would measure a broken alignment rather than an uninformed annotation.
PRIOR_VALUES = {
    "characteristics[organism]": "Homo sapiens",
    "characteristics[organism part]": "not available",
    "characteristics[cell type]": "not available",
    "characteristics[disease]": "not available",
    "comment[instrument]": "NT=Q Exactive;AC=MS:1001911",
    "comment[cleavage agent details]": "NT=Trypsin;AC=MS:1001251",
    "comment[modification parameters]": "NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed",
    "comment[precursor mass tolerance]": "10 ppm",
    "comment[fragment mass tolerance]": "0.02 Da",
    "comment[technical replicate]": "1",
    "comment[fraction identifier]": "1",
}


def ignorant_baseline(truth_text: str) -> float:
    """Score of a file with the right shape and nothing learned from the evidence.

    Structure and validity are granted outright, so this is generous: it is the score a model
    earns from priors alone. The gap between it and 100 is the benchmark's usable range, and a
    configuration below it is not reading the evidence at all.
    """
    lines = [line.split("\t") for line in truth_text.strip().split("\n")]
    header = lines[0]
    pred = [header]
    for row in lines[1:]:
        row = list(row) + [""] * (len(header) - len(row))
        pred.append([PRIOR_VALUES.get(h.strip(), row[i]) for i, h in enumerate(header)])
    text = "\n".join("\t".join(r) for r in pred) + "\n"
    return score_deterministic(truth_text, text, validity=1.0)["deterministic"]


def baseline_for_data(data_dir) -> float | None:
    """Mean ignorant baseline over a frozen pack's reference files, or None if there are none."""
    from pathlib import Path
    refs = sorted(Path(data_dir).glob("truth/*.reference.tsv"))
    scores = [ignorant_baseline(p.read_text()) for p in refs]
    return sum(scores) / len(scores) if scores else None

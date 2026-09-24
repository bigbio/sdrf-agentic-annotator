"""Deterministic comparison of a predicted SDRF against a curated reference."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sdrf_model_bench.sdrf_io import (
    column_values,
    first_value,
    is_na,
    parse_kv,
    parse_term,
    read_sdrf,
)

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
TOL_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-z]+)\s*$", re.IGNORECASE)
#: an ontology accession is PREFIX:id; 'AC=1001251' or 'AC=4' in a curated file is a reference defect
ACCESSION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*:[A-Za-z0-9_.-]+$")
#: one reporter channel (a row identity), as opposed to a plex name such as TMT10 or TMT11plex
CHANNEL_RE = re.compile(r"^(tmt1(2[6-9]|3[0-5])[nc]?|itraq1(1[3-9]|2[01])|silac (light|medium|heavy))$", re.IGNORECASE)
PLEX_NAME_RE = re.compile(r"^(tmt|itraq)\s*\d*\s*-?\s*(plex)?$", re.IGNORECASE)
SAMPLE_LEVEL = {f for f in KEY_FIELDS if f.startswith("characteristics[")}


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


def is_channel(label: str) -> bool:
    return bool(CHANNEL_RE.match(parse_term(label or "")[0]))


def is_plex_name(label: str) -> bool:
    return bool(PLEX_NAME_RE.match(parse_term(label or "")[0]))


def accession_malformed(acc: str) -> bool:
    return bool(acc) and not ACCESSION_RE.match(acc)


def classify_cell(field: str, truth: str | None, pred: str | None) -> tuple[float | None, str]:
    """(agreement, triage class) for one cell. Classes follow bigbio/sdrf-skills PR #24, decided by rule:

    match / style / accession_conflict / run_wrong / curated_richer count as usual (style is a correct
    term with the accession present on only one side and is NOT penalised); curated_wrong credits the
    run when the reference cell is malformed and the labels agree; curated_unscorable and run_richer
    are excluded from accuracy (None) - the first cannot be judged offline, the second cannot be told
    from a hallucination offline."""
    truth, pred = truth or "", pred or ""
    if is_na(truth):
        return (None, "match" if is_na(pred) else "run_richer")
    if is_na(pred):
        return (0.0, "curated_richer")
    if field in EXACT_FIELDS:
        return (1.0, "match") if truth.strip().lower() == pred.strip().lower() else (0.0, "run_wrong")
    if field in TOLERANCE_FIELDS:
        tm, pm = TOL_RE.match(truth), TOL_RE.match(pred)
        if tm and pm and tm.group(2).lower() != pm.group(2).lower():
            return (None, "curated_unscorable")  # ppm vs Da: not convertible without m/z
        a = tolerance_agreement(truth, pred)
        return (a, "match" if a == 1.0 else "run_wrong")
    t_label, t_acc = parse_term(truth)
    p_label, p_acc = parse_term(pred)
    if accession_malformed(t_acc):
        return (1.0, "curated_wrong") if t_label and t_label == p_label else (None, "curated_unscorable")
    if t_acc and p_acc and t_acc == p_acc:
        return (1.0, "match")
    if t_label and t_label == p_label:
        if t_acc and p_acc:
            return (0.5, "accession_conflict")
        return (1.0, "style" if bool(t_acc) != bool(p_acc) else "match")
    return (0.0, "run_wrong")


def term_agreement(truth: str, pred: str) -> float:
    a, _ = classify_cell("characteristics[term]", truth, pred)
    return 0.0 if a is None else a


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


def is_collapsed_plex_reference(t_header, t_rows) -> bool:
    """A curated file that names the plex (TMT10, NT=TMT11plex) instead of the channel: one row per
    run where there should be one per channel. Found in PXD026581 and PXD036580."""
    labels = [first_value(t_header, r, "comment[label]") or "" for r in t_rows]
    return any(is_plex_name(x) for x in labels) and not any(is_channel(x) for x in labels)


def align_rows(t_header, t_rows, p_header, p_rows) -> list[tuple[list[str], list[str]]]:
    # a multiplexed or SILAC reference identifies a row by (file, channel); a collapsed-plex one cannot
    use_label = (any(is_channel(first_value(t_header, r, "comment[label]") or "") for r in t_rows)
                 and not is_collapsed_plex_reference(t_header, t_rows))
    truth, pred = _row_keys(t_header, t_rows, use_label), _row_keys(p_header, p_rows, use_label)
    pairs = []
    for key, t_list in truth.items():
        pairs.extend(zip(t_list, pred.get(key, [])))
    return pairs


def _cell_agreement(field: str, truth_row, t_header, pred_row, p_header) -> tuple[float | None, str]:
    if field == MOD_FIELD:
        t_cells = column_values(t_header, truth_row, field)
        p_cells = column_values(p_header, pred_row, field)
        if all(is_na(c) for c in t_cells):
            return (None, "run_richer" if any(not is_na(c) for c in p_cells) else "match")
        a = mods_agreement(t_cells, p_cells)
        return (a, "match" if a == 1.0 else ("curated_richer" if all(is_na(c) for c in p_cells) else "run_wrong"))
    return classify_cell(field, first_value(t_header, truth_row, field), first_value(p_header, pred_row, field))


def _explicit_na(field: str, pred_row, p_header) -> bool:
    vals = column_values(p_header, pred_row, field)
    return bool(vals) and all(v.strip().lower() in ("not available", "not applicable") for v in vals)


def accession_report(pred_text: str, resolver=None) -> dict[str, int]:
    """Every accession the prediction carries: malformed (no PREFIX:id - provably wrong offline),
    verified (resolver says so), or unverified (no resolver, or not in its cache: unknown, not wrong)."""
    _, rows = read_sdrf(pred_text) if pred_text.strip() else ([], [])
    rep = {"total": 0, "verified": 0, "unverified": 0, "malformed": 0}
    for row in rows:
        for cell in row:
            acc = parse_kv(cell).get("AC", "").upper().replace("_", ":") if ("AC=" in cell.upper()) else ""
            if not acc:
                continue
            rep["total"] += 1
            if accession_malformed(acc):
                rep["malformed"] += 1
            elif resolver is not None and resolver(acc):
                rep["verified"] += 1
            else:
                rep["unverified"] += 1
    return rep


def template_self_declared(pred_text: str) -> bool:
    header, rows = read_sdrf(pred_text) if pred_text.strip() else ([], [])
    return any(v.strip().upper().startswith("NT=") for r in rows for v in column_values(header, r, "comment[sdrf template]"))


def score_deterministic(truth_text: str, pred_text: str, validity: float, resolver=None) -> dict:
    t_header, t_rows = read_sdrf(truth_text)
    p_header, p_rows = read_sdrf(pred_text)
    pairs = align_rows(t_header, t_rows, p_header, p_rows) if p_rows else []
    defects: list[str] = []
    fields = list(KEY_FIELDS)
    if is_collapsed_plex_reference(t_header, t_rows):
        defects.append("collapsed_plex")
        fields = [f for f in fields if f not in SAMPLE_LEVEL]  # sample-level cells are unknowable per channel

    t_cols = Counter(h for h in t_header if h not in INFRA_COLUMNS)
    p_cols = Counter(p_header)
    col_share = sum(min(n, p_cols[c]) for c, n in t_cols.items()) / max(1, sum(t_cols.values()))
    row_share = len(pairs) / max(1, len(t_rows))
    completeness = col_share * row_share if p_rows else 0.0

    per_field: dict[str, list[float]] = defaultdict(list)
    triage: Counter = Counter()
    counted = explicit_na = 0
    for t_row, p_row in pairs:
        for field in fields:
            agreement, cls = _cell_agreement(field, t_row, t_header, p_row, p_header)
            triage[cls] += 1
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
        "triage": dict(triage),
        "reference_defects": defects,
        "accessions": accession_report(pred_text, resolver),
        "template_self_declared": template_self_declared(pred_text),
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

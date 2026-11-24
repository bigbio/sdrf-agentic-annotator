#!/usr/bin/env python3
"""Index the annotated SDRF corpus, for the similar SDRFs and the known values of the evidence sheet.

usage: build_corpus_index.py CORPUS_DIR OUT.tsv[.gz]

CORPUS_DIR is a checkout of bigbio/sdrf-annotated-datasets. Every datasets/<acc>/*.sdrf.tsv becomes one row
(sandbox/ is left out): accession, path, the distinct values of the columns below (ontology names only, `|`
joined, at most 20 each) and the column names. No model is called.
"""
import csv
import re
import sys
from pathlib import Path

FIELDS = {
    "organism": "characteristics[organism]",
    "instrument": "comment[instrument]",
    "label": "comment[label]",
    "cell_line": "characteristics[cell line]",
    "organism_part": "characteristics[organism part]",
    "disease": "characteristics[disease]",
    "cell_type": "characteristics[cell type]",
    "modification": "comment[modification parameters]",
}
EMPTY = {"", "not applicable", "not available", "na", "none"}
MAX_VALUES = 20


def name(value):
    """The NT= name of an ontology value, or the value itself."""
    m = re.search(r"(?:^|;)\s*NT=([^;]+)", value)
    return (m.group(1) if m else value).replace("|", "/").strip()


def index_row(path, root):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        return None
    header = [h.strip() for h in rows[0]]
    lower = [h.lower() for h in header]
    out = {"accession": path.parent.name, "path": str(path.relative_to(root))}
    for field, column in FIELDS.items():
        cols = [i for i, h in enumerate(lower) if h == column]
        values = sorted({name(r[i]) for r in rows[1:] for i in cols if i < len(r)} - {""}, key=str.lower)
        out[field] = "|".join(v for v in values if v.lower() not in EMPTY)[:2000] if values else ""
        out[field] = "|".join(out[field].split("|")[:MAX_VALUES])
    out["columns"] = "|".join(dict.fromkeys(lower))
    return out


def main(corpus_dir, out_path):
    root = Path(corpus_dir)
    files = sorted((root / "datasets").glob("*/*.sdrf.tsv"))
    columns = ["accession", "path", *FIELDS, "columns"]
    n = 0
    import gzip
    opener = gzip.open if str(out_path).endswith(".gz") else open
    with opener(out_path, "wt", newline="") as fh:
        writer = csv.DictWriter(fh, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for f in files:
            row = index_row(f, root)
            if row:
                writer.writerow(row)
                n += 1
    print(f"wrote {out_path}: {n} SDRFs")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

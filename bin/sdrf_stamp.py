#!/usr/bin/env python3
"""Name this pipeline in `comment[sdrf annotation tool]` of an SDRF and name its samples.

usage: sdrf_stamp.py IN.sdrf.tsv OUT.sdrf.tsv PIPELINE_VERSION [PXD NAMES.tsv]

The tool value is `NT=sdrf-agentic-annotator;VV=v<version>`, a form the template accepts. The agents often
write `manual curation`, which is wrong for an SDRF that a model produced. If the column is missing,
it is added after the last `comment[sdrf template]` column.

With PXD and NAMES.tsv, the samples are renamed to `<PXD>-Sample-<n>`: every distinct `source name` gets
the next number in the order it first appears, so rows of one sample (fractions, replicate runs, labels)
keep one name. NAMES.tsv lists the original name of each sample next to its new name. Nothing else in the
file changes.
"""
import csv
import sys

COLUMN = "comment[sdrf annotation tool]"
SOURCE = "source name"


def stamp(rows, version):
    header, body = rows[0], rows[1:]
    value = f"NT=sdrf-agentic-annotator;VV=v{version}"
    if COLUMN in header:
        i = header.index(COLUMN)
    else:
        templates = [n for n, h in enumerate(header) if h == "comment[sdrf template]"]
        i = (templates[-1] + 1) if templates else len(header)
        header.insert(i, COLUMN)
        for row in body:
            row.insert(i, "")
    for row in body:
        row[i] = value
    return [header] + body


def name_samples(rows, pxd):
    """Rename the samples to <pxd>-Sample-<n>. Returns the rows and the (original name, new name) pairs."""
    header, body = rows[0], rows[1:]
    if SOURCE not in header:
        return rows, []
    i = header.index(SOURCE)
    names = {}
    for row in body:
        original = row[i]
        if original not in names:
            names[original] = f"{pxd}-Sample-{len(names) + 1}"
        row[i] = names[original]
    return [header] + body, list(names.items())


if __name__ == "__main__":
    src, dst, version = sys.argv[1:4]
    with open(src, newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    rows = stamp(rows, version)
    pairs = []
    if len(sys.argv) > 5:
        rows, pairs = name_samples(rows, sys.argv[4])
    with open(dst, "w", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\n").writerows(rows)
    if len(sys.argv) > 5:
        with open(sys.argv[5], "w", newline="") as f:
            csv.writer(f, delimiter="\t", lineterminator="\n").writerows([["original source name", SOURCE]] + [list(p) for p in pairs])

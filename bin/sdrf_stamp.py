#!/usr/bin/env python3
"""Name this pipeline in `comment[sdrf annotation tool]` of an SDRF.

usage: sdrf_stamp.py IN.sdrf.tsv OUT.sdrf.tsv PIPELINE_VERSION

The value is `NT=sdrf-agentic-annotator;VV=v<version>`, a form the template accepts. The agents often
write `manual curation`, which is wrong for an SDRF that a model produced. If the column is missing,
it is added after the last `comment[sdrf template]` column. Nothing else in the file changes.
"""
import csv
import sys

COLUMN = "comment[sdrf annotation tool]"


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


if __name__ == "__main__":
    src, dst, version = sys.argv[1:4]
    with open(src, newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    with open(dst, "w", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\n").writerows(stamp(rows, version))

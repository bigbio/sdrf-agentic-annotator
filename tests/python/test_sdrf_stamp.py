"""Tests for bin/sdrf_stamp.py. Run with: PYTHONPATH=bin python -m pytest tests/python"""
import sdrf_stamp

TOOL = "comment[sdrf annotation tool]"


def test_replaces_manual_curation_in_every_row():
    rows = [["source name", "comment[sdrf template]", TOOL, "comment[data file]"], ["a", "NT=x;VV=v1", "manual curation", "a.raw"], ["b", "NT=x;VV=v1", "manual curation", "b.raw"]]
    out = sdrf_stamp.stamp(rows, "0.1.0dev")
    assert [r[2] for r in out[1:]] == ["NT=sdrf-agentic-annotator;VV=v0.1.0dev"] * 2
    assert out[0] == rows[0] and [r[3] for r in out[1:]] == ["a.raw", "b.raw"]


def test_adds_the_column_after_the_last_template_column():
    rows = [["source name", "comment[sdrf template]", "comment[sdrf template]", "comment[data file]"], ["a", "t1", "t2", "a.raw"]]
    out = sdrf_stamp.stamp(rows, "1.2.3")
    assert out[0] == ["source name", "comment[sdrf template]", "comment[sdrf template]", TOOL, "comment[data file]"]
    assert out[1] == ["a", "t1", "t2", "NT=sdrf-agentic-annotator;VV=v1.2.3", "a.raw"]

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


def test_samples_are_numbered_in_order_of_first_appearance():
    rows = [["source name", "comment[data file]"], ["MCF10A_dense", "a.raw"], ["MCF10A_sparse", "b.raw"], ["MCF10A_dense", "c.raw"]]
    out, pairs = sdrf_stamp.name_samples(rows, "PXD000001")
    assert [r[0] for r in out[1:]] == ["PXD000001-Sample-1", "PXD000001-Sample-2", "PXD000001-Sample-1"]
    assert pairs == [("MCF10A_dense", "PXD000001-Sample-1"), ("MCF10A_sparse", "PXD000001-Sample-2")]
    assert [r[1] for r in out[1:]] == ["a.raw", "b.raw", "c.raw"]


def test_a_file_without_a_source_name_column_is_left_alone():
    rows = [["assay name", "comment[data file]"], ["a", "a.raw"]]
    out, pairs = sdrf_stamp.name_samples(rows, "PXD000001")
    assert out == rows and pairs == []

"""Tests for bin/archive_runs.py. Run with:
    PYTHONPATH=bin python -m pytest tests/python/test_archive_runs.py
"""
import json
import zipfile

import archive_runs


def _zip(path, names, zip64=False):
    with zipfile.ZipFile(path, "w", allowZip64=True) as z:
        for n in names:
            z.writestr(zipfile.ZipInfo(n), b"x", compress_type=zipfile.ZIP_STORED)
    return path


def _reader(path):
    data = path.read_bytes()

    def read(start, end):  # inclusive byte range, like an HTTP Range header
        return data[start:end + 1]
    return read, len(data)


def test_members_runs_only(tmp_path):
    z = _zip(tmp_path / "raw.zip", ["Raw_files/PP1_TL_1.raw", "Raw_files/PP1_TL_2.raw", "Raw_files/readme.txt",
                                     "A_01.d/analysis.tdf", "A_01.d/analysis.tdf_bin", "A_02.d/analysis.tdf", "x.wiff",
                                     "x.wiff.scan", "__MACOSX/._PP1_TL_1.raw"])
    read, size = _reader(z)
    assert archive_runs.run_members(archive_runs.zip_names(read, size)) == [
        "A_01.d", "A_02.d", "PP1_TL_1.raw", "PP1_TL_2.raw", "x.wiff"]


def test_zip64(tmp_path):
    names = [f"r{i}.raw" for i in range(70000)]  # more than 65535 entries: the archive needs a ZIP64 end record
    z = _zip(tmp_path / "big.zip", names)
    read, size = _reader(z)
    got = archive_runs.zip_names(read, size)
    assert len(got) == 70000 and got[0] == "r0.raw"


def test_expand_files_json(tmp_path):
    z = _zip(tmp_path / "RAWFiles.zip", ["S1.d/analysis.tdf", "S2.d/analysis.tdf"])
    files = tmp_path / "files.json"
    files.write_text(json.dumps({"accession": "PXD1", "files": ["RAWFiles.zip", "extra.raw"], "other_files": [],
                                 "urls": {"RAWFiles.zip": "https://example/RAWFiles.zip"}}))
    read, size = _reader(z)
    archive_runs.expand(str(files), opener=lambda url: (read, size))
    d = json.loads(files.read_text())
    assert d["files"] == ["S1.d", "S2.d", "extra.raw"]
    assert d["archives"]["RAWFiles.zip"]["runs"] == 2
    assert d["deposited_files"] == ["RAWFiles.zip", "extra.raw"]


def test_expand_keeps_files_when_listing_fails(tmp_path):
    files = tmp_path / "files.json"
    files.write_text(json.dumps({"files": ["a.zip"], "urls": {"a.zip": "https://example/a.zip"}}))

    def broken(url):
        raise OSError("403 Forbidden")
    archive_runs.expand(str(files), opener=broken)
    d = json.loads(files.read_text())
    assert d["files"] == ["a.zip"] and "403" in d["archives"]["a.zip"]["error"]


def test_expand_without_archives_is_unchanged(tmp_path):
    files = tmp_path / "files.json"
    original = {"files": ["a.raw", "b.raw"], "urls": {}}
    files.write_text(json.dumps(original))
    archive_runs.expand(str(files), opener=lambda url: (_ for _ in ()).throw(AssertionError("no fetch")))
    assert json.loads(files.read_text()) == original

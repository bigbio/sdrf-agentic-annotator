import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))
import sdrf_deliverable  # noqa: E402

problem = sdrf_deliverable.deposit_problem


def test_plain_runs_are_deliverable():
    assert problem({"files": ["a.raw", "b.raw"]}) is None
    assert problem({"files": [{"fileName": "a.mzML"}, {"fileName": "b.wiff"}]}) is None


def test_listed_zip_is_deliverable():
    # archive_runs.py replaced the zip by the runs inside it
    fj = {"files": ["run1.raw", "run2.raw"], "deposited_files": ["RAW.zip"], "archives": {"RAW.zip": {"runs": 2}}}
    assert problem(fj) is None


def test_bruker_d_zip_is_a_run():
    assert problem({"files": ["sample_1.d.zip", "sample_2.d.zip"]}) is None


def test_unlistable_zip_is_not_deliverable():
    fj = {"files": ["RAW.zip"], "archives": {"RAW.zip": {"error": "HTTP 403"}}}
    assert "archive" in problem(fj)


def test_rar_7z_tar_are_not_deliverable():
    for name in ("runs.rar", "runs.7z", "runs.tar", "runs.tar.gz", "runs.tgz"):
        assert "archive" in problem({"files": [name, "x.raw"]}), name


def test_no_run_files_is_not_deliverable():
    assert "no run files" in problem({"files": ["results.xlsx", "search.mzid"]})


def test_cli_writes_json_and_keeps_unknown_deposits(tmp_path, capsys):
    good = tmp_path / "files.json"
    good.write_text(json.dumps({"files": ["a.raw"]}))
    assert sdrf_deliverable.main([str(good)]) == 0
    assert json.loads(capsys.readouterr().out) == {"deliverable": True, "reason": ""}
    # a missing or unreadable list must never drop a dataset
    assert sdrf_deliverable.main([str(tmp_path / "missing.json")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deliverable"] is True and "could not read" in out["reason"]


def test_zipped_waters_raw_folders_follow_the_coverage_audit():
    # the audit cannot list runs inside .raw.zip archives, so an SDRF of this deposit would be held
    assert "archive" in problem({"files": ["s1.raw.zip", "s2.raw.zip"]})

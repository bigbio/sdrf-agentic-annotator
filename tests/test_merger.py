import subprocess
from pathlib import Path
import pytest
from sdrf_harness.merger import stage_sdrf, commit_batch

def _git(d, *a): subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)

def _repo(tmp_path):
    d = tmp_path / "corpus"; (d / "datasets").mkdir(parents=True)
    _git(d, "init", "-q"); _git(d, "config", "user.email", "t@t"); _git(d, "config", "user.name", "t")
    (d / "README.md").write_text("x"); _git(d, "add", "."); _git(d, "commit", "-qm", "init")
    return d

def test_stage_writes_and_refuses_overwrite(tmp_path):
    d = _repo(tmp_path)
    p = stage_sdrf(d, "PXD1", "source name\ta.raw\n")
    assert p.read_text().startswith("source name")
    with pytest.raises(FileExistsError):
        stage_sdrf(d, "PXD1", "other")

def test_commit_batch_returns_sha(tmp_path):
    d = _repo(tmp_path)
    p = stage_sdrf(d, "PXD1", "source name\ta.raw\n")
    sha = commit_batch(d, [p], "add PXD1")
    assert len(sha) >= 7
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=d, capture_output=True, text=True).stdout
    assert "add PXD1" in log

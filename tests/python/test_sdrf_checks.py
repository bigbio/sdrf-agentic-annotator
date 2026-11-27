import hashlib

import sdrf_checks


SDRF = (
    "source name\tcharacteristics[organism]\tassay name\tcomment[sdrf template]\tcomment[sdrf template]\n"
    "s1\thomo sapiens\trun1\tNT=ms-proteomics;VV=v1.1.0\tNT=human;VV=v1.1.0\n"
    "s2\thomo sapiens\trun2\tNT=ms-proteomics;VV=v1.1.0\tNT=human;VV=v1.1.0\n"
)


def write(tmp_path, text=SDRF):
    p = tmp_path / "PXD1.sdrf.tsv"
    p.write_text(text)
    return p


def test_active_templates_from_every_template_column(tmp_path):
    assert sdrf_checks.active_templates(write(tmp_path)) == ["ms-proteomics", "human"]


def test_no_template_column_gives_no_templates(tmp_path):
    assert sdrf_checks.active_templates(write(tmp_path, "source name\tassay name\ns1\trun1\n")) == []


def test_commands_validate_each_template_together(tmp_path):
    cmds = sdrf_checks.commands(write(tmp_path), record=None)
    validate = [c for name, c in cmds if name.startswith("parse_sdrf validate-sdrf")]
    assert validate == [["parse_sdrf", "validate-sdrf", "-s", str(tmp_path / "PXD1.sdrf.tsv"),
                         "-t", "ms-proteomics", "-t", "human", "--use_ols_cache_only"]]
    names = [name for name, _ in cmds]
    assert "sdrf-tools check" in names and "sdrf-tools score" in names and "sdrf-tools structure" in names
    assert not any(n.startswith("sdrf-tools reconcile") for n in names)


def test_reconcile_only_with_a_record(tmp_path):
    rec = tmp_path / "pride.json"
    rec.write_text("{}")
    cmds = dict(sdrf_checks.commands(write(tmp_path), record=rec))
    assert cmds["sdrf-tools reconcile"][-2:] == ["--record", str(rec)]


def test_report_has_hash_and_each_output_and_exit_code(tmp_path):
    p = write(tmp_path)

    def runner(cmd):
        return (1, "boom output") if cmd[1] == "score" else (0, f"ran {cmd[1]}")

    text = sdrf_checks.report(p, record=None, run=runner)
    assert hashlib.sha256(p.read_bytes()).hexdigest() in text
    assert "## sdrf-tools score (exit 1)" in text and "boom output" in text
    assert "## sdrf-tools check (exit 0)" in text and "ran check" in text


def test_a_failing_command_never_raises(tmp_path):
    def runner(cmd):
        raise OSError("not installed")

    text = sdrf_checks.report(write(tmp_path), record=None, run=runner)
    assert "not installed" in text


def test_long_output_is_cut(tmp_path):
    text = sdrf_checks.report(write(tmp_path), record=None, run=lambda cmd: (0, "x" * 50000), limit=1000)
    assert "[cut:" in text
    assert len(text) < 12 * 1500


def test_relative_paths_work_from_the_scratch_folder(tmp_path, monkeypatch):
    write(tmp_path)
    (tmp_path / "pride.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    for _, cmd in sdrf_checks.commands("PXD1.sdrf.tsv", record="pride.json"):
        paths = [a for a in cmd if a.endswith((".tsv", ".json"))]
        assert paths and all(a.startswith("/") for a in paths), cmd


def test_report_ends_with_the_sample_identity_section(tmp_path):
    text = (
        "source name\tcharacteristics[biological replicate]\tassay name\n"
        "s1\t1\trun1\n"
        "s1\t2\trun2\n"
    )
    out = sdrf_checks.report(write(tmp_path, text), run=lambda cmd: (0, "ok"))
    assert "## Sample identity" in out and "BLOCKER" in out and "s1" in out

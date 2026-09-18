import sys

from sdrf_model_bench.validator import distinct_errors, parse_output, validate, validity_score

OUT = """ERROR: Required column 'comment[label]' is missing from the SDRF file
ERROR: Row 3: bad value
ERROR: Row 4: bad value
WARNING: Term: foo in column 'characteristics[organism]', is not found
There were validation errors."""


def test_parse_and_distinct():
    res = parse_output(OUT)
    assert len(res.errors) == 3 and len(res.warnings) == 1
    assert distinct_errors(res.errors) == [
        "Required column 'comment[label]' is missing from the SDRF file", "Row #: bad value"]
    assert validity_score(res) == 0.8


def test_clean_output_scores_one():
    assert validity_score(parse_output("Most seems to be fine. There were only warnings.")) == 1.0


def test_validity_floor_is_zero():
    res = parse_output("\n".join(f"ERROR: missing col{chr(97 + i)}" for i in range(15)))
    assert validity_score(res) == 0.0


def test_validate_runs_the_given_binary(tmp_path):
    fake = tmp_path / "fake_parse_sdrf"
    fake.write_text(f"#!{sys.executable}\nimport sys\nprint('ERROR: ' + ' '.join(sys.argv[1:]))\n")
    fake.chmod(0o755)
    res = validate(tmp_path / "x.tsv", templates=["human"], parse_sdrf=str(fake))
    assert "validate-sdrf" in res.errors[0] and "--use_ols_cache_only" in res.errors[0]
    assert "-t human" in res.errors[0]


def test_crash_is_an_error(tmp_path):
    fake = tmp_path / "crash"
    fake.write_text(f"#!{sys.executable}\nraise SystemExit('Traceback: boom')\n")
    fake.chmod(0o755)
    assert validate(tmp_path / "x.tsv", parse_sdrf=str(fake)).errors

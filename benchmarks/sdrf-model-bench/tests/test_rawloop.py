import json

from sdrf_model_bench.evidence import estimate_tokens, load_evidence
from sdrf_model_bench.prompts import build_messages
from sdrf_model_bench.providers import Completion
from sdrf_model_bench.rawloop import extract_tsv, run_raw
from sdrf_model_bench.validator import ValidationResult

GOOD = "source name\tcomment[data file]\ns1\ta.raw\n"


def make_ev(tmp_path, manuscript="M" * 400):
    d = tmp_path / "evidence" / "PXD1"
    d.mkdir(parents=True)
    (d / "pride.json").write_text(json.dumps({"title": "T", "projectDescription": "D" * 100,
                                              "organisms": [{"name": "Homo sapiens (human)"}]}))
    (d / "files.json").write_text(json.dumps(["a.raw", "b.raw"]))
    (d / "manuscript.txt").write_text(manuscript)
    (d / "meta.json").write_text(json.dumps({"accession": "PXD1"}))
    return load_evidence(tmp_path, "PXD1")


def test_manuscript_toggle(tmp_path):
    ev = make_ev(tmp_path)
    on, _ = build_messages(ev, manuscript=True)
    off, _ = build_messages(ev, manuscript=False)
    assert "M" * 400 in on[-1]["content"]
    assert "M" * 400 not in off[-1]["content"] and "a.raw" in off[-1]["content"]


def test_budget_truncates_manuscript_first(tmp_path):
    ev = make_ev(tmp_path, manuscript="x" * 400_000)
    msgs, info = build_messages(ev, manuscript=True, budget_tokens=2000)
    assert info["truncated"] and info["evidence_tokens"] <= 2000
    assert "Homo sapiens" in msgs[-1]["content"]
    assert estimate_tokens("abcd") == 1


def test_extract_tsv_from_fence_and_prose():
    assert extract_tsv(f"Here:\n```tsv\n{GOOD}```\nbye") == GOOD
    assert extract_tsv("no table here") is None
    assert extract_tsv("Source name\tx\n") is None  # header only


def test_repair_loop_feeds_errors_back(tmp_path):
    replies = iter(["oops, no table", f"```tsv\n{GOOD}```", f"```tsv\n{GOOD}```"])
    seen = []

    def gen(msgs):
        seen.append(msgs)
        return Completion(next(replies), {"input_tokens": 10, "output_tokens": 2})

    results = iter([ValidationResult(errors=["Row 1: bad"]), ValidationResult()])
    r = run_raw(gen, [{"role": "user", "content": "go"}], tmp_path, lambda p: next(results))
    assert r.turns == 3 and r.sdrf == GOOD and not r.validation.errors
    assert r.usage == {"input_tokens": 30, "output_tokens": 6}
    assert "Row #: bad" in seen[2][-1]["content"]


def test_repair_budget_is_respected(tmp_path):
    gen = lambda m: Completion("nothing", {})  # noqa: E731
    r = run_raw(gen, [{"role": "user", "content": "go"}], tmp_path, lambda p: ValidationResult(), max_repairs=1)
    assert r.turns == 2 and r.sdrf is None

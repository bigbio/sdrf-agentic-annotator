import json

from sdrf_model_bench.config import ModelSpec
from sdrf_model_bench.providers import Completion
from sdrf_model_bench.runner import RunConfig, RunKey, execute_run, load_manifest, plan_runs
from sdrf_model_bench.scoring_run import score_tree
from sdrf_model_bench.validator import ValidationResult

TRUTH = "source name\tcharacteristics[organism]\tcomment[data file]\ns1\thomo sapiens\ta.raw\n"


def setup_data(tmp_path):
    data = tmp_path / "data"
    ev = data / "evidence" / "PXD1"
    ev.mkdir(parents=True)
    (ev / "pride.json").write_text(json.dumps({"title": "T"}))
    (ev / "files.json").write_text(json.dumps(["a.raw"]))
    (ev / "manuscript.txt").write_text("methods")
    (ev / "meta.json").write_text(json.dumps({"accession": "PXD1", "tier": "poor", "qtype": "LFQ", "templates": []}))
    (data / "truth").mkdir()
    (data / "truth" / "PXD1.sdrf.tsv").write_text(TRUTH)
    (data / "manifest.tsv").write_text("accession\tqtype\ttier\nPXD1\tLFQ\tpoor\n")
    return data


def test_plan_runs_crosses_everything(tmp_path):
    data = setup_data(tmp_path)
    specs = [ModelSpec("a", "ollama", "m", "raw", options={"num_ctx": 1}),
             ModelSpec("b", "claude-code", "m", "skills")]
    keys = plan_runs(specs, load_manifest(data / "manifest.tsv"), replicates={"PXD1": 2})
    assert len(keys) == 2 * 2 * 2
    assert RunKey("a", "PXD1", True, 1).dirname == "PXD1__ms-on__r1"


def test_execute_and_score_end_to_end(tmp_path):
    data = setup_data(tmp_path)
    spec = ModelSpec("fake-raw", "custom", "fake", "raw", context_window=100_000)
    calls = []

    def gen(msgs):
        calls.append(msgs)
        return Completion(f"```tsv\n{TRUTH}```", {"input_tokens": 100, "output_tokens": 10})

    cfg = RunConfig(data_dir=data, outputs=tmp_path / "out", pricing={},
                    validate_fn=lambda p, t=(): ValidationResult(), generate_factory=lambda s: gen)
    rec = execute_run(RunKey("fake-raw", "PXD1", False, 1), spec, cfg)
    assert rec["flags"] == [] and (tmp_path / "out" / "fake-raw" / "PXD1__ms-off__r1" / "sdrf.tsv").exists()
    execute_run(RunKey("fake-raw", "PXD1", False, 1), spec, cfg)  # resume: no new call
    assert len(calls) == 1

    records = score_tree(tmp_path / "out", data, validate_fn=lambda p, t=(): ValidationResult(), judge_fn=None)
    assert len(records) == 1
    r = records[0]
    assert r["deterministic"] == 100.0 and r["headline"] == 100.0
    assert r["qtype"] == "LFQ" and r["manuscript"] is False
    assert "contamination_suspect" in r["flags"]  # ms-off + poor tier + >= 80


def test_crash_is_retried_not_cached(tmp_path):
    data = setup_data(tmp_path)
    spec = ModelSpec("flaky", "custom", "fake", "raw")
    outcomes = iter([RuntimeError("529 overloaded"), Completion(f"```tsv\n{TRUTH}```", {})])

    def gen(msgs):
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    cfg = RunConfig(data_dir=data, outputs=tmp_path / "out", pricing={},
                    validate_fn=lambda p, t=(): ValidationResult(), generate_factory=lambda s: gen)
    key = RunKey("flaky", "PXD1", True, 1)
    run_dir = tmp_path / "out" / "flaky" / key.dirname
    assert execute_run(key, spec, cfg)["flags"] == ["error"]
    assert (run_dir / "error.json").exists() and not (run_dir / "usage.json").exists()
    assert execute_run(key, spec, cfg)["flags"] == []
    assert not (run_dir / "error.json").exists()


def test_context_limited_flag(tmp_path):
    data = setup_data(tmp_path)
    spec = ModelSpec("tiny", "custom", "fake", "raw", context_window=50)
    cfg = RunConfig(data_dir=data, outputs=tmp_path / "out", pricing={},
                    validate_fn=lambda p, t=(): ValidationResult(),
                    generate_factory=lambda s: (lambda m: Completion("nothing", {})))
    rec = execute_run(RunKey("tiny", "PXD1", True, 1), spec, cfg)
    assert "context_limited" in rec["flags"] and "failed" in rec["flags"]


def test_context_flag_scales_with_expected_output(tmp_path):
    from sdrf_model_bench.runner import expected_output_tokens

    data = setup_data(tmp_path)
    assert expected_output_tokens(data, "PXD1") < 100
    assert expected_output_tokens(data, "PXD_missing") == 8192
    spec = ModelSpec("small", "custom", "fake", "raw", context_window=8192)
    cfg = RunConfig(data_dir=data, outputs=tmp_path / "out", pricing={},
                    validate_fn=lambda p, t=(): ValidationResult(),
                    generate_factory=lambda s: (lambda m: Completion(f"```tsv\n{TRUTH}```", {})))
    assert "context_limited" not in execute_run(RunKey("small", "PXD1", True, 1), spec, cfg)["flags"]

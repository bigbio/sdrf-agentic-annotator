from sdrf_model_bench.report import render_backups, render_slide, summarise


def rec(model_id, arm, model, acc, ms, score, qtype="TMT", tier="rich", cost=0.1, wall=60, flags=()):
    return {"model_id": model_id, "arm": arm, "model": model, "accession": acc, "manuscript": ms,
            "qtype": qtype, "tier": tier, "headline": score, "deterministic": score, "judge": None,
            "validity": 1, "completeness": 1, "accuracy": score / 100, "specificity": 1,
            "usage": {"input_tokens": 1000, "output_tokens": 500}, "cost_usd": cost, "wall_s": wall,
            "flags": list(flags)}


RECORDS = [
    rec("m-raw", "raw", "m", "P1", True, 60), rec("m-raw", "raw", "m", "P1", False, 40),
    rec("m-skills", "skills", "m", "P1", True, 90), rec("m-skills", "skills", "m", "P1", False, 80),
    rec("local", "raw", "l", "P1", True, 20, cost=None, wall=600, flags=["context_limited"]),
    rec("local", "raw", "l", "P1", False, 10, cost=None, wall=600, flags=["failed"]),
]


def test_summarise():
    rows = {r["model_id"]: r for r in summarise(RECORDS)}
    assert rows["m-raw"]["headline"] == 50 and rows["m-raw"]["ms_delta"] == 20
    assert rows["m-skills"]["base"] == "m" and rows["local"]["cost_usd"] is None
    assert rows["local"]["minutes"] == 10 and rows["local"]["flags"]["failed"] == 1
    assert rows["m-raw"]["tokens"] == 1500


def test_render(tmp_path):
    summary = summarise(RECORDS)
    render_slide(summary, tmp_path / "slide")
    assert (tmp_path / "slide.svg").stat().st_size > 0 and (tmp_path / "slide.png").stat().st_size > 0
    render_backups(RECORDS, summary, tmp_path)
    assert (tmp_path / "backup_components.png").exists()


def test_dark_theme_and_pending_rows(tmp_path):
    render_slide(summarise(RECORDS), tmp_path / "slide-dark", theme="dark", pending=["your-model"])
    assert (tmp_path / "slide-dark.png").stat().st_size > 0


def test_thinking_models_are_labelled():
    r = rec("g-think", "raw", "gemma4:12b", "P1", True, 30)
    r["think"] = True
    assert summarise([r])[0]["base"] == "gemma4:12b (thinking)"

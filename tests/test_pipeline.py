from sdrf_agentic_annotator.pipeline import draft_dataset

MSGS = [{"role": "user", "content": "draft it"}]


def _gen(_convo):
    return "source name\tcomment[instrument]\nS1\tNT=Guess;AC=MS:9999999"


def _validate_clean(_text):
    return {"errors": [], "warnings": []}


def test_pipeline_loop_only():
    out = draft_dataset("PXD1", MSGS, _gen, _validate_clean)
    assert out["passed"] is True
    assert "loop" in out["stages"]
    assert "techsdrf" not in out["stages"]
    assert "refine" not in out["stages"]


def test_pipeline_runs_techsdrf_then_refine_in_order():
    order = []

    def techrefine_fn(acc, text):
        order.append("tech")
        return {
            "ok": True,
            "text": text + "\t# tech",
            "changes": [("comment[instrument]", "a", "b")],
        }

    def refine_fn(text):
        order.append("refine")
        # refine must see the techsdrf-modified text
        assert "# tech" in text
        return text + " # ref", {"grounded": [1], "stripped": []}

    out = draft_dataset(
        "PXD1",
        MSGS,
        _gen,
        _validate_clean,
        techrefine_fn=techrefine_fn,
        refine_fn=refine_fn,
    )
    assert order == ["tech", "refine"]  # empirical before accession grounding
    assert out["stages"]["techsdrf"]["ok"] is True
    assert out["stages"]["refine"]["grounded"] == [1]
    assert out["text"].endswith("# ref")


def test_pipeline_skips_techsdrf_when_not_ok():
    def techrefine_fn(acc, text):
        return {"ok": False, "text": text, "changes": []}

    def refine_fn(text):
        assert "# tech" not in text  # unchanged input flows through
        return text, {"grounded": [], "stripped": []}

    out = draft_dataset(
        "PXD1",
        MSGS,
        _gen,
        _validate_clean,
        techrefine_fn=techrefine_fn,
        refine_fn=refine_fn,
    )
    assert out["stages"]["techsdrf"]["ok"] is False


def test_pipeline_reports_final_validation_failure():
    def validate(text):
        return {"errors": ["still bad"], "warnings": []}

    out = draft_dataset("PXD1", MSGS, _gen, validate, max_iters=2)
    assert out["passed"] is False
    assert out["final_validation"]["errors"] == ["still bad"]
    assert out["stages"]["loop"]["iters"] == 2


def test_pipeline_final_validation_after_refine():
    # refine fixes the text so final validation passes even though loop saw errors
    calls = {"n": 0}

    def validate(text):
        calls["n"] += 1
        return (
            {"errors": [], "warnings": []}
            if "# ref" in text
            else {"errors": ["e"], "warnings": []}
        )

    def refine_fn(text):
        return text + " # ref", {"grounded": [], "stripped": []}

    out = draft_dataset("PXD1", MSGS, _gen, validate, refine_fn=refine_fn, max_iters=2)
    assert out["passed"] is True

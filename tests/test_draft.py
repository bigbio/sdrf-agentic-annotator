from sdrf_agentic_annotator.draft import (
    build_repair_message,
    clean_output,
    header_order_errors,
    physical_order,
    run_repair_loop,
    validate_text,
)
from sdrf_agentic_annotator.template import combine


# --- physical_order ---------------------------------------------------------


def test_physical_order_strings():
    cols = [
        "assay name",
        "characteristics[disease]",
        "source name",
        "comment[label]",
        "technology type",
        "characteristics[organism]",
    ]
    ordered = physical_order(cols)
    assert ordered[0] == "source name"
    assert ordered.index("characteristics[organism]") < ordered.index("assay name")
    assert ordered.index("characteristics[disease]") < ordered.index("assay name")
    assert ordered.index("assay name") < ordered.index("technology type")
    assert ordered.index("technology type") < ordered.index("comment[label]")


def test_physical_order_on_real_template():
    cols = physical_order(combine(["ms-proteomics", "cell-lines"]))
    names = [c.name for c in cols]
    assert names[0] == "source name"
    last_char = max(i for i, n in enumerate(names) if n.startswith("characteristics["))
    assert last_char < names.index("assay name")


# --- header_order_errors ----------------------------------------------------


def test_header_order_flags_characteristic_after_assay():
    header = ["source name", "assay name", "characteristics[organism]", "comment[label]"]
    errs = header_order_errors(header)
    assert any("before" in e and "assay name" in e for e in errs)


def test_header_order_clean_passes():
    header = ["source name", "characteristics[organism]", "assay name", "comment[label]"]
    assert header_order_errors(header) == []


def test_header_order_flags_missing_source_name_first():
    header = ["characteristics[organism]", "source name"]
    assert any("source name" in e for e in header_order_errors(header))


# --- clean_output -----------------------------------------------------------


def test_clean_output_strips_fences_and_prose():
    raw = "Here is your SDRF:\n```tsv\nsource name\tassay name\nS1\tA1\n```"
    out = clean_output(raw)
    assert out.startswith("source name\t")
    assert "```" not in out
    assert "Here is" not in out


# --- validate_text (no CLI) -------------------------------------------------


def test_validate_text_catches_order_and_ragged_without_cli():
    sdrf = "source name\tassay name\tcharacteristics[organism]\n" "S1\tA1\thomo sapiens\tEXTRA"
    res = validate_text(sdrf, run_cli=False)
    assert any("before" in e for e in res["errors"])  # characteristic after assay
    assert any("ragged" in e for e in res["errors"])  # 4 cells vs 3 headers


def test_validate_text_flags_no_data_rows():
    res = validate_text("source name\tassay name", run_cli=False)
    assert any("no data rows" in e for e in res["errors"])


def test_validate_text_clean_minimal_no_cli():
    sdrf = "source name\tcharacteristics[organism]\tassay name\nS1\thomo sapiens\tA1"
    res = validate_text(sdrf, run_cli=False)
    assert res["errors"] == []


def test_validate_text_accession_mismatch_from_labels():
    sdrf = (
        "source name\tcharacteristics[organism]\tassay name\tcomment[instrument]\n"
        "S1\thomo sapiens\tA1\tNT=Orbitrap Elite;AC=MS:9999999"
    )
    labels = {"MS:9999999": "some other instrument"}
    res = validate_text(sdrf, run_cli=False, labels=labels)
    assert any("Accession mismatch" in e for e in res["errors"])


# --- build_repair_message ---------------------------------------------------


def test_repair_message_lists_errors():
    msg = build_repair_message(["err one", "err two"], ["warn one"])
    assert "err one" in msg and "err two" in msg
    assert "warn one" in msg
    assert "corrected SDRF" in msg


# --- run_repair_loop (fake model) -------------------------------------------


def test_loop_stops_when_clean():
    drafts = iter(["bad", "good"])
    calls = {"n": 0}

    def generate(convo):
        calls["n"] += 1
        return next(drafts)

    def validate(text):
        return {"errors": [] if text == "good" else ["fix me"], "warnings": []}

    out = run_repair_loop([{"role": "user", "content": "go"}], generate, validate)
    assert out["passed"] is True
    assert out["iters"] == 2
    assert calls["n"] == 2
    assert out["history"][0]["errors"] == 1
    assert out["history"][1]["errors"] == 0


def test_loop_feeds_errors_back_into_conversation():
    seen_convos = []

    def generate(convo):
        seen_convos.append(convo)
        return "still bad"

    def validate(text):
        return {"errors": ["column order wrong"], "warnings": []}

    run_repair_loop([{"role": "user", "content": "go"}], generate, validate, max_iters=2)
    # second call must include the assistant draft + a repair message citing the error
    second = seen_convos[1]
    assert any(m["role"] == "assistant" for m in second)
    assert any("column order wrong" in m["content"] for m in second if m["role"] == "user")


def test_loop_gives_up_after_max_iters():
    def generate(convo):
        return "bad"

    def validate(text):
        return {"errors": ["nope"], "warnings": []}

    out = run_repair_loop([{"role": "user", "content": "go"}], generate, validate, max_iters=3)
    assert out["passed"] is False
    assert out["iters"] == 3
    assert len(out["history"]) == 3


def test_loop_improves_over_rounds():
    # model fixes one error per round -> loop converges
    state = {"errs": ["a", "b", "c"]}

    def generate(convo):
        return "draft"

    def validate(text):
        if state["errs"]:
            state["errs"] = state["errs"][1:]
        return {"errors": state["errs"], "warnings": []}

    out = run_repair_loop([{"role": "user", "content": "go"}], generate, validate, max_iters=5)
    counts = [h["errors"] for h in out["history"]]
    assert counts == sorted(counts, reverse=True)  # monotonically non-increasing
    assert out["passed"] is True

from sdrf_agentic_annotator.models import Bundle
from sdrf_agentic_annotator.prompt import SYSTEM, build_messages, target_columns


def _bundle():
    return Bundle(
        accession="PXD016837",
        repository="pride",
        organisms=[("Homo sapiens", "9606")],
        instruments=["LTQ Orbitrap Elite"],
        files=[
            {"name": "a_r1.raw", "ext": "raw"},
            {"name": "b_r1.raw", "ext": "raw"},
            {"name": "peaklist.mgf", "ext": "mgf"},
        ],
    )


def _project():
    return {
        "title": "A melanoma study",
        "sampleProcessingProtocol": "cells digested with trypsin",
        "dataProcessingProtocol": "searched with X",
    }


def test_target_columns_physical_order_required_and_recommended():
    cols = target_columns(["ms-proteomics", "cell-lines"])
    names = [c.name for c in cols]
    assert names[0] == "source name"
    # characteristics precede assay name
    last_char = max(i for i, n in enumerate(names) if n.startswith("characteristics["))
    assert last_char < names.index("assay name")
    # only required/recommended
    assert all(c.requirement in ("required", "recommended") for c in cols)


def test_build_messages_counts_only_raw_files():
    out = build_messages(_bundle(), _project(), ["ms-proteomics", "human"])
    assert out["n_raw"] == 2  # the .mgf peak list is excluded
    user = out["messages"][1]["content"]
    assert "a_r1.raw" in user and "b_r1.raw" in user
    assert "peaklist.mgf" not in user


def test_build_messages_includes_protocols_and_title():
    out = build_messages(_bundle(), _project(), ["ms-proteomics", "human"])
    user = out["messages"][1]["content"]
    assert "A melanoma study" in user
    assert "trypsin" in user
    assert "header row + 2 data rows" in user


def test_build_messages_lists_columns_in_order():
    out = build_messages(_bundle(), _project(), ["ms-proteomics"])
    user = out["messages"][1]["content"]
    assert user.index("source name") < user.index("assay name")


def test_system_prompt_has_key_rules():
    assert "v1.1.0" in SYSTEM
    assert "OMIT AC=" in SYSTEM
    assert "physical SDRF layout" in SYSTEM


def test_build_messages_includes_gaps_when_given():
    out = build_messages(
        _bundle(), _project(), ["ms-proteomics"], gaps=["characteristics[cell line]"]
    )
    assert "characteristics[cell line]" in out["messages"][1]["content"]

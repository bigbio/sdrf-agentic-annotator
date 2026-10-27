"""Tests for bin/sdrf_prefill.py. Run with the sdrf-skills tools on the path:
    PYTHONPATH=<sdrf-skills checkout>:bin python -m pytest tests/python
"""
import json

import sdrf_prefill


def evidence(tmp_path, record, files):
    (tmp_path / "pride.json").write_text(json.dumps(record))
    (tmp_path / "files.json").write_text(json.dumps(files))
    return tmp_path


RECORD = {
    "accession": "PXD000001",
    "title": "A study",
    "projectDescription": "Mammary epithelial cells.",
    "sampleProcessingProtocol": "Each gel band was reduced, alkylated and digested in gel using 125 ng Trypsin/LysC.",
    "dataProcessingProtocol": "Spectra were searched with MaxQuant.",
    "organisms": [{"accession": "NEWT:9606", "name": "Homo sapiens (human)"}],
    "instruments": [{"accession": "MS:1001911", "name": "Q Exactive"}],
    "organismParts": [{"accession": "BTO:0000668", "name": "Kernel"}],
    "quantificationMethods": [],
    "diseases": [],
}
FILES = {
    "files": ["a.raw", "b.raw"],
    "other_files": ["mqpar.xml", "a.raw_Byonic.mzid.gz", "a.pride.mztab.gz", "notes.txt"],
    "urls": {"mqpar.xml": "https://example.org/mqpar.xml", "notes.txt": "https://example.org/notes.txt"},
}


def test_record_fields_keep_their_accessions(tmp_path):
    out = sdrf_prefill.prefill(evidence(tmp_path, RECORD, FILES))
    assert out["organism"] == [{"value": "Homo sapiens", "source": "pride.json:organisms", "basis": "record", "accession": "NCBITaxon:9606"}]
    assert [(i["value"], i["accession"]) for i in out["instrument"]] == [("Q Exactive", "MS:1001911")]
    assert out["organism_part"][0]["value"] == "Kernel"


def test_co_digest_names_both_enzymes(tmp_path):
    out = sdrf_prefill.prefill(evidence(tmp_path, RECORD, FILES))
    assert [(e["value"], e["accession"], e["basis"]) for e in out["cleavage_agent"]] == [
        ("Trypsin", "MS:1001251", "text"),
        ("Lys-C", "MS:1001309", "text"),
    ]


def test_no_digest_sentence_gives_no_enzyme(tmp_path):
    record = {**RECORD, "sampleProcessingProtocol": "Not available", "dataProcessingProtocol": "Not available"}
    assert sdrf_prefill.prefill(evidence(tmp_path, record, FILES))["cleavage_agent"] == []


def test_label_free_is_marked_as_absence_not_as_fact(tmp_path):
    label = sdrf_prefill.prefill(evidence(tmp_path, RECORD, FILES))["label"]
    assert [(x["value"], x["basis"]) for x in label] == [("label free sample", "absence")]


def test_tmt_in_the_protocol_is_found_as_text(tmp_path):
    record = {**RECORD, "sampleProcessingProtocol": "Peptides were labelled with TMT10plex and digested with trypsin."}
    label = sdrf_prefill.prefill(evidence(tmp_path, record, FILES))["label"]
    assert label[0]["value"] == "TMT" and label[0]["basis"] == "text"


def test_acquisition_hint(tmp_path):
    record = {**RECORD, "dataProcessingProtocol": "Data-independent acquisition (DIA) was searched with DIA-NN."}
    assert [a["value"] for a in sdrf_prefill.prefill(evidence(tmp_path, record, FILES))["acquisition"]] == ["DIA"]


def test_files_are_listed_and_search_parameter_files_found(tmp_path):
    files = sdrf_prefill.prefill(evidence(tmp_path, RECORD, FILES))["files"]
    assert files["run_files"] == ["a.raw", "b.raw"] and files["run_count"] == 2
    assert files["search_parameter_files"] == ["mqpar.xml"]
    assert files["urls"] == {"mqpar.xml": "https://example.org/mqpar.xml"}
    assert "a.pride.mztab.gz" in files["result_files"] and "notes.txt" not in files["result_files"]


def test_missing_fields_are_left_out_not_invented(tmp_path):
    out = sdrf_prefill.prefill(evidence(tmp_path, {"accession": "PXD000002"}, {"files": []}))
    assert out["organism"] == [] and out["instrument"] == [] and out["disease"] == []
    assert out["files"]["run_count"] == 0

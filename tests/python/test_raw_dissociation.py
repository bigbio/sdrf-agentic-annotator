"""Tests for bin/raw_dissociation.py. Run with: PYTHONPATH=bin python -m pytest tests/python"""
import json

import raw_dissociation as rd
import sdrf_prefill


def header(*lines):
    """A fake Thermo RAW header: the magic bytes, `Finnigan`, then method text as UTF-16."""
    return b"\x01\xa1" + "Finnigan".encode("utf-16le") + b"\x00" * 40 + "\r\n".join(lines).encode("utf-16le")


def decide(*heads):
    return rd.decide([rd.parse_method(h) for h in heads])


def test_activation_type_lines_name_the_method():
    value, _ = decide(header("Scan Event Details:", "Activation Type: HCD", "Normalized Coll. Energy: 35.0", "Activation Type: HCD"))
    assert value["types"] == ["HCD"] and value["confidence"] == "high" and value["rule"] == "A"
    assert value["sdrf"] == ["NT=beam-type collision-induced dissociation;AC=MS:1000422"]


def test_the_fusion_layout_and_a_second_type_is_ambiguous():
    value, _ = decide(header("ActivationType = CID", "Collision Energy (%) = 35", "ActivationType = ETD"))
    assert value["types"] == ["CID", "ETD"] and value["ambiguous"] and value["confidence"] == "low"


def test_the_q_exactive_xml_tag_needs_an_energy_above_zero():
    assert decide(header('<Fragmentation_HCD FullInternalName="decimal?">0</Fragmentation_HCD>'))[0] is None
    value, _ = decide(header('<Fragmentation_HCD FullInternalName="decimal?">27</Fragmentation_HCD>', "In-source CID 0.0 eV"))
    assert value["types"] == ["HCD"] and value["rule"] == "B"


def test_a_legacy_ion_trap_method_is_cid_with_medium_confidence():
    value, _ = decide(header("MS2 Activation Q: 0.250", "MS2 Activation Time: 30.000"))
    assert value["types"] == ["CID"] and value["confidence"] == "medium" and value["rule"] == "C"


def test_files_that_disagree_are_ambiguous():
    value, _ = decide(header("Activation Type: CID"), header("Activation Type: HCD"))
    assert value["ambiguous"]


def test_a_file_that_is_not_a_thermo_raw_gives_no_value():
    value, reason = decide(b"not a raw file")
    assert value is None and "Thermo" in reason


def test_a_method_without_an_activation_type_gives_no_value():
    value, reason = decide(header("Detector Type = Orbitrap"))
    assert value is None and "no activation type" in reason


def test_prefill_carries_the_raw_value_as_a_fact(tmp_path):
    out = {"value": {"types": ["CID"], "sdrf": ["NT=collision-induced dissociation;AC=MS:1000133"], "confidence": "high", "ambiguous": False}, "files": [{"file": "a.raw", "types": {"CID": 3}, "evidence": ["Activation Type: CID"]}]}
    path = tmp_path / "d.json"
    path.write_text(json.dumps(out))
    facts = sdrf_prefill.dissociation_facts(path)
    assert facts[0]["value"].endswith("MS:1000133") and facts[0]["basis"] == "raw" and facts[0]["evidence"] == ["Activation Type: CID"]
    assert sdrf_prefill.dissociation_facts(tmp_path / "missing.json") == []


def test_a_busy_server_is_retried_with_a_back_off(monkeypatch):
    import urllib.error

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        return "ok"

    monkeypatch.setattr(rd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rd.time, "sleep", lambda s: None)
    assert rd.open_url("u", 5) == "ok" and len(calls) == 3


def test_other_errors_are_not_retried(monkeypatch):
    import urllib.error

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    monkeypatch.setattr(rd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rd.time, "sleep", lambda s: None)
    try:
        rd.open_url("u", 5)
        raise AssertionError("expected an error")
    except urllib.error.HTTPError as e:
        assert e.code == 404 and len(calls) == 1

from sdrf_agentic_annotator.models import Bundle, Verdict, STATUSES

def test_status_set_has_core_states():
    for s in ["candidate", "claimed", "ready", "escalate", "merged", "blocked"]:
        assert s in STATUSES

def test_bundle_json_roundtrip():
    b = Bundle(accession="PXD000001", repository="pride",
               organisms=[("Homo sapiens", "9606")], instruments=["Q Exactive"],
               files=[{"name": "a.raw", "ext": "raw"}], deposited_sdrf=None,
               labels=["control"], protocol={"enzyme": "Trypsin"}, gaps=["organism part"])
    assert Bundle.from_json(b.to_json()) == b

def test_verdict_defaults():
    v = Verdict(passed=True, errors=[], collisions=0, ragged=0)
    assert v.passed and v.collisions == 0

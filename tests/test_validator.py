from pathlib import Path
from sdrf_agentic_annotator.validator import structural_check, validate

FIX = Path(__file__).parent / "fixtures"

def test_structural_check_detects_ragged_and_collisions():
    ragged, collide = structural_check(FIX / "collide.sdrf.tsv")
    assert collide == 1        # two rows share source/biorep/techrep/fraction
    assert ragged == 0

def test_validate_structural_only_passes_good(tmp_path):
    v = validate(FIX / "good.sdrf.tsv", run_cli=False)
    assert v.passed and v.collisions == 0 and v.ragged == 0

def test_validate_structural_only_fails_collision():
    v = validate(FIX / "collide.sdrf.tsv", run_cli=False)
    assert not v.passed and v.collisions == 1

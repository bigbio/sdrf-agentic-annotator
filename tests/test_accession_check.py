from pathlib import Path
from sdrf_agentic_annotator.validator import accession_check, normalise_term

LABELS = {
    "MS:1001251": "trypsin",
    "MS:1001252": "db source ebi",
    "UBERON:0001044": "salivary gland",
    "NCBITAXON:1772": "mycobacterium smegmatis",
}

def _write(tmp_path, rows):
    p = tmp_path / "x.sdrf.tsv"
    p.write_text("comment[cleavage agent details]\tcharacteristics[organism part]\n" +
                 "\n".join(rows) + "\n")
    return p

def test_normalise_collapses_separators_and_case():
    assert normalise_term("Saliva-Secreting  gland") == "saliva secreting gland"

def test_flags_wrong_accession(tmp_path):
    p = _write(tmp_path, ["NT=Trypsin;AC=MS:1001252\tNT=salivary gland;AC=UBERON:0001044"])
    bad = accession_check(p, LABELS)
    # Trypsin->MS:1001252 is 'db source ebi' => mismatch flagged; salivary gland exact-matches its label here (synonym tolerance is covered by test_substring_synonym_not_flagged)
    assert ("Trypsin", "MS:1001252", "db source ebi") in bad
    assert all(nt != "salivary gland" for nt, _, _ in bad)

def test_correct_accession_not_flagged(tmp_path):
    p = _write(tmp_path, ["NT=Trypsin;AC=MS:1001251\tnot available"])
    assert accession_check(p, LABELS) == []

def test_unknown_accession_skipped(tmp_path):
    p = _write(tmp_path, ["NT=Foo;AC=MS:9999999\tnot available"])
    assert accession_check(p, LABELS) == []

def test_substring_synonym_not_flagged(tmp_path):
    # organism name is a prefix of the cache strain label -> substring -> tolerated, not flagged
    p = _write(tmp_path, ["NT=Trypsin;AC=MS:1001251\tnot available"])
    # reuse an organism NT that is a substring of its cache label
    p.write_text("characteristics[organism]\n"
                 "NT=mycobacterium smegmatis mc2 155;AC=NCBITaxon:1772\n")
    assert accession_check(p, LABELS) == []

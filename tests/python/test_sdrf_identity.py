import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))
import sdrf_identity  # noqa: E402

HEAD = "source name\tcharacteristics[biological replicate]\tcomment[technical replicate]\tcomment[data file]\n"


def sdrf(tmp_path, rows, head=HEAD):
    p = tmp_path / "PXD1.sdrf.tsv"
    p.write_text(head + "".join("\t".join(r) + "\n" for r in rows))
    return p


def test_distinct_sources_per_biological_replicate_pass(tmp_path):
    p = sdrf(tmp_path, [("s1", "1", "1", "a.raw"), ("s2", "2", "1", "b.raw"), ("s3", "3", "1", "c.raw")])
    assert sdrf_identity.problems(p) == []


def test_technical_repeats_of_one_sample_pass(tmp_path):
    p = sdrf(tmp_path, [("s1", "1", "1", "a.raw"), ("s1", "1", "2", "b.raw")])
    assert sdrf_identity.problems(p) == []


def test_source_reused_for_two_biological_replicates_is_a_problem(tmp_path):
    p = sdrf(tmp_path, [("s1", "1", "1", "a.raw"), ("s1", "2", "1", "b.raw"), ("s2", "1", "1", "c.raw")])
    found = sdrf_identity.problems(p)
    assert found == [("s1", ["1", "2"])]


def test_replicate_values_sort_numerically(tmp_path):
    p = sdrf(tmp_path, [("s1", "10", "1", "a.raw"), ("s1", "2", "1", "b.raw")])
    assert sdrf_identity.problems(p) == [("s1", ["2", "10"])]


def test_no_replicate_column_is_not_checked(tmp_path):
    p = sdrf(tmp_path, [("s1", "a.raw"), ("s1", "b.raw")], head="source name\tcomment[data file]\n")
    assert sdrf_identity.problems(p) == []


def test_empty_source_name_rows_are_ignored(tmp_path):
    # unused multiplex channels have an empty source name
    p = sdrf(tmp_path, [("", "1", "1", "a.raw"), ("", "2", "1", "a.raw")])
    assert sdrf_identity.problems(p) == []


def test_section_names_the_sources_and_how_to_fix(tmp_path):
    p = sdrf(tmp_path, [("s1", "1", "1", "a.raw"), ("s1", "2", "1", "b.raw")])
    text = sdrf_identity.section(p)
    assert "BLOCKER" in text and "s1" in text and "distinct source name" in text


def test_section_is_short_and_clean_when_nothing_is_wrong(tmp_path):
    p = sdrf(tmp_path, [("s1", "1", "1", "a.raw")])
    assert "No source name" in sdrf_identity.section(p)
    assert "BLOCKER" not in sdrf_identity.section(p)


def test_section_lists_at_most_ten_sources(tmp_path):
    rows = [(f"s{i}", r, "1", f"{i}{r}.raw") for i in range(30) for r in ("1", "2")]
    text = sdrf_identity.section(sdrf(tmp_path, rows))
    assert text.count("biological replicate 1, 2") == 10 and "30 source names" in text and "20 more" in text

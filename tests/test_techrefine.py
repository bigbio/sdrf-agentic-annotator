import os
import stat
from pathlib import Path

from sdrf_agentic_annotator.techrefine import _diff_cells, techrefine


def test_diff_cells_reports_changed_columns():
    old = "source name\tcomment[instrument]\nS1\tNT=Wrong\nS2\tNT=Wrong"
    new = "source name\tcomment[instrument]\nS1\tAC=MS:1001910;NT=LTQ Orbitrap Elite\nS2\tAC=MS:1001910;NT=LTQ Orbitrap Elite"
    ch = _diff_cells(old, new)
    assert (
        "comment[instrument]",
        "NT=Wrong",
        "AC=MS:1001910;NT=LTQ Orbitrap Elite",
    ) in ch
    assert len({c[0] for c in ch}) == 1


def test_techrefine_missing_binary_degrades_gracefully():
    out = techrefine(
        "PXD1", "source name\tassay name\nS1\tA1", cmd=("definitely_not_a_binary_xyz",)
    )
    assert out["ok"] is False
    assert out["text"].startswith("source name")  # input returned unchanged
    assert out["changes"] == []


def _fake_techsdrf(tmp_path: Path) -> Path:
    """A stub that mimics `techsdrf refine ... -s IN -o OUT` by writing an SDRF
    with the instrument column empirically corrected."""
    script = tmp_path / "faketech"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "a = sys.argv\n"
        "inp = a[a.index('-s') + 1]; out = a[a.index('-o') + 1]\n"
        "lines = open(inp).read().splitlines()\n"
        "h = lines[0].split('\\t'); j = h.index('comment[instrument]')\n"
        "rows = []\n"
        "for ln in lines[1:]:\n"
        "    c = ln.split('\\t');\n"
        "    if len(c) > j: c[j] = 'AC=MS:1001910;NT=LTQ Orbitrap Elite'\n"
        "    rows.append('\\t'.join(c))\n"
        "open(out, 'w').write('\\n'.join([lines[0]] + rows) + '\\n')\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_techrefine_applies_empirical_change(tmp_path):
    fake = _fake_techsdrf(tmp_path)
    sdrf = (
        "source name\tassay name\tcomment[instrument]\nS1\tA1\tNT=Guessed;AC=MS:9999999"
    )
    out = techrefine("PXD1", sdrf, cmd=(str(fake),), env={**os.environ})
    assert out["ok"] is True
    assert "AC=MS:1001910;NT=LTQ Orbitrap Elite" in out["text"]
    assert any(c[0] == "comment[instrument]" for c in out["changes"])


def test_techrefine_passes_flags(tmp_path):
    # a stub that records argv so we can assert -n and --skip-ptm are forwarded
    script = tmp_path / "argcap"
    argv_dump = tmp_path / "argv.txt"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_dump)!r}, 'w').write(' '.join(sys.argv))\n"
        "a = sys.argv; out = a[a.index('-o') + 1]\n"
        "open(out, 'w').write(open(a[a.index('-s') + 1]).read())\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    techrefine(
        "PXD1",
        "source name\nS1",
        n_files=5,
        skip_ptm=True,
        cmd=(str(script),),
        env={**os.environ},
    )
    argv = argv_dump.read_text()
    assert "-n 5" in argv
    assert "--skip-ptm" in argv
    assert "-p PXD1" in argv


def test_family_signature_groups_by_instrument_words():
    from sdrf_agentic_annotator.techrefine import family_signature

    # differ only in replicate/fraction numbers -> same family
    assert family_signature("LTQ_sample1_F01.raw") == family_signature(
        "LTQ_sample2_F03.raw"
    )
    # different instrument words -> different family
    assert family_signature("LTQ_s1.raw") != family_signature("Orbitrap_LTQ_s1.raw")


def test_is_thermo():
    from sdrf_agentic_annotator.techrefine import is_thermo

    assert is_thermo("a.raw") and is_thermo("a.RAW") and is_thermo("a.raw.gz")
    assert not is_thermo("a.wiff") and not is_thermo("a.d") and not is_thermo("a.mgf")


def test_representative_files_samples_across_families():
    from sdrf_agentic_annotator.techrefine import representative_files

    files = [
        "LTQ_1.raw",
        "LTQ_2.raw",
        "Orbitrap_LTQ_1.raw",
        "Orbitrap_LTQ_2.raw",
        "x.wiff",
    ]
    reps = representative_files(files, per_family=1)
    # one from each of the two Thermo families; the .wiff is excluded
    assert len([f for f in reps if "orbitrap" in f.lower()]) == 1
    assert len([f for f in reps if f.lower().startswith("ltq")]) == 1
    assert "x.wiff" not in reps


def test_representative_files_respects_cap():
    from sdrf_agentic_annotator.techrefine import representative_files

    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    files = [f"{w}_run_1.raw" for w in names]  # 6 distinct families
    assert len(representative_files(files, per_family=1, cap=3)) == 3


def test_techrefine_dataset_per_family_merge():
    from sdrf_agentic_annotator.techrefine import techrefine_dataset

    header = "source name\tcomment[data file]\tcomment[instrument]"
    sdrf = (
        f"{header}\n"
        "S1\tLTQ_1.raw\tNT=guess\n"
        "S2\tLTQ_2.raw\tNT=guess\n"
        "S3\tOrbitrapFusion_1.raw\tNT=guess\n"
    )

    def fake_run(acc, subset_text, n_files=1, **kw):
        # return a per-family instrument based on which family's files are present
        lines = subset_text.splitlines()
        instr = (
            "AC=MS:1001910;NT=LTQ Orbitrap Elite"
            if "LTQ_" in subset_text and "Fusion" not in subset_text
            else "AC=MS:1002416;NT=Orbitrap Fusion"
        )
        h = lines[0].split("\t")
        j = h.index("comment[instrument]")
        out = [lines[0]]
        for ln in lines[1:]:
            c = ln.split("\t")
            c[j] = instr
            out.append("\t".join(c))
        return {"ok": True, "text": "\n".join(out) + "\n", "changes": []}

    res = techrefine_dataset("PXD1", sdrf, per_family=1, run=fake_run)
    assert res["ok"] is True
    rows = {r.split("\t")[0]: r for r in res["text"].splitlines()[1:]}
    assert "LTQ Orbitrap Elite" in rows["S1"] and "LTQ Orbitrap Elite" in rows["S2"]
    assert "Orbitrap Fusion" in rows["S3"]  # different family -> different instrument
    assert len(res["families"]) == 2


def test_techrefine_dataset_skips_non_thermo():
    from sdrf_agentic_annotator.techrefine import techrefine_dataset

    sdrf = "source name\tcomment[data file]\tcomment[instrument]\nS1\ta.wiff\tNT=x\n"
    called = []

    def fake_run(acc, text, n_files=1, **kw):
        called.append(text)
        return {"ok": True, "text": text}

    res = techrefine_dataset("PXD1", sdrf, run=fake_run)
    assert res["ok"] is False  # no Thermo files -> nothing analyzed
    assert called == []


def test_techrefine_dataset_preserves_repeated_mod_columns():
    from sdrf_agentic_annotator.techrefine import techrefine_dataset

    # 2 split modification columns must NOT be corrupted by the merge
    header = "source name\tcomment[data file]\tcomment[instrument]\tcomment[modification parameters]\tcomment[modification parameters]"
    sdrf = f"{header}\nS1\ta.raw\tNT=guess\tNT=Carbamidomethyl;AC=UNIMOD:4\tNT=Oxidation;AC=UNIMOD:35\n"

    def fake_run(acc, subset, n_files=1, **kw):
        lines = subset.splitlines()
        h = lines[0].split("\t")
        j = h.index("comment[instrument]")
        out = [lines[0]]
        for ln in lines[1:]:
            c = ln.split("\t")
            c[j] = "AC=MS:1000449;NT=LTQ Orbitrap"
            out.append("\t".join(c))
        return {"ok": True, "text": "\n".join(out) + "\n", "changes": []}

    res = techrefine_dataset("PXD1", sdrf, per_family=1, run=fake_run)
    row = res["text"].splitlines()[1]
    assert "NT=Carbamidomethyl;AC=UNIMOD:4" in row  # both mods intact
    assert "NT=Oxidation;AC=UNIMOD:35" in row
    assert "LTQ Orbitrap" in row  # single-instance instrument still enriched

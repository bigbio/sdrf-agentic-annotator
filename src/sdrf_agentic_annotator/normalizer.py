from __future__ import annotations

ACQ_CV = {
    "DDA": "NT=Data-dependent acquisition;AC=PRIDE:0000627",
    "DIA": "NT=Data-independent acquisition;AC=PRIDE:0000450",
}


def _insert_after(header, rows, anchor, name, value):
    if name in header:
        return header, rows
    idx = (header.index(anchor) + 1) if anchor in header else len(header)
    header = header[:idx] + [name] + header[idx:]
    rows = [r[:idx] + [value] + r[idx:] for r in rows]
    return header, rows


def normalize_sdrf(text: str, acquisition: str = "DDA") -> str:
    lines = text.splitlines()
    if not lines:
        return text
    header = [c.strip() for c in lines[0].split("\t")]
    rows = [[c.strip() for c in ln.split("\t")] for ln in lines[1:] if ln != ""]
    rows = [r + ["not available"] * (len(header) - len(r)) if len(r) < len(header) else r
            for r in rows]
    header, rows = _insert_after(header, rows, "assay name", "technology type",
                                 "proteomic profiling by mass spectrometry")
    header, rows = _insert_after(header, rows, "technology type",
                                 "comment[proteomics data acquisition method]",
                                 ACQ_CV.get(acquisition, ACQ_CV["DDA"]))
    if "comment[fraction identifier]" in header:
        fi = header.index("comment[fraction identifier]")
        for r in rows:
            if fi < len(r) and r[fi] == "not applicable":
                r[fi] = "1"
    return "\t".join(header) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"

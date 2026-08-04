"""Build the Qwen drafting prompt from a dataset's evidence.

Formalizes (and makes testable) the system+user messages proven on PXD016837:
columns are presented in physical SDRF order, required+recommended only (the
model may append relevant optionals), with the CV / v1.1.0 / fraction rules and
"NT-only when unsure of an accession" guidance that made the self-repair loop
converge. The raw filenames + full submitter protocols are the evidence body.
"""

from __future__ import annotations

from .draft import physical_order
from .template import combine

_RAW_EXTS = frozenset({"raw", "wiff", "d", "raw.gz", "wiff.gz"})

SYSTEM = (
    "You are an expert proteomics data curator creating an SDRF-Proteomics "
    "annotation file.\n"
    "OUTPUT: ONLY a tab-separated file - one header row then exactly one row per "
    "raw data file. No prose, no markdown fences.\n"
    "RULES:\n"
    "- Use the columns listed by the user, IN THAT ORDER (physical SDRF layout: "
    "source name, characteristics[...], assay name, technology type, comment[...]). "
    "You MAY append extra relevant comment[...] columns if evidence supports them.\n"
    "- One row per raw file; the raw filename goes in comment[data file].\n"
    "- 'technology type' = 'proteomic profiling by mass spectrometry'.\n"
    "- CV columns (instrument, label, cleavage agent details, dissociation method, "
    "proteomics data acquisition method) use NT=term name;AC=ONTOLOGY:ACCESSION "
    "when you are CERTAIN of the accession; otherwise give ONLY NT=term name and "
    "OMIT AC= (never guess an accession). Use standard PRIDE/MS controlled "
    "vocabulary values (e.g. label free sample; data-dependent acquisition).\n"
    "- 'characteristics[organism]' uses the NCBITaxon scientific name (e.g. Homo "
    "sapiens).\n"
    "- Fill EVERY cell: 'not applicable' when a column does not apply, 'not "
    "available' when unknown.\n"
    "- comment[sdrf version] = v1.1.0 . comment[fraction identifier] is an integer "
    "starting at 1 (not 'not applicable').\n"
    "- Keep (source name, characteristics[biological replicate], comment[technical "
    "replicate], comment[fraction identifier]) unique across rows.\n"
)


def _raw_files(bundle) -> list[str]:
    return [
        f.get("name", "")
        for f in (getattr(bundle, "files", []) or [])
        if f.get("ext") in _RAW_EXTS
    ]


def target_columns(templates):
    """Required+recommended columns of the combined templates, physical order."""
    return [
        c
        for c in physical_order(combine(templates))
        if c.requirement in ("required", "recommended")
    ]


def build_messages(bundle, project: dict, templates, gaps=()) -> dict:
    """Return {messages, n_raw, n_cols} for the drafting prompt."""
    cols = target_columns(templates)
    raws = _raw_files(bundle)
    colspec = "\n".join(
        f"  {i + 1}. {c.name}  [{c.requirement}]" for i, c in enumerate(cols)
    )
    acc = getattr(bundle, "accession", "")
    parts = [
        f"DATASET: {acc}",
        f"TITLE: {project.get('title', '')}",
        f"ORGANISM(S): {getattr(bundle, 'organisms', [])}",
        f"INSTRUMENT(S): {getattr(bundle, 'instruments', [])}",
        "",
        "SAMPLE PROCESSING PROTOCOL:",
        str(project.get("sampleProcessingProtocol", "") or ""),
        "",
        "DATA PROCESSING PROTOCOL:",
        str(project.get("dataProcessingProtocol", "") or ""),
        "",
        f"RAW DATA FILES ({len(raws)}):",
        "\n".join(raws),
        "",
        (
            f"SDRF COLUMNS (templates: {', '.join(templates)}) - use these exact "
            "names, in this order:"
        ),
        colspec,
    ]
    if gaps:
        parts += ["", "Resolve especially from the protocol/title: " + ", ".join(gaps)]
    parts += ["", f"Produce the SDRF now: header row + {len(raws)} data rows."]
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(parts)},
        ],
        "n_raw": len(raws),
        "n_cols": len(cols),
    }

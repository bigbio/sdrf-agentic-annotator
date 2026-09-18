"""The raw-arm prompt. Identical for every raw model; only the evidence varies."""

from __future__ import annotations

from sdrf_model_bench.evidence import Evidence, estimate_tokens

SYSTEM = """You annotate proteomics datasets in the SDRF-Proteomics format.

An SDRF is a tab-separated table with one row per raw file and sample (for multiplexed
labelling such as TMT: one row per raw file and channel). Use these columns when the
evidence supports them, in this order, and add factor value[...] columns for the
variables the study compares:

source name, characteristics[organism], characteristics[organism part],
characteristics[disease], characteristics[cell type], characteristics[biological replicate],
assay name, technology type, comment[data file], comment[technical replicate],
comment[fraction identifier], comment[label], comment[instrument],
comment[cleavage agent details], comment[modification parameters] (repeat the column once
per modification), comment[precursor mass tolerance], comment[fragment mass tolerance],
comment[proteomics data acquisition method], factor value[<variable>]

Cell conventions:
- ontology terms as key=value pairs, e.g. NT=breast carcinoma;AC=EFO:0000305
- organism as the NCBI taxonomy name in lower case, e.g. homo sapiens
- label e.g. AC=MS:1002038;NT=label free sample or AC=MS:1002616;NT=TMT126
- modification e.g. NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed
- tolerance e.g. 10 ppm or 0.02 Da
- write 'not available' only when the evidence really does not say
- comment[data file] must use the exact raw file names given

Reply with the complete SDRF inside one ```tsv fenced block and nothing else."""

PRIDE_FIELDS = [
    ("Title", "title"), ("Description", "projectDescription"),
    ("Sample processing protocol", "sampleProcessingProtocol"),
    ("Data processing protocol", "dataProcessingProtocol"),
]
PRIDE_LISTS = [
    ("Organisms", "organisms"), ("Organism parts", "organismParts"), ("Diseases", "diseases"),
    ("Instruments", "instruments"), ("Modifications", "identifiedPTMStrings"),
    ("Quantification", "quantificationMethods"), ("Experiment types", "experimentTypes"),
]


def _names(items) -> str:
    out = []
    for it in items or []:
        out.append(it.get("name", "") if isinstance(it, dict) else str(it))
    return "; ".join(x for x in out if x)


def render_pride(pride: dict, text_limit: int | None = None) -> str:
    lines = []
    for label, key in PRIDE_FIELDS:
        val = (pride.get(key) or "").strip()
        if text_limit is not None:
            val = val[:text_limit]
        if val:
            lines.append(f"{label}: {val}")
    for label, key in PRIDE_LISTS:
        val = _names(pride.get(key))
        if val:
            lines.append(f"{label}: {val}")
    kw = pride.get("keywords")
    if kw:
        lines.append("Keywords: " + (", ".join(kw) if isinstance(kw, list) else str(kw)))
    return "\n".join(lines)


def build_messages(ev: Evidence, manuscript: bool, budget_tokens: int = 24000) -> tuple[list[dict], dict]:
    """Assemble the prompt. Over budget, the manuscript is cut first, then the PRIDE free text."""
    files = "\n".join(ev.files)
    pride = render_pride(ev.pride)
    ms = ev.manuscript if manuscript else ""
    fixed = estimate_tokens(files)
    truncated = False
    room = budget_tokens - fixed - estimate_tokens(pride)
    if ms and estimate_tokens(ms) > room:
        ms = ms[: max(0, room) * 4]
        truncated = True
    if fixed + estimate_tokens(pride) + estimate_tokens(ms) > budget_tokens:
        limit = 4000
        while limit > 200 and fixed + estimate_tokens(render_pride(ev.pride, limit)) > budget_tokens:
            limit //= 2
        pride = render_pride(ev.pride, limit)
        truncated = True

    parts = [f"Dataset: {ev.accession}", "", "## Repository metadata (PRIDE)", pride, "",
             f"## Raw files ({len(ev.files)})", files]
    if ms:
        parts += ["", "## Manuscript excerpt (methods and sample-related legends)", ms]
    parts += ["", "Create the SDRF for this dataset."]
    user = "\n".join(parts)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    info = {
        "evidence_tokens": estimate_tokens(pride) + fixed + estimate_tokens(ms),
        "prompt_tokens": estimate_tokens(SYSTEM) + estimate_tokens(user),
        "truncated": truncated,
    }
    return messages, info

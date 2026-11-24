#!/usr/bin/env python3
"""Write an evidence sheet that the annotate agent starts from, without calling a model.

usage: sdrf_sheet.py EVIDENCE_DIR PREFILL.json OUT_PREFIX [--ontology-dir DIR] [--corpus-index TSV]

Reads evidence/manuscript.txt, evidence/pride.json and evidence/files.json (written by `sdrf-tools fetch`)
and <PXD>.prefill.json (bin/sdrf_prefill.py). Writes OUT_PREFIX.sheet.md for the agent and
OUT_PREFIX.sheet.json for tests and measurement. Every value names its source: the sentence it was
found in, the file names, or the corpus accession. A value found by a pattern is marked `confirm`.
"""
import re

# ---------------------------------------------------------------- methods excerpt

METHODS_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:materials?\s+and\s+methods|methods(?:\s+and\s+materials?)?|"
    r"experimental\s+(?:procedures?|section|design)|sample\s+preparation|lc-?ms(?:/ms)?(?:\s+analysis)?|"
    r"mass\s+spectrometry(?:\s+analysis)?|data\s+(?:analysis|processing)|database\s+search(?:ing)?|"
    r"proteomic\s+analysis|star\s*★?\s*methods)\b[\w\s/,-]{0,60}$",
    re.IGNORECASE,
)
STOP_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:results(?:\s+and\s+discussion)?|discussion|references|bibliography|"
    r"acknowledge?ments?|conclusions?|supplementary|supporting\s+information|author\s+contributions|"
    r"funding|conflicts?\s+of\s+interest|competing\s+interests?)\b[\w\s,-]{0,40}$",
    re.IGNORECASE,
)
KEY_TERMS = re.compile(
    r"\b(?:ppm|Da|mmu|toleran\w+|missed\s+cleavage|trypsin|lys-?c|chymotrypsin|gluc|aspn|digest\w*|TMT|iTRAQ|SILAC|"
    r"label\w*|fraction\w*|orbitrap|exploris|q\s*exactive|timstof|astral|lumos|eclipse|fusion|tripletof|synapt|"
    r"DIA|DDA|SWATH|HCD|CID|ETD|EThcD|carbamidomethyl\w*|oxidation|phospho\w*|acetyl\w*|cell\s+line|cells|tissue|"
    r"patients?|mice|mouse|rats?|plasma|serum|biops\w+|enrich\w*)\b",
    re.IGNORECASE,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")


def sentences(text):
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]


def _is_heading(line, pattern):
    return len(line.strip()) <= 90 and bool(pattern.match(line))


def methods_excerpt(text, limit=6000):
    """The Methods part of a manuscript, cut to `limit` characters keeping the sentences with key terms first."""
    headings, kept, inside = [], [], False
    for line in (text or "").splitlines():
        if _is_heading(line, STOP_HEADING):
            inside = False
            continue
        if _is_heading(line, METHODS_HEADING):
            inside = True
            headings.append(line.strip())
            kept.append(line.strip())
            continue
        if inside and line.strip():
            kept.append(line.strip())
    if not headings:
        return {"found": False, "headings": [], "text": ""}
    body = "\n".join(kept)
    if len(body) <= limit:
        return {"found": True, "headings": headings, "text": body}
    # too long: keep sentences with key terms first, then the others, and print them in their original order
    units = [s for para in kept for s in sentences(para)]
    order = sorted(range(len(units)), key=lambda i: (KEY_TERMS.search(units[i]) is None, i))
    chosen, size = set(), 0
    for i in order:
        if size + len(units[i]) + 1 > limit:
            continue
        chosen.add(i)
        size += len(units[i]) + 1
    return {"found": True, "headings": headings, "text": "\n".join(units[i] for i in sorted(chosen))}


# ---------------------------------------------------------------- search settings

TOLERANCE = re.compile(r"(?:±|\+/-|\+-)?\s*(\d+(?:\.\d+)?)\s*(ppm|Da|mmu|Th)\b")
PRECURSOR_WORDS = re.compile(r"precursor|parent|MS1\b|peptide\s+mass|first\s+search|main\s+search|(?<![/\w])MS\s+toleran", re.IGNORECASE)
FRAGMENT_WORDS = re.compile(r"fragment|MS/MS|MS2\b|product\s+ion|MS\s*/\s*MS", re.IGNORECASE)
NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "zero": "0", "no": "0"}
MISSED = (
    re.compile(r"\b(\d|one|two|three|four|five|zero|no)\s+(?:missed|miss-?)\s*cleavages?", re.IGNORECASE),
    re.compile(r"missed\s+cleavages?\D{0,40}?(\d)\b", re.IGNORECASE),
)
FRACTIONS = (
    re.compile(r"\b(\d{1,3})\s+(?:\w+\s+){0,2}fractions\b", re.IGNORECASE),
    re.compile(r"fractionated\s+into\s+(\d{1,3})\b", re.IGNORECASE),
)
ACQUISITION = ((re.compile(r"\bDIA\b|data[- ]independent|\bSWATH\b|\bdiaPASEF\b", re.IGNORECASE), "DIA"),
               (re.compile(r"\bDDA\b|data[- ]dependent|\bddaPASEF\b", re.IGNORECASE), "DDA"))
GRADIENT = (re.compile(r"\b(\d{1,3})[- ]?min(?:ute)?s?\s+(?:\w+\s+){0,2}gradient", re.IGNORECASE),
            re.compile(r"gradient\s+(?:of|over|for)\s+(\d{1,3})\s*min", re.IGNORECASE))


def _setting(field, value, sentence):
    return {"field": field, "value": value, "sentence": sentence, "basis": "text", "confirm": True}


def search_settings(text):
    """Search settings found by pattern, one item per distinct (field, value), each with its sentence."""
    found, seen = [], set()

    def add(field, value, sentence):
        if (field, value) not in seen:
            seen.add((field, value))
            found.append(_setting(field, value, sentence))

    for s in sentences(text or ""):
        start = 0
        for m in TOLERANCE.finditer(s):
            window = s[start:m.start()]
            start = m.end()
            pre = [x.end() for x in PRECURSOR_WORDS.finditer(window)]
            frag = [x.end() for x in FRAGMENT_WORDS.finditer(window)]
            if not pre and not frag:
                continue
            field = "fragment_tolerance" if (frag and (not pre or frag[-1] > pre[-1])) else "precursor_tolerance"
            add(field, f"{m.group(1)} {m.group(2)}", s)
        for pat in MISSED:
            m = pat.search(s)
            if m:
                add("missed_cleavages", NUMBER_WORDS.get(m.group(1).lower(), m.group(1)), s)
                break
        for pat in FRACTIONS:
            m = pat.search(s)
            if m:
                add("fractions", m.group(1), s)
                break
        for pat, label in ACQUISITION:
            if pat.search(s):
                add("acquisition", label, s)
        for pat in GRADIENT:
            m = pat.search(s)
            if m:
                add("gradient_minutes", m.group(1), s)
                break
    return found


# ---------------------------------------------------------------- design from file names

EXTENSIONS = re.compile(r"\.(raw|d|wiff2?|scan|mzml|mzxml|mgf|zip|gz|tar|tgz|7z|rar|bz2)$", re.IGNORECASE)
FRACTION_TOKEN = re.compile(r"^(?:f|fr|frac|fraction)\d+$", re.IGNORECASE)
REPLICATE_TOKEN = re.compile(r"^(?:r|rep|br|tr|bio|tech|replicate)\d+$", re.IGNORECASE)
TIMESTAMP_TOKEN = re.compile(r"^\d{6,}$")


def _stem(name):
    name = name.rsplit("/", 1)[-1]
    while EXTENSIONS.search(name):
        name = EXTENSIONS.sub("", name)
    return name


def filename_design(files, max_positions=8, max_values=12):
    """Positions of the file-name tokens that vary across the run files, with their values.

    Files are split on _ - . and space; only files with the most common token count are compared.
    A position whose value is the same in every file is dropped, and so is a timestamp (6+ digits).
    kind: fraction or replicate when every value looks like one, run when every file has its own value,
    condition otherwise.
    """
    split = [re.split(r"[_\-. ]+", _stem(f)) for f in files or []]
    if not split:
        return {"positions": [], "dropped": [], "compared": 0, "files": 0}
    lengths = {}
    for t in split:
        lengths[len(t)] = lengths.get(len(t), 0) + 1
    width = max(lengths, key=lambda n: (lengths[n], n))
    rows = [t for t in split if len(t) == width]
    dropped, positions = [], []
    for i in range(width):
        values = sorted({r[i] for r in rows})
        if len(values) == 1:
            dropped.append(values[0])
            continue
        if all(TIMESTAMP_TOKEN.match(v) for v in values):
            dropped.append(f"timestamp at position {i}")
            continue
        if all(FRACTION_TOKEN.match(v) for v in values):
            kind = "fraction"
        elif all(REPLICATE_TOKEN.match(v) for v in values):
            kind = "replicate"
        elif len(values) == len(rows):
            kind = "run"
        else:
            kind = "condition"
        positions.append({"index": i, "kind": kind, "n_values": len(values), "values": values[:max_values]})
    positions = sorted(sorted(positions, key=lambda p: p["n_values"])[:max_positions], key=lambda p: p["index"])
    return {"positions": positions, "dropped": dropped, "compared": len(rows), "files": len(split)}

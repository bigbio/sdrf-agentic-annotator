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

TOLERANCE = re.compile(r"(?:±|\+/-|\+-)?\s*(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)\b")
# the ion type named right after the number ("10 ppm for precursors", "4.5 ppm (precursor)") wins over the words before it
ION_WORD = re.compile(r"\b(precursor|parent|MS1|fragment|product|MS/MS|MS2)", re.IGNORECASE)
TRAILING_ION = re.compile(r"\s*(?:\(\s*|for\s+(?:the\s+)?)(precursor|parent|MS1|fragment|product|MS/MS|MS2)", re.IGNORECASE)
PRECURSOR_WORDS = re.compile(r"precursor|parent|MS1\b|peptide\s+mass|first\s+search|main\s+search|(?<![/\w])MS\s+toleran", re.IGNORECASE)
FRAGMENT_WORDS = re.compile(r"fragment|MS/MS|MS2\b|product\s+ion|MS\s*/\s*MS", re.IGNORECASE)
SEARCH_STAGE = re.compile(r"\s*(?:in|for|at|during)?\s*(?:the\s+)?(first|main)\s+search", re.IGNORECASE)
TOLERANCE_WORDS = re.compile(r"toleran|accuracy|error|deviation|\bset\s+(?:to|at)\b", re.IGNORECASE)
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
        tols = list(TOLERANCE.finditer(s))
        if len(tols) >= 2 and "respectively" in s.lower() and TOLERANCE_WORDS.search(s[:tols[0].start()]):
            # "10 ppm and 0.02 Da for precursor and fragment ions, respectively": numbers and ion types in order
            ions = ION_WORD.findall(s[tols[-1].end():])
            if len(ions) >= len(tols):
                for m, ion in zip(tols, ions):
                    field = "precursor_tolerance" if ion.lower() in ("precursor", "parent", "ms1") else "fragment_tolerance"
                    add(field, f"{m.group(1)} {m.group(2)}", s)
                tols = []
        for m in tols:
            window = s[start:m.start()]
            start = m.end()
            if "isolation" in window[-40:].lower() or not TOLERANCE_WORDS.search(s[:m.start()]):
                continue
            trail = TRAILING_ION.match(s[m.end():m.end() + 30])
            if trail:
                ion = trail.group(1).lower()
                field = "precursor_tolerance" if ion in ("precursor", "parent", "ms1") else "fragment_tolerance"
            else:
                pre = [x.end() for x in PRECURSOR_WORDS.finditer(window)]
                frag = [x.end() for x in FRAGMENT_WORDS.finditer(window)]
                if not pre and not frag:
                    continue
                field = "fragment_tolerance" if (frag and (not pre or frag[-1] > pre[-1])) else "precursor_tolerance"
            q = SEARCH_STAGE.match(s[m.end():m.end() + 30])
            add(field, f"{m.group(1)} {m.group(2)}" + (f" ({q.group(1).lower()} search)" if q else ""), s)
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
        elif len(values) == len(rows) and len(rows) >= 6:  # with few files, a token unique per file may be the condition
            kind = "run"
        else:
            kind = "condition"
        positions.append({"index": i, "kind": kind, "n_values": len(values), "values": values[:max_values]})
    positions = sorted(sorted(positions, key=lambda p: p["n_values"])[:max_positions], key=lambda p: p["index"])
    return {"positions": positions, "dropped": dropped, "compared": len(rows), "files": len(split)}


# ---------------------------------------------------------------- ontology term matches

# category -> (cache file, accession prefix kept). A term that an ontology imports from another
# (an uberon term inside mondo) is left out, so each term is reported once, under its own category.
CATEGORY_SOURCES = {
    "organism_part": [("uberon", "uberon:")],
    "cell_type": [("cl", "cl:")],
    "disease": [("mondo", "mondo:")],
    "modification": [("unimod", "unimod:")],
    "instrument": [("psi-ms", "ms:")],
}
INSTRUMENT_WORDS = re.compile(
    r"orbitrap|exploris|exactive|timstof|tripletof|synapt|ltq|astral|eclipse|lumos|fusion|zenotof|xevo|velos|elite|impact|maxis")
STOP_LABELS = {
    "cell", "cells", "tissue", "tissues", "protein", "proteins", "control", "sample", "samples", "organ", "part",
    "region", "system", "body", "line", "type", "material", "entity", "molecule", "compound", "disease",
    "disorder", "syndrome", "group", "time", "set", "label", "unknown", "other", "none", "instrument model",
}
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+/'-]*[A-Za-z0-9+]|[A-Za-z0-9]")


def _read_cache(directory, name):
    """Rows (accession, label) of <name>.parquet (pandas) or <name>.tsv; None when neither can be read."""
    from pathlib import Path
    base = Path(directory)
    if (base / f"{name}.tsv").exists():
        import csv
        with open(base / f"{name}.tsv", newline="") as fh:
            return [(r["accession"], r["label"]) for r in csv.DictReader(fh, delimiter="\t")]
    if (base / f"{name}.parquet").exists():
        try:
            import pandas as pd
        except ImportError:
            return None
        frame = pd.read_parquet(base / f"{name}.parquet", columns=["accession", "label"])
        return list(frame.itertuples(index=False, name=None))
    return None


DEFAULT_ONTOLOGY_DIR = "/opt/cache/sdrf-pipelines/ontologies"  # the caches of sdrf-pipelines in the runner image


def load_terms(ontology_dir):
    """{category: [{"label", "accession"}]} from the ontology caches, and the reason when none could be read.

    Without `ontology_dir`, the caches of sdrf-pipelines in the runner image are used when they are there.
    """
    from pathlib import Path
    if not ontology_dir and Path(DEFAULT_ONTOLOGY_DIR).is_dir():
        ontology_dir = DEFAULT_ONTOLOGY_DIR
    if not ontology_dir or not Path(ontology_dir).is_dir():
        return {}, f"no ontology cache folder ({ontology_dir})"
    terms = {}
    for category, sources in CATEGORY_SOURCES.items():
        for name, prefix in sources:
            rows = _read_cache(ontology_dir, name)
            for acc, label in rows or []:
                if not isinstance(label, str) or not str(acc).lower().startswith(prefix):
                    continue
                if category == "instrument" and not INSTRUMENT_WORDS.search(label.lower()):
                    continue
                terms.setdefault(category, []).append({"label": label, "accession": acc})
    if not terms:
        return {}, f"no readable ontology cache in {ontology_dir} (parquet needs pandas and pyarrow)"
    return terms, None


def _index(terms):
    """n-gram of lower-case tokens -> [(category, term)], and the longest n-gram length."""
    index, longest = {}, 1
    for category, items in terms.items():
        for term in items:
            label = (term.get("label") or "").strip()
            if not label or label.lower() in STOP_LABELS:
                continue
            key = tuple(t.lower() for t in TOKEN.findall(label))
            if not key:
                continue
            index.setdefault(key, []).append((category, term))
            longest = max(longest, len(key))
    return index, longest


def _short_label_ok(label, span):
    """A label of fewer than 4 characters counts only where the text writes it in capitals or with a digit."""
    return len(label) >= 4 or span.isupper() or any(c.isdigit() for c in span)


# reagents and phrases whose words are also ontology labels (dimethyl, milk, serum, blood): masked before matching
REAGENT_PHRASES = re.compile(
    r"dimethyl\s+sulfoxide|non-?\s*fat\s+(?:dry\s+)?milk|skim(?:med)?\s+milk|milk\s+powder|"
    r"(?:fetal|foetal|newborn)\s+(?:bovine|calf)\s+serum|bovine\s+serum\s+albumin|horse\s+serum|goat\s+serum|"
    r"blood\s+donors?|methyl[-\s]\S*cyclodextrin", re.IGNORECASE)
CELL_CONTEXT = {"cell", "cells", "line", "lines", "cultures", "xenografts"}


def _mask(text):
    return REAGENT_PHRASES.sub(lambda m: " " * len(m.group(0)), text)


def _cell_line_ok(label, text, tokens, lower, i, n):
    """A cell line name counts with a digit or hyphen (K562, PC-3), or when 'cell(s)'/'line' follows within 3 words
    of the same sentence."""
    if re.search(r"[\d-]", label):
        return True
    prev = tokens[i + n - 1].end()
    for k in range(i + n, min(i + n + 3, len(tokens))):
        if re.search(r"[.;:!?]", text[prev:tokens[k].start()]):
            return False
        if lower[k] in CELL_CONTEXT:
            return True
        prev = tokens[k].end()
    return False


def term_matches(text, terms, known=None):
    """Whole-word matches of the term labels in `text`, longest first, by category, with count and first sentence.

    `known` ({category: set of lower-case values}) holds the values the annotated corpus uses in that column.
    When it is given, a one-word label counts only if the corpus uses it, so that common words that are also
    ontology labels (tube, acquired, impact) are not reported; labels of several words always count.
    """
    text = text or ""
    index, longest = _index(terms)
    tokens = list(TOKEN.finditer(_mask(text)))
    lower = [t.group(0).lower() for t in tokens]
    bounds = [m.end() for m in SENTENCE_SPLIT.finditer(text)] + [len(text)]
    hits = {}
    i = 0
    while i < len(tokens):
        matched = 0
        for n in range(min(longest, len(tokens) - i), 0, -1):
            key = tuple(lower[i:i + n])
            found = index.get(key)
            if not found and lower[i + n - 1].endswith("s"):  # plain plural of the last word
                found = index.get(key[:-1] + (key[-1][:-1],))
            if not found:
                continue
            span = text[tokens[i].start():tokens[i + n - 1].end()]
            for category, term in found:
                if not _short_label_ok(term["label"], span):
                    continue
                if known is not None and n == 1 and term["label"].lower() not in known.get(category, set()):
                    continue
                if category == "instrument" and n == 1:  # "orbitrap" names a family, not a model
                    continue
                if category == "cell_line" and not _cell_line_ok(term["label"], text, tokens, lower, i, n):
                    continue
                entry = hits.setdefault(category, {}).get(term["label"])
                if entry is None:
                    start = max([0] + [b for b in bounds if b <= tokens[i].start()])
                    end = min(b for b in bounds if b >= tokens[i + n - 1].end())
                    hits[category][term["label"]] = entry = {
                        "label": term["label"], "accession": term.get("accession"), "count": 0,
                        "sentence": text[start:end].strip(),
                        "at": tokens[i].start() - start - (len(text[start:end]) - len(text[start:end].lstrip()))}
                entry["count"] += 1
                matched = n
            if matched:
                break
        i += matched or 1
    return {c: sorted(v.values(), key=lambda e: (-e["count"], e["label"])) for c, v in hits.items()}


# ---------------------------------------------------------------- corpus: known values and similar SDRFs

CORE = ("organism", "instrument", "label")
BIOLOGY = ("cell_line", "organism_part", "disease")
KNOWN = ("organism_part", "cell_type", "disease", "modification", "instrument", "cell_line")


def _read_index(index_path):
    import csv
    from pathlib import Path
    if not index_path or not Path(index_path).exists():
        return []
    import gzip
    opener = gzip.open if str(index_path).endswith(".gz") else open
    with opener(index_path, "rt", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def label_class(value):
    """The labelling class of a label value: tmt, itraq, silac, dimethyl or label free (TMT126 and TMT are both tmt)."""
    v = value.lower()
    for cls in ("tmt", "itraq", "silac", "dimethyl"):
        if v.startswith(cls) or cls in v.split():
            return cls
    return "label free" if "label free" in v or "label-free" in v else v


def _values(row, field):
    values = {v.lower() for v in (row.get(field) or "").split("|") if v}
    return {label_class(v) for v in values} if field == "label" else values


GENERIC_CELL_LINES = {"cell line", "cell lines", "cells", "cell", "pooled", "pool", "mixed", "mix", "control", "unknown",
                      "primary", "primary cells", "other", "multiple", "various", "none"}


def cell_line_name_ok(name):
    """A value that looks like a cell line name: letters, a capital or a digit as written, not a generic word."""
    name = (name or "").strip()
    return (len(name) >= 3 and bool(re.search(r"[A-Za-z]", name)) and bool(re.search(r"[A-Z0-9]", name))
            and not name.isdigit() and name.lower() not in GENERIC_CELL_LINES)


def corpus_terms(index_path, min_datasets=10, min_cell_line=2):
    """Cell line terms and {category: lower-case values}, both from the annotated corpus.

    A value counts when at least `min_datasets` corpus accessions use it in that column (a one-word ontology label is
    matched only if it counts, see term_matches). A cell line needs `min_cell_line` SDRFs and a cell-line-like name;
    a trailing " cell" or " cells" is dropped. The names keep the case the corpus writes them in.
    """
    rows = _read_index(index_path)
    if not rows:
        return [], None
    from collections import Counter
    # counted once per accession: one dataset with 93 SDRF files is one use, not 93
    by_acc = {}
    for r in rows:
        acc = by_acc.setdefault(r["accession"], {**{c: set() for c in KNOWN}, "names": set()})
        for c in KNOWN:
            acc[c] |= _values(r, c)
        acc["names"] |= {re.sub(r"\s+cells?$", "", x) for x in (r.get("cell_line") or "").split("|") if x}
    counts = {c: Counter() for c in KNOWN}
    names = {}
    for acc in by_acc.values():
        for c in KNOWN:
            counts[c].update(acc[c])
        for v in acc["names"]:
            if cell_line_name_ok(v):
                names.setdefault(v.lower(), Counter())[v] += 1
    lines = sorted(c.most_common(1)[0][0] for k, c in names.items() if sum(c.values()) >= min_cell_line)
    known = {c: {v for v, n in counts[c].items() if n >= min_datasets} for c in KNOWN}
    known["cell_line"] = {v.lower() for v in lines}
    return [{"label": v, "accession": None} for v in lines], known


def similar_sdrfs(index_path, facts, corpus_root, k=2, exclude=None):
    """Up to k corpus SDRFs sharing organism, instrument and label with `facts`, ranked by shared biology.

    `facts` maps a field to a set of lower-case values. Each result has the accession, the shared fields,
    the header, and the first three rows when the corpus checkout `corpus_root` is given.
    """
    import csv
    from pathlib import Path
    scored = []
    for r in _read_index(index_path):
        if exclude and r["accession"] == exclude:  # never the dataset itself, when it is already in the corpus
            continue
        want = dict(facts, label={label_class(v) for v in facts.get("label") or ()})
        if not all(_values(r, f) & set(want.get(f) or ()) for f in CORE):
            continue
        shared = [f for f in BIOLOGY if _values(r, f) & set(want.get(f) or ())]
        scored.append((len(shared), r["accession"], shared, r))
    scored.sort(key=lambda s: s[1], reverse=True)  # newer accession first among equals
    scored.sort(key=lambda s: -s[0])
    out = []
    for _, acc, shared, r in scored[:k]:
        header, rows = r["columns"].split("|"), []
        if corpus_root and (Path(corpus_root) / r["path"]).exists():
            with open(Path(corpus_root) / r["path"], newline="", encoding="utf-8", errors="replace") as fh:
                table = list(csv.reader(fh, delimiter="\t"))
            header, rows = table[0], table[1:4]
        out.append({"accession": acc, "shared": list(CORE) + shared, "header": header, "rows": rows})
    return out


# ---------------------------------------------------------------- render and command line

SECTION_TITLES = {"methods": "Methods excerpt", "terms": "Term matches", "settings": "Search settings",
                  "design": "Design from file names", "similar": "Similar SDRFs"}
CATEGORY_TITLES = {"cell_line": "cell line", "organism_part": "organism part", "cell_type": "cell type",
                   "disease": "disease", "modification": "modification", "instrument": "instrument"}


def _quote(sentence, n=220, at=0):
    """The sentence in quotes, cut to about n characters around position `at` (where the value is)."""
    sentence = sentence or ""
    if len(sentence) > n:
        lo = max(0, min(at - n // 3, len(sentence) - n))
        sentence = ("\u2026" if lo else "") + sentence[lo:lo + n] + ("\u2026" if lo + n < len(sentence) else "")
    return '"' + " ".join(sentence.split()) + '"'


def _render(sheet, excerpt_limit, terms_per_category, similar_rows):
    out = [f"# Evidence sheet for {sheet.get('accession') or ''}".rstrip(),
           "Built without a model from the PRIDE record, the manuscript and the deposited file names. Each value names "
           "its source. Values marked (confirm) were found by a pattern: confirm them before you use them. A missing "
           "value was not found here; it may still be in the manuscript.", ""]
    errors = sheet.get("errors") or {}
    m = sheet.get("methods") or {}
    out.append("## 1. Methods excerpt" + (f" (headings: {', '.join(m.get('headings')[:6])})" if m.get("headings") else ""))
    if m.get("found"):
        text = m.get("text") or ""
        out.append(text if len(text) <= excerpt_limit else text[:excerpt_limit].rsplit(" ", 1)[0] + " …")
    else:
        out.append("no manuscript methods found: use the PRIDE protocols and the manuscript itself")
    out += ["", "## 2. Term matches (ontology labels in the methods, title and PRIDE protocols)"]
    terms = sheet.get("terms") or {}
    if terms:
        for cat in CATEGORY_TITLES:
            items = terms.get(cat) or []
            if not items:
                continue
            out.append(f"### {CATEGORY_TITLES[cat]}")
            for t in items[:terms_per_category]:
                acc = f" ({t['accession']})" if t.get("accession") else ""
                out.append(f"- {t['label']}{acc}, {t['count']}x: {_quote(t.get('sentence'), at=t.get('at', 0))}")
            if len(items) > terms_per_category:
                out.append(f"- … {len(items) - terms_per_category} more")
    else:
        out.append("none found")
    if sheet.get("terms_note"):
        out.append(f"note: {sheet['terms_note']}")
    out += ["", "## 3. Search settings (confirm)"]
    for x in sheet.get("settings") or []:
        out.append(f"- {x['field'].replace('_', ' ')}: {x['value']} (confirm): {_quote(x['sentence'], at=max(0, x['sentence'].find(x['value'].split()[0])))}")
    if not sheet.get("settings"):
        out.append("none found")
    d = sheet.get("design") or {}
    out += ["", f"## 4. Design from file names ({d.get('files', 0)} run files, {d.get('compared', 0)} with the common name pattern)"]
    for p in d.get("positions") or []:
        more = f" (of {p['n_values']})" if p["n_values"] > len(p["values"]) else ""
        out.append(f"- token {p['index']} ({p['kind']}, {p['n_values']} values){more}: {', '.join(p['values'])}")
    if d.get("dropped"):
        out.append(f"- the same in every file: {', '.join(d['dropped'][:12])}")
    if not d.get("positions"):
        out.append("no varying name token")
    out += ["", "## 5. Similar SDRFs (a column set to compare with, not values for this dataset)"]
    for x in sheet.get("similar") or []:
        out.append(f"- {x['accession']} (shares {', '.join(x['shared'])}): columns {' | '.join(x['header'])}")
        for row in (x.get("rows") or [])[:similar_rows]:
            out.append("  " + " | ".join(row))
    if not sheet.get("similar"):
        out.append("none in the corpus with the same organism, instrument and label")
    if errors:
        out += ["", "## Not available"] + [f"- {SECTION_TITLES.get(k, k)}: {v}" for k, v in errors.items()]
    return "\n".join(out) + "\n"


def render(sheet, limit=12000):
    """The sheet as Markdown, at most `limit` characters: similar-SDRF rows go first, then the term tail, then the excerpt."""
    text = _render(sheet, 6000, 10**6, 3)
    for terms_per_category, similar_rows in ((10**6, 0), (5, 0)):
        if len(text) <= limit:
            return text
        text = _render(sheet, 6000, terms_per_category, similar_rows)
    if len(text) > limit:
        excerpt = len((sheet.get("methods") or {}).get("text") or "")
        text = _render(sheet, max(0, min(6000, excerpt) - (len(text) - limit) - 50), 5, 0)
    return text[:limit]


def _lower_values(items):
    return {str(i.get("value")).lower() for i in items or [] if i.get("value")}


def build_sheet(evidence_dir, prefill_path, ontology_dir=None, corpus_index=None):
    """All sections; a section that fails is left empty and named in `errors`."""
    import json
    from pathlib import Path
    ev = Path(evidence_dir)
    sheet = {"errors": {}}

    def section(name, fn, default):
        try:
            return fn()
        except Exception as e:  # the sheet must never fail the prefill task
            sheet["errors"][name] = f"{type(e).__name__}: {e}"[:300]
            return default

    record = section("record", lambda: json.loads((ev / "pride.json").read_text()), {})
    prefill = section("prefill", lambda: json.loads(Path(prefill_path).read_text()), {})
    sheet["accession"] = record.get("accession") or prefill.get("accession")
    manuscript = (ev / "manuscript.txt").read_text(errors="replace") if (ev / "manuscript.txt").exists() else ""
    sheet["methods"] = section("methods", lambda: methods_excerpt(manuscript), {"found": False, "headings": [], "text": ""})
    protocols = "\n".join(str(record.get(k) or "") for k in ("title", "sampleProcessingProtocol", "dataProcessingProtocol"))
    text = sheet["methods"]["text"] + "\n" + protocols

    def terms():
        found, reason = load_terms(ontology_dir)
        cell_lines, known = corpus_terms(corpus_index)
        if cell_lines:
            found["cell_line"] = cell_lines
        if reason and not cell_lines:
            sheet["errors"]["terms"] = reason
        elif reason:
            sheet["terms_note"] = reason + "; cell lines from the corpus only"
        return term_matches(text, found, known=known)

    sheet["terms"] = section("terms", terms, {})
    sheet["settings"] = section("settings", lambda: search_settings(text), [])
    run_files = (prefill.get("files") or {}).get("run_files") or []
    sheet["design"] = section("design", lambda: filename_design(run_files), {})
    facts = {"organism": _lower_values(prefill.get("organism")), "instrument": _lower_values(prefill.get("instrument")),
             "label": _lower_values(prefill.get("label"))}
    for cat in BIOLOGY:
        facts[cat] = {t["label"].lower() for t in sheet["terms"].get(cat) or []}
    sheet["similar"] = section("similar", lambda: similar_sdrfs(corpus_index, facts, None, exclude=sheet["accession"]), [])
    return sheet


def main(argv):
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("evidence_dir")
    ap.add_argument("prefill")
    ap.add_argument("out_prefix")
    ap.add_argument("--ontology-dir")
    ap.add_argument("--corpus-index")
    a = ap.parse_args(argv)
    try:
        sheet = build_sheet(a.evidence_dir, a.prefill, a.ontology_dir, a.corpus_index)
        text = render(sheet)
    except Exception as e:  # never fail the task: write what went wrong instead
        sheet = {"errors": {"sheet": f"{type(e).__name__}: {e}"[:300]}}
        text = f"# Evidence sheet\n\n## Not available\n- {sheet['errors']['sheet']}\n"
    Path(a.out_prefix + ".sheet.md").write_text(text)
    Path(a.out_prefix + ".sheet.json").write_text(json.dumps(sheet, indent=1, ensure_ascii=False, default=sorted) + "\n")
    print(f"wrote {a.out_prefix}.sheet.md: {len(text)} characters, errors: {sorted(sheet.get('errors') or {})}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))

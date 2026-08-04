"""Agentic self-repair drafting loop.

The drafter is not one-shot. Qwen generates an SDRF, we validate it (physical
column order + coordinate collisions + parse_sdrf ontology/pattern checks +
NT/AC accession consistency), and feed the *specific* failures back to the model
to regenerate — iterating until it validates clean or a round budget is hit.

This module is model-agnostic and headless-testable: ``run_repair_loop`` takes a
``generate(messages) -> text`` callable and a ``validate(text) -> {errors,
warnings}`` callable, so the loop logic is unit-tested with a fake model, and the
real run wires vLLM + ``validate_text`` at the edge (the GPU job).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .validator import accession_check, structural_check

# canonical SDRF physical layout: source name, characteristics[*], assay name,
# technology type, comment[*]
_SPECIAL_ORDER = {"source name": 0, "assay name": 2, "technology type": 3}


def _bucket(name: str) -> int:
    if name in _SPECIAL_ORDER:
        return _SPECIAL_ORDER[name]
    if name.startswith("characteristics["):
        return 1
    return 4  # comment[*] and anything else


def physical_order(columns):
    """Reorder template columns into SDRF physical layout (stable within bucket).

    ``columns`` may be Column objects (with ``.name``) or plain strings.
    Returns the same element type, reordered.
    """

    def name_of(c):
        return c.name if hasattr(c, "name") else c

    return sorted(columns, key=lambda c: _bucket(name_of(c)))


def header_order_errors(header) -> list[str]:
    """Physical-layout violations in a header row (list of column names)."""
    errs = []
    if header and header[0] != "source name":
        errs.append("Column order: 'source name' must be the first column.")
    assay_idx = header.index("assay name") if "assay name" in header else None
    if assay_idx is not None:
        late = [
            c
            for i, c in enumerate(header)
            if i > assay_idx and c.startswith("characteristics[")
        ]
        if late:
            errs.append(
                "Column order: all characteristics[...] columns must come BEFORE "
                "'assay name'. Move these before it: " + ", ".join(late)
            )
    return errs


def _parse_cli_lines(output: str):
    errors, warnings = [], []
    for ln in output.splitlines():
        s = ln.strip()
        if s.startswith("ERROR:"):
            errors.append(s[len("ERROR:") :].strip())
        elif s.startswith("WARNING:"):
            warnings.append(s[len("WARNING:") :].strip())
    return errors, warnings


def validate_text(
    sdrf_text: str,
    templates=("ms-proteomics",),
    run_cli: bool = True,
    labels: dict | None = None,
    parse_cmd=("parse_sdrf", "validate-sdrf"),
    parse_env: dict | None = None,
) -> dict:
    """Validate an SDRF string. Returns {"errors": [...], "warnings": [...]}.

    Errors block acceptance; warnings are advisory but still fed back to the
    model. Combines physical-order + structural (ragged/collisions) + parse_sdrf
    (ERROR/WARNING lines) + NT/AC accession consistency.

    ``parse_cmd`` is the base parse_sdrf invocation (default the console script;
    on the cluster it is ``[python, -m, sdrf_pipelines.parse_sdrf, validate-sdrf]``)
    and ``parse_env`` is a custom environment for that subprocess only — so an
    isolated PYTHONPATH/XDG_CACHE_HOME can point at a --target install + OLS cache
    without disturbing the parent process (e.g. a vLLM worker).
    """
    errors: list[str] = []
    warnings: list[str] = []

    lines = sdrf_text.splitlines()
    header = lines[0].split("\t") if lines else []
    errors += header_order_errors(header)
    ndata = sum(1 for ln in lines[1:] if ln.strip())
    if ndata == 0:
        errors.append("SDRF has a header but no data rows.")

    with tempfile.NamedTemporaryFile(
        "w", suffix=".sdrf.tsv", delete=False, newline=""
    ) as tf:
        tf.write(sdrf_text if sdrf_text.endswith("\n") else sdrf_text + "\n")
        tmp = tf.name
    try:
        ragged, collisions = structural_check(tmp)
        if ragged:
            errors.append(
                f"{ragged} row(s) have a different number of columns than the "
                "header (ragged rows). Every row must have exactly the header's "
                "column count."
            )
        if collisions:
            errors.append(
                f"{collisions} duplicate sample coordinate(s): the combination "
                "(source name, biological replicate, technical replicate, "
                "fraction identifier) must be unique on every row."
            )
        if run_cli:
            cmd = [*parse_cmd, "--sdrf_file", tmp]
            for t in templates:
                cmd += ["-t", t]
            cmd += ["--use_ols_cache_only"]
            try:
                out = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=parse_env,
                    check=False,
                )
                ce, cw = _parse_cli_lines(out.stdout + out.stderr)
                errors += ce
                warnings += cw
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                warnings.append(f"parse_sdrf unavailable ({type(e).__name__}).")
        if labels:
            for nt, ac, real in accession_check(tmp, labels):
                errors.append(
                    f"Accession mismatch: '{nt}' is labelled {ac}, but {ac} is "
                    f"'{real}' in the ontology. Use the correct accession for '{nt}'."
                )
    finally:
        Path(tmp).unlink(missing_ok=True)

    # de-duplicate, preserve order
    return {"errors": _dedup(errors), "warnings": _dedup(warnings)}


def _dedup(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_repair_message(errors, warnings=()) -> str:
    lines = [
        (
            "Your SDRF did not pass validation. Fix EVERY issue below and output the "
            "FULL corrected SDRF again (header + all data rows), same format, no prose."
        ),
        "",
        "ERRORS (must fix):",
    ]
    lines += [f"  - {e}" for e in errors] or ["  (none)"]
    if warnings:
        lines += ["", "WARNINGS (fix if you can):"]
        lines += [f"  - {w}" for w in warnings]
    lines += [
        "",
        (
            "Reminders: use controlled-vocabulary terms (NT=name;AC=ONTOLOGY:ACCESSION) "
            "for instrument, label, cleavage agent, dissociation, disease, organism "
            "part -- but if you are NOT certain of the accession, give only NT=term name "
            "and OMIT AC= (never guess an accession). comment[sdrf version] must be like "
            "v1.1.0 (leading 'v'). Keep the physical column order source name -> "
            "characteristics[...] -> assay name -> technology type -> comment[...]; fill "
            "missing values with 'not available' (unknown) or 'not applicable' (n/a)."
        ),
    ]
    return "\n".join(lines)


_FENCE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


def clean_output(text: str) -> str:
    """Strip accidental markdown fences / leading prose the model may emit."""
    t = text.strip()
    t = _FENCE.sub("", t).strip()
    # drop any leading lines before the header row (must start with 'source name')
    lines = t.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("source name\t") or ln == "source name":
            return "\n".join(lines[i:]).strip()
    return t


def run_repair_loop(messages, generate, validate, max_iters: int = 4) -> dict:
    """Generate -> validate -> feed failures back, up to ``max_iters`` rounds.

    ``generate(messages) -> str`` ; ``validate(text) -> {"errors", "warnings"}``.
    Returns {text, passed, iters, history} where history logs per-round error and
    warning counts (and the messages themselves for the errors).
    """
    history = []
    text = ""
    result = {"errors": ["(not run)"], "warnings": []}
    convo = list(messages)
    for i in range(max_iters):
        text = clean_output(generate(convo))
        result = validate(text)
        history.append(
            {
                "iter": i,
                "errors": len(result["errors"]),
                "warnings": len(result["warnings"]),
                "error_messages": result["errors"],
            }
        )
        if not result["errors"]:
            return {"text": text, "passed": True, "iters": i + 1, "history": history}
        convo = convo + [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": build_repair_message(result["errors"], result["warnings"]),
            },
        ]
    return {
        "text": text,
        "passed": not result["errors"],
        "iters": max_iters,
        "history": history,
    }

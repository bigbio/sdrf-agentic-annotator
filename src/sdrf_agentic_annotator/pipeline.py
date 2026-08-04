"""Drafter pipeline — compose the stages into one dataset annotation.

    Qwen self-repair loop  ->  techsdrf empirical  ->  deterministic accession
    refine (ground + strip)  ->  final validation

An LLM for judgment (sample mapping, organism part, disease), empirical spectra
analysis for instrument/acquisition/mods, and deterministic ontology lookups for
accessions — each fact sourced from where it is actually authoritative.

Pure orchestration over injectable stage callables, so it is unit-tested with
fakes; the real run wires vLLM (``generate``), ``draft.validate_text``,
``techrefine.techrefine`` and ``ground.refine`` at the edge (the GPU/CPU jobs).
"""

from __future__ import annotations

from .draft import run_repair_loop


def draft_dataset(
    accession: str,
    messages,
    generate,
    validate,
    *,
    techrefine_fn=None,
    refine_fn=None,
    max_iters: int = 4,
) -> dict:
    """Run the full drafter for one dataset. Returns
    {text, passed, final_validation, stages} where ``stages`` records what each
    stage did (loop history, techsdrf changes, ground/strip changes).

    * ``generate(messages) -> str`` and ``validate(text) -> {errors, warnings}``
      drive the Qwen self-repair loop.
    * ``techrefine_fn(accession, text) -> {ok, text, changes}`` (optional) applies
      empirical spectra-derived columns; on the cluster this is
      ``techrefine.techrefine_dataset`` (Thermo-only, per name-family so mixed
      instruments each get their own values, representative subset per family).
    * ``refine_fn(text) -> (text, {grounded, stripped})`` (optional) grounds/strips
      accessions deterministically.
    """
    stages: dict = {}

    loop = run_repair_loop(messages, generate, validate, max_iters=max_iters)
    text = loop["text"]
    stages["loop"] = {
        "passed": loop["passed"],
        "iters": loop["iters"],
        "history": loop["history"],
    }

    if techrefine_fn is not None:
        tr = techrefine_fn(accession, text)
        stages["techsdrf"] = {
            "ok": tr.get("ok", False),
            "changes": tr.get("changes", []),
        }
        if tr.get("ok") and tr.get("text"):
            text = tr["text"]

    if refine_fn is not None:
        text, info = refine_fn(text)
        stages["refine"] = info

    final = validate(text)
    return {
        "text": text,
        "passed": not final["errors"],
        "final_validation": final,
        "stages": stages,
    }

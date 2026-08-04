"""Fast in-process SDRF validation.

The subprocess-per-file ``parse_sdrf`` path re-imports sdrf-pipelines and reloads
the ontology cache on every call (~9 s/file) — untenable for batch refine over
thousands of datasets. ``FastValidator`` builds the schema registry + ontology
once and validates each SDRF from a string in-process (~2 s/file).

Only use this on CPU steps (batch refine); the GPU draft loop keeps the isolated
subprocess validator so sdrf-pipelines' numpy can't clash with vLLM's.
"""

from __future__ import annotations

import io
import logging


class FastValidator:
    """Reusable in-process validator (registry + ontology loaded once)."""

    def __init__(self):
        from sdrf_pipelines.sdrf.schemas import SchemaRegistry, SchemaValidator

        self._registry = SchemaRegistry()
        self._validator = SchemaValidator(self._registry)

    def validate(self, sdrf_text: str, template: str = "ms-proteomics") -> dict:
        """Validate an SDRF string. Returns {"errors": [...], "warnings": [...]}
        (same shape as draft.validate_text)."""
        from sdrf_pipelines.sdrf.sdrf import read_sdrf

        try:
            df = read_sdrf(io.StringIO(sdrf_text))
        except Exception as e:  # malformed/empty SDRF -> a blocking error, not a crash
            return {"errors": [f"unreadable SDRF: {type(e).__name__}: {e}"], "warnings": []}
        errs = self._validator.validate(df, template, use_ols_cache_only=True)
        errors = [str(e) for e in errs if e.error_type == logging.ERROR]
        warnings = [str(e) for e in errs if e.error_type == logging.WARNING]
        return {"errors": errors, "warnings": warnings}

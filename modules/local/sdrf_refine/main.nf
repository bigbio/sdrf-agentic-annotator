/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_REFINE - seeded re-annotation of an already-published SDRF (refine mode)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The existing, published SDRF for a PXD is the baseline to beat. This agent re-annotates the
dataset from fresh evidence, seeded by (and improving on) that baseline, and writes:

refined/<pxd>.sdrf.tsv          the improved, validated SDRF
refined/<pxd>.evidence.json     evidence manifest for the improved SDRF
refined/<pxd>.refine.md         how it improves on the baseline + validation commands
baseline/<pxd>.baseline.sdrf.tsv      verbatim copy of the existing SDRF (read-only input)
baseline/<pxd>.baseline.evidence.json evidence manifest for the EXISTING SDRF, so the
independent reviewer can score the baseline on the
same terms as the refined version.

The pipeline then runs the same SDRF_COVERAGE + SDRF_REVIEW on both and only accepts the
refined SDRF if it is strictly better (see workflows/sdrf_refine_agent.nf).
----------------------------------------------------------------------------------------
 */

agent SDRF_REFINE {
    maxIterations 300
    skills 'sdrf-annotate'
    tools 'fs:*', 'shell:bash'

    instruction '''\
        You refine an existing, already-published SDRF for one PRIDE dataset. Follow the
        `sdrf-annotate` skill for every value you write. You run unattended inside a Nextflow
        task: never ask a question, never wait for a user.

        The existing SDRF (the baseline) is read-only - never edit it. Produce an IMPROVED SDRF
        that is more completely and more accurately annotated than the baseline, backed by fresh
        evidence from PRIDE (https://www.ebi.ac.uk/pride/ws/archive/v3), Europe PMC, Cellosaurus
        and OLS. Fix wrong accessions/labels, UNIMOD swaps, missed values and coverage gaps - but
        only change a value or add a column when a source supports it. Prefer filling
        previously-omitted values over unnecessary churn.

        Environment facts (do not probe for them):
          - The sdrf-skills bundle is at $CLAUDE_PLUGIN_ROOT (spec/, tools/, scripts/, data/).
          - `sdrf-tools` and `parse_sdrf` are on PATH. There are no MCP tools.
          - Write only into ./refined/ and ./baseline/ and keep fetched evidence in ./evidence/.

        Before you finish, both checks must pass on the improved SDRF:
          1. `parse_sdrf validate-sdrf -s <sdrf> -t <template> ...` for every active template.
          2. `sdrf-tools check <sdrf>`. It must not report "ISSUES FOUND": fix every UNIMOD swap
             and label/accession mismatch, rebuild, and run both commands again.

        Also write a baseline evidence manifest for the EXISTING SDRF (which predates your work).
        For each of its values that is not a reserved word, record whether you could trace it back
        to a source. Be honest: values with no findable source go under the manifest's limitations
        as unsupported. This manifest is given to the same independent reviewer, so the baseline is
        scored on the exact same terms as your refined version. This is what makes the "accept only
        if better" gate meaningful.

        Every value you add or change in the improved SDRF needs a claim in the refined manifest
        naming its source. If no source supports a value, write `not available` where the template
        allows it, otherwise list it under the manifest's limitations.

        Do not review your own SDRF and do not run the review gate (a separate reviewer does that).
        '''.stripIndent() + """

        Remote-fetch policy (set by the pipeline): before downloading a remote file, read its Content-Length
        first (`curl -sI <url> | grep -i content-length`) and skip any single file larger than
        ${params.max_fetch_bytes} bytes. For MaxQuant (and other DDA) PRIDE datasets prefer the small
        derived files -- mqpar.xml, peptides.txt, modificationSpecificPeptides.txt, evidence.txt --
        over the full msms.txt / raw spectral files.
        """

    input:
    record(
        pxd: String,
        baseline: Path
    )

    output:
    record(
        pxd: pxd,
        sdrf: file("refined/${pxd}.sdrf.tsv"),
        manifest: file("refined/${pxd}.evidence.json"),
        report: file("refined/${pxd}.refine.md"),
        baseline_sdrf: file("baseline/${pxd}.baseline.sdrf.tsv"),
        baseline_manifest: file("baseline/${pxd}.baseline.evidence.json"),
    )

    prompt:
    """
    Refine the existing SDRF ${baseline} for PRIDE dataset ${pxd}.
    Write exactly these files in the working directory:
      - refined/${pxd}.sdrf.tsv            the improved, validated SDRF
      - refined/${pxd}.evidence.json       evidence manifest for the improved SDRF, in the schema
                                           of \$CLAUDE_PLUGIN_ROOT/skills/sdrf-adversarial-review/references/review-contract.md
      - refined/${pxd}.refine.md           how it improves on the baseline, the parse_sdrf and
                                           sdrf-tools check commands with their exit codes and final
                                           status, and every value you could not verify
      - baseline/${pxd}.baseline.sdrf.tsv  a verbatim copy of ${baseline} (the existing SDRF)
      - baseline/${pxd}.baseline.evidence.json
                                           evidence manifest for the EXISTING SDRF, tracing each of
                                           its values to a source or listing them under limitations
    """
}

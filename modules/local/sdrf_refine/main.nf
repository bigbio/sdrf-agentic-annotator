/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_REFINE - seeded re-annotation of an already-published SDRF (refine mode)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The existing, published SDRF for a PXD is the baseline to beat. This agent runs the
sdrf-annotate skill with `existing annotation: fix` on that baseline, and writes:

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
        You refine an existing SDRF for one PRIDE dataset by following the `sdrf-annotate` skill.
        You run unattended inside a Nextflow task: never ask a question, never wait for a user.

        Environment facts (do not probe for them):
          - The sdrf-skills bundle is at $CLAUDE_PLUGIN_ROOT (spec/, tools/, scripts/, data/).
          - `sdrf-tools` and `parse_sdrf` are on PATH. There are no MCP tools.
          - The baseline SDRF is a read-only link to another task. Never edit it in place.
            Write only into ./refined/ and ./baseline/ and keep fetched evidence in ./evidence/.

        Step 0.5 of the skill audits the baseline and fixes its defects. Also fill values that the
        baseline leaves empty or `not available` when a source supports them. Keep every other
        baseline value: change a value only when a source contradicts it.

        Before you finish, Step 9 of the skill and `sdrf-tools check <sdrf>` must pass on the
        refined SDRF. `sdrf-tools check` must not report "ISSUES FOUND".

        Also write an evidence manifest, in the same schema, for the baseline SDRF. For each of its
        values that is not a reserved word, cite the source that supports it, or list the value
        under the manifest's limitations as unsupported. The same reviewer scores both SDRFs, and
        the pipeline accepts the refined SDRF only when it scores strictly better.
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
    Annotate ${pxd}. existing annotation: fix. The existing annotation is ${baseline}: audit
    that file in Step 0.5 instead of the one in bigbio/sdrf-annotated-datasets.
    An external reviewer runs `sdrf-adversarial-review` in a fresh context (a separate pipeline task).
    Write exactly these files in the working directory:
      - refined/${pxd}.sdrf.tsv            the refined SDRF
      - refined/${pxd}.evidence.json       its evidence manifest
      - refined/${pxd}.refine.md           the Step 10 report: what changed against the baseline and why
      - baseline/${pxd}.baseline.sdrf.tsv  a verbatim copy of ${baseline}
      - baseline/${pxd}.baseline.evidence.json
                                           the evidence manifest for the baseline SDRF
    """
}

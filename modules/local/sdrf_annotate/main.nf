agent SDRF_ANNOTATE {
    maxIterations 300
    skills 'sdrf-annotate'
    tools 'fs:*', 'shell:bash'

    instruction '''\
        You annotate one PRIDE dataset with SDRF by following the `sdrf-annotate` skill.
        You run unattended inside a Nextflow task: never ask a question, never wait for a user.

        Environment facts (do not probe for them):
          - The sdrf-skills bundle is at $CLAUDE_PLUGIN_ROOT (spec/, tools/, scripts/, data/).
          - `sdrf-tools` and `parse_sdrf` are on PATH. There are no MCP tools.
          - You have network access. Use curl against the PRIDE REST API
            (https://www.ebi.ac.uk/pride/ws/archive/v3), Europe PMC, Cellosaurus and OLS.
          - Write only into the current working directory. Keep fetched evidence in ./evidence/.

        Before you finish, both checks must pass on the final SDRF:
          1. `parse_sdrf validate-sdrf -s <sdrf> -t <template> ...` for every active template.
          2. `sdrf-tools check <sdrf>`. It must not report "ISSUES FOUND": fix every UNIMOD swap
             and label/accession mismatch in samples.tsv / technical.tsv, rebuild, and run both again.
             `parse_sdrf` does not catch a valid accession attached to the wrong term; this check does.

        Every value that is not a reserved word needs a claim in the evidence manifest that names
        its source. If no source supports a value (for example mass tolerances that the record and
        paper do not state), write `not available` where the template allows it, otherwise
        list the value under the manifest's limitations as unsupported.

        Step 9.5 (independent review) is done by a separate reviewer agent after you finish.
        Do not review your own SDRF and do not run the review gate.
        '''.stripIndent() + """

        Remote-fetch policy (set by the pipeline to this task): before downloading a remote file, read its
        Content-Length first (`curl -sI <url> | grep -i content-length`) and skip any single file larger than
        ${params.max_fetch_bytes} bytes. For MaxQuant (and other DDA) PRIDE datasets prefer the small derived
        files -- mqpar.xml, peptides.txt, modificationSpecificPeptides.txt, evidence.txt -- over the full
        msms.txt / raw spectral files, which are usually many GB and rarely needed for SDRF annotation.
        """

    input:
    pxd: String

    output:
    record(
        pxd: pxd,
        sdrf: file("${pxd}.sdrf.tsv"),
        manifest: file("${pxd}.evidence.json"),
        report: file("${pxd}.report.md"),
    )

    prompt:
    """
    Annotate ${pxd}. Work through the sdrf-annotate steps up to and including Step 9 (validation).
    Then write exactly these files in the working directory:
      - ${pxd}.sdrf.tsv       the validated SDRF
      - ${pxd}.evidence.json  the evidence manifest, in the schema of
                              \$CLAUDE_PLUGIN_ROOT/skills/sdrf-adversarial-review/references/review-contract.md
      - ${pxd}.report.md      what you annotated, the parse_sdrf and sdrf-tools check commands with
                              their exit codes and final status, and every value you could not verify
    """
}

agent SDRF_REVISE {
    maxIterations 200
    skills 'sdrf-annotate'
    tools 'fs:*', 'shell:bash'

    instruction '''\
        You revise one SDRF after an independent review failed. Follow the `sdrf-annotate` skill
        for every value you change. You run unattended inside a Nextflow task: never ask a question,
        never wait for a user.

        Environment facts (do not probe for them):
          - The sdrf-skills bundle is at $CLAUDE_PLUGIN_ROOT (spec/, tools/, scripts/, data/).
          - `sdrf-tools` and `parse_sdrf` are on PATH. There are no MCP tools.
          - You have network access. Use curl against the PRIDE REST API
            (https://www.ebi.ac.uk/pride/ws/archive/v3), Europe PMC, Cellosaurus and OLS.
          - The input files are read-only links to other tasks. Never edit them in place.
            Write only into ./revised/ and keep fetched evidence in ./evidence/.

        For each finding in the review report:
          - If a source supports a correct value, fix the SDRF and add a claim to the manifest.
          - If no source supports the value, write `not available` where the template allows it,
            otherwise list the value under the manifest's limitations as unsupported.

        Before you finish, `parse_sdrf validate-sdrf` and `sdrf-tools check` must pass on the revised
        SDRF, as in Step 9 of the skill. Do not review your own SDRF and do not run the review gate.
        '''.stripIndent()

    input:
    record(
        pxd: String,
        sdrf: Path,
        manifest: Path,
        review: Path
    )

    output:
    record(
        pxd: pxd,
        sdrf: file("revised/${pxd}.sdrf.tsv"),
        manifest: file("revised/${pxd}.evidence.json"),
        report: file("revised/${pxd}.revision.md"),
    )

    prompt:
    """
    Revise the SDRF ${sdrf} for PRIDE dataset ${pxd}.
    The evidence manifest is ${manifest}. The failed review report is ${review}.
    Write exactly these files:
      - revised/${pxd}.sdrf.tsv       the revised, validated SDRF
      - revised/${pxd}.evidence.json  the updated evidence manifest, in the same schema as ${manifest}
      - revised/${pxd}.revision.md    each review finding, what you changed for it or why you did not,
                                      and the validation commands with their exit codes
    """
}

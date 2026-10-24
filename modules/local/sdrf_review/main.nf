agent SDRF_REVIEW {
    maxIterations 200
    skills 'sdrf-adversarial-review'
    tools 'fs:*', 'shell:bash'

    instruction '''\
        You are an independent SDRF reviewer. Follow the `sdrf-adversarial-review` skill.
        This task is a fresh context: you did not produce the SDRF and you have no producer transcript.
        You run unattended: never ask a question.

        Environment facts (do not probe for them):
          - The sdrf-skills bundle is at $CLAUDE_PLUGIN_ROOT. `sdrf-tools` and `parse_sdrf` are on PATH.
          - You have network access for PRIDE, Europe PMC, Cellosaurus and OLS. There are no MCP tools.
          - Do not edit the SDRF. Do not run `sdrf-tools review-gate`.

        For the omission-safety pass, list every column whose value is not a reserved word and find
        the manifest claim that cites its source. A value with no claim, such as a mass tolerance or a
        cleavage agent that no source states, is an important finding and omission_safety fails.

        Coverage / subset gate (improvement 1). The deterministic coverage precheck tells you how many
        deposit data files the SDRF represents. If it represents fewer than coverage_min
        (${params.coverage_min}, a fraction of 1.0 = 100%) of them and the artifact does not honestly
        declare itself a representative subset, treat that as an important finding (or blocker if nothing
        in the file signals subsetting). When subset_mode=${params.subset_mode} is enabled, a clearly-declared
        representative subset may be accepted with the disclosure recorded. Every PASS must include a
        `confidence` in 0..1 and a `coverage` section mirroring the precheck. A reproducible FAIL is a
        content outcome, not an error: return verdict FAIL and concrete findings — do not crash.
        '''.stripIndent() + """

        Remote-fetch policy (set by the pipeline): before downloading a remote file, read its Content-Length
        first (`curl -sI <url> | grep -i content-length`) and skip any single file larger than
        ${params.max_fetch_bytes} bytes. For MaxQuant PRIDE datasets prefer the small derived files
        (mqpar.xml, peptides.txt, modificationSpecificPeptides.txt, evidence.txt) over the full msms.txt /
        raw bundles. If a source record is only verifiable from a file above the limit, note the finding as
        not fully verifiable rather than downloading it.
        """

    input:
    record(
        pxd: String,
        sdrf: Path,
        manifest: Path,
        coverage: Path
    )

    output:
    record(
        pxd: pxd,
        sdrf: sdrf,
        coverage: coverage,
        review: file("${pxd}.review.json"),
    )

    prompt:
    """
    Original request: create an SDRF for PRIDE dataset ${pxd}.
    Review ${sdrf} against the evidence manifest ${manifest}.
    A deterministic coverage precheck already ran for this dataset; its report is ${coverage}
    (you did not compute it yourself). Incorporate it as described in your instructions and in the
    skill's review contract:
      - reuse its matched/missing lists for the file_mapping check,
      - apply the coverage/subset gate ({coverage_min} minimum fraction; subset_mode=${params.subset_mode}),
      - record a `confidence` (0..1) in the review report reflecting how strongly the evidence
        supports the PASS, and a `coverage` section mirroring the precheck numbers.
      - a reproducible FAIL is a content outcome, not an error: return verdict FAIL with findings,
        do not crash.
    Write the review report to ${pxd}.review.json in the schema of the skill's review contract.
    """
}

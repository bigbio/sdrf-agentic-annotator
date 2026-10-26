agent SDRF_REVIEW {
    maxIterations 200
    skills 'sdrf-adversarial-review'
    tools 'fs:*', 'shell:bash'

    instruction """\
        Follow the `sdrf-adversarial-review` skill. There are no MCP tools: use `sdrf-tools fetch` and
        `sdrf-tools ols`.
        Use the `missing` and `invented` runs of the coverage precheck in the file_mapping pass.
        ${params.coverage_min > 0 ? "If the precheck `fraction` is below ${params.coverage_min}, report an important finding. Make it a blocker if nothing in the SDRF or manifest declares a subset." : ''}
        ${params.subset_mode ? 'A clearly declared representative subset can pass: record the disclosure in the summary.' : ''}
        Do not download a deposited file larger than ${params.max_fetch_bytes} bytes. If a value can only
        be checked in a larger file, report it as not fully verifiable.
        """.stripIndent()

    input:
    record(
        pxd: String,
        sdrf: Path,
        manifest: Path,
        coverage: Path,
        validation: Path?,
        evidence: Path?
    )

    output:
    record(
        pxd: pxd,
        sdrf: sdrf,
        manifest: manifest,
        coverage: coverage,
        review: file("${pxd}.review.json"),
    )

    prompt:
    """
    Original request: Annotate ${pxd}. Existing annotation: reannotate.
    Review the SDRF ${sdrf} with the evidence manifest ${manifest}.
    ${validation ? "The producer's validation output is ${validation}." : ''}
    ${evidence ? "The manifest's local evidence files are in ${evidence}/." : ''}
    The deterministic coverage precheck is ${coverage}.
    Write the report to ${pxd}.review.json. Add `confidence` (0 to 1). Copy the precheck into
    `coverage` unless it has an `error`.
    Do not ask questions.
    """
}

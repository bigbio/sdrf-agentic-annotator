agent SDRF_REVISE {
    maxIterations 200
    skills 'sdrf-annotate'
    tools 'fs:*', 'shell:bash'

    instruction """\
        Follow the `sdrf-annotate` skill. There are no MCP tools: look terms up with `sdrf-tools ols`.
        `evidence/`, if present, holds the record from `sdrf-tools fetch`. You have network access, so
        this is not offline mode.
        The input files are read-only links. Copy `samples.tsv` and `technical.tsv` to `revised/` and fix
        them there; if they are missing, write them from the SDRF first.
        In Step 9, also run `sdrf-tools check` on the SDRF and fix every issue it reports.
        Do not download a deposited file larger than ${params.max_fetch_bytes} bytes. For MaxQuant, read
        mqpar.xml and the small result tables, not msms.txt or raw files.
        """.stripIndent()

    input:
    record(
        pxd: String,
        sdrf: Path,
        manifest: Path,
        review: Path,
        samples: Path?,
        technical: Path?,
        evidence: Path?
    )

    output:
    record(
        pxd: pxd,
        sdrf: file("revised/${pxd}.sdrf.tsv"),
        manifest: file("revised/${pxd}.evidence.json"),
        validation: file("revised/${pxd}.validation.txt"),
        report: file("revised/${pxd}.revision.md"),
        samples: file("revised/samples.tsv"),
        technical: file("revised/technical.tsv"),
    )

    prompt:
    """
    Revise the SDRF ${sdrf} for ${pxd}. Existing annotation: reannotate.
    The external review ${review} failed. Fix its findings. The evidence manifest is ${manifest}.
    Do not ask questions.
    An external reviewer runs `sdrf-adversarial-review` in a separate pipeline task.
    Write the outputs to `revised/` with the default names. Name the report ${pxd}.revision.md: for
    each finding, say what you changed or why you did not.
    """
}

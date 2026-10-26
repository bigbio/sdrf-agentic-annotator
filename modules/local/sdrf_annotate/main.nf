agent SDRF_ANNOTATE {
    maxIterations 300
    skills 'sdrf-annotate'
    tools 'fs:*', 'shell:bash'

    instruction """\
        Follow the `sdrf-annotate` skill. There are no MCP tools: gather the record with `sdrf-tools fetch`.
        Keep `evidence/`, `samples.tsv` and `technical.tsv` in the working directory: later tasks read them.
        In Step 9, also run `sdrf-tools check` on the SDRF and fix every issue it reports.
        Do not download a deposited file larger than ${params.max_fetch_bytes} bytes. For MaxQuant, read
        mqpar.xml and the small result tables, not msms.txt or raw files.
        """.stripIndent()

    input:
    pxd: String

    output:
    record(
        pxd: pxd,
        sdrf: file("${pxd}.sdrf.tsv"),
        manifest: file("${pxd}.evidence.json"),
        validation: file("${pxd}.validation.txt"),
        report: file("${pxd}.report.md"),
        samples: file("samples.tsv"),
        technical: file("technical.tsv"),
        evidence: file("evidence"),
    )

    prompt:
    """
    Annotate ${pxd}. Existing annotation: reannotate.
    Do not ask questions.
    External reviewer: a separate pipeline task runs `sdrf-adversarial-review` in a fresh context.
    Hand the Step 9.5 review off to it and give the status REVIEW_PENDING_EXTERNAL.
    """
}

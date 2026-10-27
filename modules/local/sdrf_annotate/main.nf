agent SDRF_ANNOTATE {
    maxIterations 300
    skills 'sdrf-annotate'
    tools 'fs:*', 'shell:bash'

    instruction """\
        Follow the `sdrf-annotate` skill. There are no MCP tools: gather the record with `sdrf-tools fetch`.
        The sdrf-skills bundle is at `/opt/sdrf-skills` (the `SDRF_SKILLS_ROOT` environment variable): resolve
        skill paths such as `spec/sdrf-proteomics/TERMS.tsv` or `skills/sdrf-annotate/references/gather-context.md`
        against it. Never search the whole filesystem (`find /`): on a cluster it hangs for tens of minutes.
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
    An external reviewer runs `sdrf-adversarial-review` in a separate pipeline task.
    """
}

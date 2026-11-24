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
    record(
        pxd: String,
        prefill: Path?,
        sheet: Path?
    )

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
    ${prefill ? "The file ${prefill} holds the facts the PRIDE record already states (organism, instrument, enzymes, labels, the deposited run files). Start from them: do not look them up again, and change one only with evidence that you record in the manifest. If the file has an `error`, ignore it and gather the record yourself. A value with basis `text` was found by a pattern: confirm it. `comment[data file]` must be a name from `run_files`; when the deposit packs its runs in a zip, `run_files` lists the runs inside it: use those names. `dissociation_method` was read from the instrument method embedded in the deposited RAW files (basis `raw`): use it for `comment[dissociation method]` and keep its `evidence` in the manifest, unless the publication states another method. If `ambiguous` is true, the method lists several activation types and you have to find out which one the study used. Never write `not available` for the dissociation method when a value is given here." : ''}
    ${sheet ? "Read ${sheet} first. It holds the methods of the manuscript and candidate values, each with its source sentence or file, built without a model. Open evidence/manuscript.txt only for a fact the sheet does not hold. Values marked (confirm) were found by a pattern: confirm them before you use them. The similar SDRFs show a column set, not values for this dataset. Record in the manifest the sentence that supports each value." : ''}
    `characteristics[sample type]` is `study sample` by default. Use another child of `sample type` (PRIDE:0000895) only when the deposit or the publication says so: `control sample`, `calibration sample`, `blank`, `single cell`, `multiplex sample` or `environmental sample`.
    Combine independent lookups (several files, several terms) into one shell command per turn: every turn costs a model request.
    These are the most common reasons the reviewer fails an SDRF; check each before you finish:
    - Mass tolerances: write a value only when a source states it (manuscript, PRIDE protocol, a deposited search parameter file) and cite that sentence or file; when the search engine sets them itself (DIA-NN library-free, for example) or no source states them, write `not available`. Never use 10 ppm / 20 ppm as defaults. Keep precursor and fragment apart in "X and Y, respectively" sentences.
    - Citations: take the DOI and PubMed ID only from evidence/pride.json or the Europe PMC record you fetched, never from memory; quote only text that is in a file you read.
    - Enzymes: a co-digestion (Lys-C and trypsin, trypsin and Glu-C) needs one `comment[cleavage agent details]` column per enzyme.
    - Instrument: if the PRIDE record, the RAW header and the manuscript disagree, use the RAW header, then the PRIDE record, and record the disagreement in the manifest.
    - Modifications: list every modification of the search, including those in a small deposited search parameter or result file.
    - Design: one row per run, and the factor values that the deposit's sample names or tables give; never one row for a whole archive or study.
    Do not ask questions.
    External reviewer: a separate pipeline task runs `sdrf-adversarial-review` in a fresh context.
    Hand the Step 9.5 review off to it and give the status REVIEW_PENDING_EXTERNAL.
    Before you give the status, list the working directory and write any of these files that is missing; the task fails without every one of them: `${pxd}.sdrf.tsv`; `${pxd}.evidence.json` (the evidence manifest itself, not only a copy under evidence/); `${pxd}.validation.txt` (the full output of `parse_sdrf validate-sdrf` on the final SDRF); `${pxd}.report.md` (a short report: templates, sources, open questions); `samples.tsv`; `technical.tsv`; the folder `evidence/`.
    """
}

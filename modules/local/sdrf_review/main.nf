agent SDRF_REVIEW {
    maxIterations 200
    skills 'sdrf-adversarial-review'
    tools 'fs:*', 'shell:bash'

    instruction """\
        Follow the `sdrf-adversarial-review` skill. There are no MCP tools: use `sdrf-tools fetch` and
        `sdrf-tools ols`.
        The sdrf-skills bundle is at `/opt/sdrf-skills` (the `SDRF_SKILLS_ROOT` environment variable): resolve
        skill paths such as `spec/sdrf-proteomics/TERMS.tsv` or `skills/sdrf-annotate/references/gather-context.md`
        against it. Never search the whole filesystem (`find /`): on a cluster it hangs for tens of minutes.
        Use the `missing` and `invented` runs of the coverage precheck in the file_mapping pass.
        ${(params.coverage_min as String).toDouble() > 0 ? "If the precheck `fraction` is below ${params.coverage_min}, report an important finding. Make it a blocker if nothing in the SDRF or manifest declares a subset." : ''}
        ${params.subset_mode.toString().trim().toLowerCase() == 'true' ? 'A clearly declared representative subset can pass: record the disclosure in the summary.' : ''}
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
        evidence: Path?,
        checks: Path?
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
    ${checks ? "The pipeline already hashed the SDRF and ran the deterministic checks of the skill's steps 1 and 3 (validate-sdrf for the active templates, sdrf-tools structure, check, score and reconcile, convert-openms) on this exact file: the outputs are in ${checks}. Use them for the deterministic_validation and spec_compliance passes and do not run those commands again; re-hash the SDRF only once, at the end, to confirm it did not change. A BLOCKER in the sample identity section of ${checks} (one source name carrying several biological replicate values) is a failing finding: independent biological replicates need distinct source names." : ''}
    `not available` for a mass tolerance that no source states is correct, not a finding, even though convert-openms then cannot read it; a tolerance value that no source states is an important finding.
    Every turn is a call to a shared, saturated model, so keep turns few: combine independent lookups (greps, jq queries, file reads, ontology lookups) into one shell command per turn, and read only the parts of large files that a check needs.
    Write the report to ${pxd}.review.json. Add `confidence` (0 to 1). Copy the precheck into
    `coverage` unless it has an `error`.
    Do not ask questions.
    """
}

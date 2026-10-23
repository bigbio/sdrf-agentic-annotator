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
        '''.stripIndent()

    input:
    record(pxd: String, sdrf: Path, manifest: Path)

    output:
    record(
        pxd:    pxd,
        sdrf:   sdrf,
        review: file("${pxd}.review.json")
    )

    prompt:
    """
    Original request: create an SDRF for PRIDE dataset ${pxd}.
    Review ${sdrf} against the evidence manifest ${manifest}.
    Write the review report to ${pxd}.review.json in the schema of the skill's review contract.
    """
}

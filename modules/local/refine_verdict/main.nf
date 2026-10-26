nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REFINE_VERDICT - write the baseline-vs-refined decision of a PXD as <pxd>.refine_verdict.json
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

process REFINE_VERDICT {
    tag "${pxd}"
    container 'ghcr.io/bigbio/sdrf-agentic-annotator:dev'

    cpus 1
    memory 2.GB

    input:
    record(
        pxd: String,
        json: String
    )

    output:
    record(
        pxd: pxd,
        verdict: file("${pxd}.refine_verdict.json"),
    )

    script:
    """
    cat > ${pxd}.refine_verdict.json <<'EOF'
    ${json}
    EOF
    """
}

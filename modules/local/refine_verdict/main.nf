nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REFINE_VERDICT - write the baseline-vs-refined decision of a PXD as <pxd>.refine_verdict.json
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

process REFINE_VERDICT {
    tag "${pxd}"
    label 'process_single'

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

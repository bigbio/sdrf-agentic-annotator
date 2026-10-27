nextflow.enable.types = true

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REFINE_VERDICT - write the baseline-vs-refined decision of a PXD as <pxd>.refine_verdict.json
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs in the Nextflow JVM, without a container.
----------------------------------------------------------------------------------------
 */

process REFINE_VERDICT {
    tag "${pxd}"

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

    exec:
    task.workDir.resolve("${pxd}.refine_verdict.json").text = json + '\n'
}

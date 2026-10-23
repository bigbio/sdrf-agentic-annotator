include { validateParameters ; paramsSummaryLog ; samplesheetToList } from 'plugin/nf-schema'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW TO INITIALISE PIPELINE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_INITIALISATION {
    take:
    input // string: path to the samplesheet

    main:
    validateParameters()
    log.info(paramsSummaryLog(workflow))

    ch_pxds = channel.fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))
        .map { row -> row[0] }

    emit:
    pxds = ch_pxds
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW FOR PIPELINE COMPLETION
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_COMPLETION {
    take:
    summary // path: summary.tsv

    main:
    summary.subscribe { tsv ->
        def failed = tsv.readLines().drop(1).findAll { line -> line.split('\t')[2] != 'PASS' }.collect { line -> line.split('\t')[0] }
        if (failed) {
            log.warn("The final review did not pass for ${failed.size()} PXD(s): ${failed.join(', ')}. See summary.tsv and the review reports.")
        }
    }
}

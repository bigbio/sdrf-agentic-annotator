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
        def rows = tsv.readLines().drop(1).findAll { line -> line.trim() }
        def notPass = rows.findAll { line -> line.split('\t')[2] != 'PASS' && line.split('\t')[2] != 'LOW_CONF' }.collect { line -> line.split('\t')[0] }
        def lowConf = rows.findAll { line -> line.split('\t')[2] == 'LOW_CONF' }.collect { line -> line.split('\t')[0] }
        if (notPass) {
            log.warn(
                "Final review did not pass for ${notPass.size()} PXD(s): ${notPass.join(', ')}. " + "This is a content outcome, not an infrastructure error. See summary.tsv and review reports."
            )
        }
        if (lowConf) {
            log.warn(
                "Final verdict is LOW_CONF for ${lowConf.size()} PXD(s): ${lowConf.join(', ')}. " + "Accepted and passed on; revisit if you want a stronger annotation."
            )
        }
        if (params.exit_on_review_fail && notPass) {
            error(
                "exit_on_review_fail requested and ${notPass.size()} PXD(s) have a non-PASS final verdict: ${notPass.join(', ')}. " + "This is an intentional exit-on-content-fail; infra errors are handled separately by task retries."
            )
        }
    }
}

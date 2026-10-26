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

    // ref_sdrf is optional and only used in refine mode
    ch_samplesheet = channel.fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))
        .map { row ->
            def r = (row instanceof Map)
                ? [pxd: row.pxd, ref_sdrf: row.ref_sdrf]
                : [pxd: row[0], ref_sdrf: (row.size() >= 2 ? row[1] : null)]
            record(pxd: r.pxd as String, ref_sdrf: (r.ref_sdrf ? r.ref_sdrf as String : null))
        }

    emit:
    samplesheet = ch_samplesheet // records: pxd, ref_sdrf
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
        def lines = tsv.readLines().findAll { line -> line.trim() }
        def header = lines[0].split('\t') as List
        def verdicts = lines
            .drop(1)
            .collectEntries { line ->
                def row = [header, line.split('\t', -1) as List].transpose().collectEntries()
                // refine_summary.tsv has no final_verdict: the verdict of the chosen SDRF is the final one
                def verdict = row.containsKey('final_verdict')
                    ? row.final_verdict
                    : (row.chosen == 'refined' ? row.refined_verdict : row.baseline_verdict)
                [(row.pxd): verdict]
            }
        def notPass = verdicts.findAll { _pxd, v -> v != 'PASS' && v != 'LOW_CONF' }.keySet() as List
        def lowConf = verdicts.findAll { _pxd, v -> v == 'LOW_CONF' }.keySet() as List
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

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

// Parsed JSON file, or null when the file is missing or unreadable
def readJson(json) {
    if (!json) {
        return null
    }
    try {
        return new groovy.json.JsonSlurper().parse(json.toFile())
    }
    catch (_e: Exception) {
        return null
    }
}

def verdictOf(review) {
    return readJson(review)?.verdict ?: 'FAIL'
}

def confidenceOf(review) {
    try {
        def c = readJson(review)?.confidence
        return c != null ? c as Float : -1.0
    }
    catch (_e: Exception) {
        return -1.0
    }
}

def parseReview(review) {
    return [verdict: verdictOf(review), conf: confidenceOf(review)]
}

// Run coverage for summary.tsv: the fraction, `unverifiable` after a coverage error, or `n/a`
def coverageOf(coverage) {
    def c = readJson(coverage)
    if (c == null) {
        return 'n/a'
    }
    return c.error ? 'unverifiable' : (c.fraction != null ? c.fraction as String : 'n/a')
}

def coverageFraction(coverage) {
    def f = readJson(coverage)?.fraction
    return f != null ? f as Float : null
}

// Accept the refined SDRF only if it is strictly better than the baseline:
//   - refined must PASS the independent adversarial review,
//   - refined coverage must be measurable and not worse than baseline,
//   - and either the baseline did not PASS (FAIL -> PASS) or the refined confidence is higher.
def isBetter(bv, fv, bc, fc) {
    if (fv.verdict != 'PASS') {
        return false
    }
    if (fc == null) {
        return false
    }
    if (bc != null && fc < bc) {
        return false
    }
    if (bv.verdict != 'PASS') {
        return true
    }
    return fv.conf > bv.conf
}

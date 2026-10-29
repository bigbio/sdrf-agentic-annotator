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

    // samplesheetToList returns one list per row in schema column order (pxd, ref_sdrf), with
    // ref_sdrf as a Path. An empty or absent ref_sdrf comes back as an empty list.
    ch_samplesheet = channel.fromList(samplesheetToList(input, "${projectDir}/assets/schema_input.json"))
        .map { row -> record(pxd: row[0] as String, ref_sdrf: row[1] ?: null) }

    emit:
    samplesheet = ch_samplesheet // records: pxd, ref_sdrf (Path or null, used only in refine mode)
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUBWORKFLOW FOR PIPELINE COMPLETION
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow PIPELINE_COMPLETION {
    take:
    summary // path: summary.tsv or refine_summary.tsv, both with `pxd` and `final_verdict` columns

    main:
    // A final FAIL is a content outcome, not an infrastructure error: warn, and stop only on request
    summary.subscribe { tsv ->
        def rows = readSummary(tsv)
        def noReview = rows.findAll { r -> r.final_verdict == 'NO_REVIEW' }.collect { r -> r.pxd }
        def notPass = rows.findAll { r -> !(r.final_verdict in ['PASS', 'LOW_CONF', 'NO_REVIEW']) }.collect { r -> r.pxd }
        def lowConf = rows.findAll { r -> r.final_verdict == 'LOW_CONF' }.collect { r -> r.pxd }
        if (notPass) {
            log.warn(
                "Final review did not pass for ${notPass.size()} PXD(s): ${notPass.join(', ')}. " + "This is a content outcome, not an infrastructure error. See ${tsv.name} and review reports."
            )
        }
        if (noReview) {
            log.warn(
                "The re-review of the revised SDRF did not finish for ${noReview.size()} PXD(s): ${noReview.join(', ')}. " + "A task failed and was skipped, so the revised files have no verdict. This is an infrastructure failure, not a content outcome."
            )
        }
        if (lowConf) {
            log.warn(
                "Final verdict is LOW_CONF for ${lowConf.size()} PXD(s): ${lowConf.join(', ')}. " + "Accepted and passed on; revisit if you want a stronger annotation."
            )
        }
        if (isTrue(params.exit_on_review_fail) && (notPass || noReview)) {
            def failed = notPass + noReview
            error(
                "exit_on_review_fail requested and ${failed.size()} PXD(s) have a non-PASS final verdict: ${failed.join(', ')}. " + "This is an intentional exit-on-content-fail; a PXD whose re-review did not finish counts as not passed."
            )
        }
    }
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

// Verdict and confidence of a review report written by an agent. A report the pipeline cannot
// read (e.g. JSON wrapped in a markdown code fence that is not JSON inside) is a FAIL with a
// warning, never a crash of the whole run. The verdict is upper-cased, so `pass` is a PASS.
def readReview(review) {
    def text = review.text.trim()
    if (text.startsWith('```')) {
        text = text.replaceFirst('^```[A-Za-z]*', '').replaceFirst('```$', '').trim()
    }
    def json = null
    try {
        json = new groovy.json.JsonSlurper().parseText(text)
    }
    catch (e: Exception) {
        log.warn("Cannot parse the review report ${review}: ${e.message}. Counting it as FAIL.")
    }
    if (!(json instanceof Map)) {
        return [verdict: 'FAIL', confidence: -1.0d]
    }
    def verdict = json.verdict ? (json.verdict as String).trim().toUpperCase() : 'FAIL'
    return [verdict: verdict, confidence: toConfidence(json.confidence)]
}

// Reviewer confidence as a number in 0..1, or -1 when it is missing or not a number in 0..1
def toConfidence(value) {
    try {
        def c = (value as String).toDouble()
        return (c >= 0 && c <= 1) ? c : -1.0d
    }
    catch (_e: Exception) {
        return -1.0d
    }
}

// A PASS below the confidence gate, or without a confidence, is accepted but flagged LOW_CONF
def gateVerdict(verdict, confidence, gate) {
    if (verdict == 'PASS' && gate > 0 && confidence < gate) {
        return 'LOW_CONF'
    }
    return verdict
}

// Fraction of the deposited runs that the SDRF annotates (or null) and the error, if any, of a
// SDRF_COVERAGE report (the `coverage` block of `sdrf-tools audit-existing --json`)
def readCoverage(coverage) {
    if (!coverage) {
        return [fraction: null, error: null]
    }
    try {
        def json = new groovy.json.JsonSlurper().parseText(coverage.text)
        def fraction = json.fraction != null ? (json.fraction as String).toDouble() : null
        return [fraction: fraction, error: json.error ?: null]
    }
    catch (_e: Exception) {
        return [fraction: null, error: null]
    }
}

// Coverage column of summary.tsv: `unverifiable` when the deposit could not be read, else the fraction or `n/a`
def coverageLabel(coverage) {
    if (coverage.error) {
        return 'unverifiable'
    }
    return coverage.fraction != null ? coverage.fraction as String : 'n/a'
}

// Verdict, confidence and coverage of one reviewed SDRF, as compared by the refine gate
def scoreOf(reviewed) {
    def review = readReview(reviewed.review)
    def coverage = readCoverage(reviewed.coverage)
    return [verdict: review.verdict, confidence: review.confidence, coverage: coverage.fraction, coverage_label: coverageLabel(coverage)]
}

// Accept the refined SDRF only if it is strictly better than the baseline:
//   - refined must PASS the independent adversarial review,
//   - refined coverage must be measurable and not worse than baseline,
//   - and either the baseline did not PASS (FAIL -> PASS) or the refined confidence is higher.
def isBetter(base, refined) {
    if (refined.verdict != 'PASS') {
        return false
    }
    if (refined.coverage == null) {
        return false
    }
    if (base.coverage != null && refined.coverage < base.coverage) {
        return false
    }
    if (base.verdict != 'PASS') {
        return true
    }
    return refined.confidence > base.confidence
}

// Rows of a summary TSV as maps keyed by its header
def readSummary(tsv) {
    def lines = tsv.readLines().findAll { line -> line.trim() }
    if (!lines) {
        return []
    }
    def header = lines[0].split('\t') as List
    return lines.drop(1).collect { line -> [header, line.split('\t', -1) as List].transpose().collectEntries() }
}

// Boolean parameter value. On the command line, `--revise false` arrives as the string 'false'.
def isTrue(value) {
    return (value instanceof Boolean) ? value : ((value as String)?.trim()?.toLowerCase() in ['true', 'yes', '1'])
}

// software_versions.yml: the tool versions from the `versions` topic, plus the agent model and runner image
def softwareVersionsToYAML(rows) {
    def versions = rows
        .groupBy { r -> r[0].tokenize(':').last() }
        .collectEntries { process, entries -> [(process): entries.collectEntries { r -> [(r[1]): r[2]] }] }
    def agent = workflow.session.config.agent ?: [:]
    versions['Workflow'] = [
        (workflow.manifest.name): workflow.manifest.version,
        Nextflow: workflow.nextflow.version.toString(),
        agent_model: agent.model,
        agent_api_provider: agent.apiProvider,
        agent_container: agent.container,
    ]
    return new org.yaml.snakeyaml.Yaml().dumpAsMap(versions)
}

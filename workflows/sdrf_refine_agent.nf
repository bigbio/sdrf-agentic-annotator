/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SDRF_REVIEW } from '../modules/local/sdrf_review'
include { SDRF_REVIEW as SDRF_REVIEW_BASELINE } from '../modules/local/sdrf_review'
include { SDRF_REVIEW as SDRF_REVIEW_REFINED } from '../modules/local/sdrf_review'
include { SDRF_REVIEW as SDRF_REVIEW_REFV2 } from '../modules/local/sdrf_review'
include { SDRF_COVERAGE } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_BASELINE } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REFINED } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REFV2 } from '../modules/local/sdrf_coverage'
include { SDRF_REVISE } from '../modules/local/sdrf_revise'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REFINE VERDICT - one JSON record per PXD with the baseline-vs-refined decision
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */
process REFINE_VERDICT {
    tag "${pxd}"
    container 'ghcr.io/bigbio/sdrf-agentic-annotator:dev'

    cpus 1
    memory '2 GB'

    input:
    tuple val(pxd), path(chosen_sdrf), val(verdict_json)

    output:
    tuple val(pxd), path("${pxd}.refine_verdict.json")

    script:
    """
    cat > ${pxd}.refine_verdict.json <<'EOF'
    ${verdict_json}
    EOF
    """
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RUN MAIN WORKFLOW - refine mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Given (pxd, optional ref_sdrf) rows, refine the existing SDRF and only accept the refined
version if - scored on the same adversarial review - it is strictly better than the baseline
(verdict/confidence + coverage). Otherwise keep the original.
 */

workflow SDRF_REFINE_AGENT {
    take:
    ch_rows // records: pxd (String), ref_sdrf (String or null)

    main:

    // ---- baseline acquisition: local path if given, else fetch from sdrf-annotated-datasets ----
    ch_has_ref = ch_rows
        .filter { r -> r.ref_sdrf }
        .map { r -> record(pxd: r.pxd, baseline: file(r.ref_sdrf as String)) }
    ch_no_ref = ch_rows
        .filter { r -> !r.ref_sdrf }
        .map { r -> r.pxd }
    ch_fetched = SDRF_FETCH_BASELINE(ch_no_ref).map { pxd, baseline -> record(pxd: pxd, baseline: baseline) }
    ch_baseline = ch_has_ref.mix(ch_fetched)

    // ---- refine agent: seeded re-annotation + baseline evidence manifest ----
    ch_refined = SDRF_REFINE(ch_baseline)

    // ---- baseline score: coverage precheck + independent adversarial review ----
    ch_base_cov = SDRF_COVERAGE_BASELINE(ch_refined.map { r -> tuple(r.pxd, r.baseline_sdrf, r.baseline_manifest) })
    ch_base_rev_in = ch_refined
        .map { r -> tuple(r.pxd, r) }
        .join(ch_base_cov.map { pxd, cov, _s, _m -> tuple(pxd, cov) }, remainder: true)
        .map { pxd, r, cov -> record(pxd: pxd, sdrf: r.baseline_sdrf, manifest: r.baseline_manifest, coverage: cov) }
    ch_base_rev = SDRF_REVIEW_BASELINE(ch_base_rev_in)

    // ---- refined score (initial) ----
    ch_ref_cov = SDRF_COVERAGE_REFINED(ch_refined.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })
    ch_ref_rev_in = ch_refined
        .map { r -> tuple(r.pxd, r) }
        .join(ch_ref_cov.map { pxd, cov, _s, _m -> tuple(pxd, cov) }, remainder: true)
        .map { pxd, r, cov -> record(pxd: pxd, sdrf: r.sdrf, manifest: r.manifest, coverage: cov) }
    ch_ref_rev = SDRF_REVIEW_REFINED(ch_ref_rev_in)

    // ---- optional revise of the refined version if its review fails ----
    ch_ref_pass = ch_ref_rev.filter { r -> verdictOf(r.review) == 'PASS' }
    ch_ref_fail = ch_ref_rev.filter { r -> verdictOf(r.review) != 'PASS' }

    ch_final_rev = channel.empty()
    if (params.revise) {
        ch_rev = SDRF_REVISE(ch_ref_fail.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, review: r.review) })
        ch_rev_cov = SDRF_COVERAGE_REFV2(ch_rev.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })
        ch_rev_in = ch_rev
            .map { r -> tuple(r.pxd, r) }
            .join(ch_rev_cov.map { pxd, cov, _s, _m -> tuple(pxd, cov) }, remainder: true)
            .map { pxd, r, cov -> record(pxd: pxd, sdrf: r.sdrf, manifest: r.manifest, coverage: cov) }
        ch_rev_view = SDRF_REVIEW_REFV2(ch_rev_in)
        ch_final_rev = ch_ref_pass.mix(ch_rev_view)
    }
    else {
        ch_final_rev = ch_ref_pass
    }

    // ---- acceptance gate: accept refined only if strictly better ----
    ch_decision = ch_base_rev
        .map { r -> tuple(r.pxd, r) }
        .join(ch_final_rev.map { r -> tuple(r.pxd, r) }, remainder: true)
        .map { pxd, b, f ->
            def bv = parseReview(b.review)
            def bc = parseCoverage(b.coverage)
            def reason = 'kept original (no improvement)'
            def chosen = 'baseline'
            if (f) {
                def fv = parseReview(f.review)
                def fc = parseCoverage(f.coverage)
                chosen = isBetter(bv, fv, bc, fc) ? 'refined' : 'baseline'
                reason = (chosen == 'refined')
                    ? 'refined passes and is strictly better (verdict/confidence, coverage not worse)'
                    : 'refined not strictly better - kept existing SDRF'
                record(
                    pxd: pxd,
                    baseline_verdict: bv.verdict,
                    baseline_confidence: bv.conf,
                    baseline_coverage: bc,
                    refined_verdict: fv.verdict,
                    refined_confidence: fv.conf,
                    refined_coverage: fc,
                    chosen: chosen,
                    chosen_sdrf: (chosen == 'refined') ? f.sdrf : b.sdrf,
                    json: new groovy.json.JsonBuilder([
                        pxd: pxd,
                        chosen: chosen,
                        reason: reason,
                        baseline: [verdict: bv.verdict, confidence: bv.conf, coverage: bc],
                        refined: [verdict: fv.verdict, confidence: fv.conf, coverage: fc],
                    ]).toString(),
                )
            }
            else {
                record(
                    pxd: pxd,
                    baseline_verdict: bv.verdict,
                    baseline_confidence: bv.conf,
                    baseline_coverage: bc,
                    refined_verdict: 'n/a',
                    refined_confidence: null,
                    refined_coverage: null,
                    chosen: 'baseline',
                    chosen_sdrf: b.sdrf,
                    json: new groovy.json.JsonBuilder([
                        pxd: pxd,
                        chosen: 'baseline',
                        reason: 'no refined verdict produced - kept existing SDRF',
                        baseline: [verdict: bv.verdict, confidence: bv.conf, coverage: bc],
                        refined: null,
                    ]).toString(),
                )
            }
        }

    ch_verdict = REFINE_VERDICT(ch_decision.map { r -> tuple(r.pxd, r.chosen_sdrf, r.json) })

    // ---- summary ----
    ch_summary = ch_decision
        .map { d -> [d.pxd, d.baseline_verdict, d.refined_verdict, d.chosen, d.baseline_coverage, d.refined_coverage, d.baseline_confidence, d.refined_confidence].join('\t') }
        .collectFile(
            name: 'refine_summary.tsv',
            seed: 'pxd\tbaseline_verdict\trefined_verdict\tchosen\tbaseline_coverage\trefined_coverage\tbaseline_confidence\trefined_confidence',
            newLine: true,
            sort: true,
        )

    ch_decision.subscribe { d ->
        if (d.chosen == 'baseline') {
            log.info("Refine: ${d.pxd} kept existing SDRF (baseline=${d.baseline_verdict}, refined=${d.refined_verdict})")
        }
        else {
            log.info("Refine: ${d.pxd} accepted refined SDRF (baseline=${d.baseline_verdict} -> refined=${d.refined_verdict})")
        }
    }

    emit:
    refined = ch_refined
    baseline = ch_baseline
    baseline_review = ch_base_rev
    decision = ch_decision
    verdict = ch_verdict
    summary = ch_summary
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
HELPERS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

def parseReview(review) {
    def j = new groovy.json.JsonSlurper().parse(review.toFile())
    def c = j.confidence
    return [verdict: j.verdict ?: 'FAIL', conf: (c != null ? (c as Float) : -1.0)]
}

def parseCoverage(coverage) {
    if (!coverage) {
        return null
    }
    try {
        def j = new groovy.json.JsonSlurper().parse(coverage.toFile())
        return (j.coverage != null) ? (j.coverage as Float) : null
    }
    catch (_e: Exception) {
        return null
    }
}

def verdictOf(review) {
    return new groovy.json.JsonSlurper().parse(review.toFile()).verdict ?: 'FAIL'
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

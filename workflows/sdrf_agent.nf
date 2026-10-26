/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_REVIEW } from '../modules/local/sdrf_review'
include { SDRF_REVISE } from '../modules/local/sdrf_revise'
include { SDRF_REVIEW as SDRF_REVIEW_REVISED } from '../modules/local/sdrf_review'
include { SDRF_COVERAGE } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REV1 } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REV2 } from '../modules/local/sdrf_coverage'
include { SDRF_REVISE as SDRF_REVISE_REV2 } from '../modules/local/sdrf_revise'
include { SDRF_REVIEW as SDRF_REVIEW_REVISED_REV2 } from '../modules/local/sdrf_review'
include { SUMMARISE_REVIEWS ; isTrue ; readReview ; withCoverage } from '../subworkflows/local/utils_sdrf_agent'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

workflow SDRF_AGENT {
    take:
    ch_pxds // channel: PXD accessions

    main:
    ch_annotated = SDRF_ANNOTATE(ch_pxds)

    // ---- deterministic coverage precheck (improvement 1 + file-existence, improvement 3) ----
    // Runs the SDRF's data files against the PRIDE deposit file list BEFORE the adversarial pass.
    ch_initial_cov = SDRF_COVERAGE(ch_annotated.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })
    // The reviewer gets the SDRF, the evidence manifest, and the coverage report (not the producer report)
    ch_reviewed = SDRF_REVIEW(withCoverage(ch_annotated, ch_initial_cov))

    // ---- bounded revise / escalation loop (improvement 3) ----
    // Statically unrolled with `if` guards (Nextflow DSL does not allow process calls in a for
    // loop), so at most two rounds. Each round re-runs coverage on the revised SDRF and re-reviews
    // only the still-failing records. A reproducible content FAIL is not a crash: it stays the
    // final record for that PXD.
    ch_rev1_view = channel.empty()
    ch_rev2_view = channel.empty()
    ch_revised_all = channel.empty()
    ch_revised_review = channel.empty()
    if (isTrue(params.revise) && (params.max_revise as Integer) >= 1) {
        // ---- round 1 ----
        ch_rev1 = SDRF_REVISE(failedReviews(ch_reviewed))
        ch_rev1_view = SDRF_REVIEW_REVISED(withCoverage(ch_rev1, SDRF_COVERAGE_REV1(ch_rev1.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })))

        ch_revised_all = ch_revised_all.mix(ch_rev1.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, report: r.report, dir: 'revised') })
        ch_revised_review = ch_revised_review.mix(ch_rev1_view.map { r -> record(pxd: r.pxd, review: r.review, coverage: r.coverage, dir: 'revised') })

        // ---- round 2 (only if max_revise >= 2) ----
        if ((params.max_revise as Integer) >= 2) {
            ch_rev2 = SDRF_REVISE_REV2(failedReviews(ch_rev1_view))
            ch_rev2_view = SDRF_REVIEW_REVISED_REV2(withCoverage(ch_rev2, SDRF_COVERAGE_REV2(ch_rev2.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })))

            ch_revised_all = ch_revised_all.mix(ch_rev2.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, report: r.report, dir: 'revised_2') })
            ch_revised_review = ch_revised_review.mix(ch_rev2_view.map { r -> record(pxd: r.pxd, review: r.review, coverage: r.coverage, dir: 'revised_2') })
        }
    }

    // ---- summary with coverage + confidence + content-vs-infra classification ----
    // A final content verdict of FAIL/LOW_CONF is reported by PIPELINE_COMPLETION as a warning
    // (not a crash) unless exit_on_review_fail is requested.
    SUMMARISE_REVIEWS(ch_reviewed, ch_rev1_view, ch_rev2_view)

    emit:
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised_all
    revised_review = ch_revised_review
    coverage = ch_initial_cov.map { pxd, cov, _sdrf, _manifest -> record(pxd: pxd, coverage: cov) }
    summary = SUMMARISE_REVIEWS.out.summary
}

// Revise input records for every review that did not PASS
def failedReviews(ch_views) {
    return ch_views
        .filter { r -> readReview(r.review).verdict != 'PASS' }
        .map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, review: r.review) }
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES AND SUBWORKFLOWS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SCORE_SDRF as SCORE_BASELINE } from '../subworkflows/local/score_sdrf'
include { REVIEW_REVISE } from '../subworkflows/local/review_revise'
include { SDRF_SUMMARY } from '../subworkflows/local/sdrf_summary'
include { REFINE_GATE } from '../subworkflows/local/refine_gate'
include { verdictOf } from '../subworkflows/local/utils_sdrf_agent'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Annotate mode: annotate each PXD, then review and revise the SDRF.
Refine mode (--refine): refine the existing SDRF of each PXD, review and revise it, and
accept it only if it scores strictly better than the existing SDRF on the same review.
----------------------------------------------------------------------------------------
 */

workflow SDRF_AGENTIC_ANNOTATOR {
    take:
    ch_samplesheet // records: pxd, ref_sdrf (refine mode only, optional)

    main:
    ch_annotated = channel.empty()
    ch_reviewed = channel.empty()
    ch_revised = channel.empty()
    ch_revised_review = channel.empty()
    ch_coverage = channel.empty()
    ch_refine_decision = channel.empty()
    ch_refine_verdict = channel.empty()

    if (params.refine) {
        // The existing SDRF is the samplesheet's ref_sdrf, else the one in bigbio/sdrf-annotated-datasets
        ch_has_ref = ch_samplesheet
            .filter { r -> r.ref_sdrf }
            .map { r -> record(pxd: r.pxd, baseline: file(r.ref_sdrf as String)) }
        ch_fetched = SDRF_FETCH_BASELINE(ch_samplesheet.filter { r -> !r.ref_sdrf }.map { r -> r.pxd })
        ch_sdrf = SDRF_REFINE(ch_has_ref.mix(ch_fetched))
        max_rounds = params.revise ? 1 : 0
    }
    else {
        ch_sdrf = SDRF_ANNOTATE(ch_samplesheet.map { r -> r.pxd })
        max_rounds = params.revise ? params.max_revise : 0
    }

    REVIEW_REVISE(ch_sdrf, max_rounds)

    if (params.refine) {
        ch_baseline_review = SCORE_BASELINE(ch_sdrf.map { r -> record(pxd: r.pxd, sdrf: r.baseline_sdrf, manifest: r.baseline_manifest) }).review
        // Without revise, only a refined SDRF that passes its review can replace the baseline
        ch_refined_review = REVIEW_REVISE.out.last_review.filter { r -> params.revise || verdictOf(r.review) == 'PASS' }
        REFINE_GATE(ch_baseline_review, ch_refined_review)
        ch_summary = REFINE_GATE.out.summary
        ch_refine_decision = REFINE_GATE.out.decision
        ch_refine_verdict = REFINE_GATE.out.verdict
    }
    else {
        ch_summary = SDRF_SUMMARY(REVIEW_REVISE.out.reviewed, REVIEW_REVISE.out.revised_review).summary
        ch_annotated = ch_sdrf
        ch_reviewed = REVIEW_REVISE.out.reviewed
        ch_revised = REVIEW_REVISE.out.revised
        ch_revised_review = REVIEW_REVISE.out.revised_review
        ch_coverage = REVIEW_REVISE.out.coverage
    }

    emit:
    summary = ch_summary // path: summary.tsv, or refine_summary.tsv in refine mode
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised
    revised_review = ch_revised_review
    coverage = ch_coverage
    refine_decision = ch_refine_decision
    refine_verdict = ch_refine_verdict
}

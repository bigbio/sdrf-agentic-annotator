/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES AND SUBWORKFLOWS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_FREEZE_BASELINE } from '../modules/local/sdrf_freeze_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SCORE_SDRF as SCORE_BASELINE } from '../subworkflows/local/score_sdrf'
include { REVIEW_REVISE } from '../subworkflows/local/review_revise'
include { SUMMARISE_REVIEWS } from '../subworkflows/local/summarise_reviews'
include { REFINE_DECISION } from '../subworkflows/local/refine_decision'
include { isTrue ; softwareVersionsToYAML } from '../subworkflows/local/utils_sdrf_agent'

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

    max_rounds = isTrue(params.revise) ? (params.max_revise as Integer) : 0

    if (isTrue(params.refine)) {
        // The existing SDRF is the samplesheet's ref_sdrf, else the one in bigbio/sdrf-annotated-datasets
        ch_has_ref = ch_samplesheet
            .filter { r -> r.ref_sdrf }
            .map { r -> record(pxd: r.pxd, baseline: r.ref_sdrf) }
        ch_fetched = SDRF_FETCH_BASELINE(ch_samplesheet.filter { r -> !r.ref_sdrf }.map { r -> r.pxd })
        // The baseline that is scored and published, and a separate copy for the refine agent
        ch_frozen = SDRF_FREEZE_BASELINE(ch_has_ref.mix(ch_fetched))
        ch_sdrf = SDRF_REFINE(ch_frozen.map { r -> record(pxd: r.pxd, baseline: r.agent_baseline) })

        // Refine mode revises the refined SDRF at most once
        REVIEW_REVISE(ch_sdrf, Math.min(max_rounds, 1))

        ch_baseline = ch_sdrf
            .map { r -> record(pxd: r.pxd, manifest: r.baseline_manifest) }
            .join(ch_frozen.map { r -> record(pxd: r.pxd, sdrf: r.baseline) }, by: 'pxd')
        REFINE_DECISION(SCORE_BASELINE(ch_baseline).review, REVIEW_REVISE.out.last_review)
        ch_summary = REFINE_DECISION.out.summary
        ch_refine_decision = REFINE_DECISION.out.decision
        ch_refine_verdict = REFINE_DECISION.out.verdict
    }
    else {
        ch_sdrf = SDRF_ANNOTATE(ch_samplesheet.map { r -> r.pxd })
        REVIEW_REVISE(ch_sdrf, max_rounds)
        SUMMARISE_REVIEWS(REVIEW_REVISE.out.reviewed, REVIEW_REVISE.out.review_1, REVIEW_REVISE.out.review_2)
        ch_summary = SUMMARISE_REVIEWS.out.summary
        ch_annotated = ch_sdrf
        ch_reviewed = REVIEW_REVISE.out.reviewed
        ch_revised = REVIEW_REVISE.out.revised
        ch_revised_review = REVIEW_REVISE.out.revised_review
        ch_coverage = REVIEW_REVISE.out.coverage
    }

    ch_versions = channel.topic('versions')
        .unique()
        .toList()
        .map { rows -> softwareVersionsToYAML(rows) }
        .collectFile(name: 'software_versions.yml')

    emit:
    summary = ch_summary // path: summary.tsv, or refine_summary.tsv in refine mode
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised
    revised_review = ch_revised_review
    coverage = ch_coverage
    refine_decision = ch_refine_decision
    refine_verdict = ch_refine_verdict
    versions = ch_versions // path: software_versions.yml
}

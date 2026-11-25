/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES AND SUBWORKFLOWS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_ANNOTATE } from '../modules/local/sdrf_annotate'
include { SDRF_PREFILL } from '../modules/local/sdrf_prefill'
include { SDRF_STAMP } from '../modules/local/sdrf_stamp'
include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_FREEZE_BASELINE } from '../modules/local/sdrf_freeze_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SCORE_SDRF as SCORE_BASELINE } from '../subworkflows/local/score_sdrf'
include { REVIEW_REVISE } from '../subworkflows/local/review_revise'
include { SUMMARISE_REVIEWS } from '../subworkflows/local/summarise_reviews'
include { REFINE_DECISION } from '../subworkflows/local/refine_decision'
include { existingSdrf ; isTrue ; qcFiles ; readReview ; softwareVersionsToYAML } from '../subworkflows/local/utils_sdrf_agent'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Annotate mode: annotate each PXD, then review and revise the SDRF.
Refine mode (--refine): refine the existing SDRF of each PXD, review and revise it, and
accept it only if it scores strictly better than the existing SDRF on the same review.
Review-existing mode (--review_existing): review and revise the SDRF already in each row's
`ref_dir` (an earlier annotate task's folder), without annotating again.
----------------------------------------------------------------------------------------
 */

workflow SDRF_AGENTIC_ANNOTATOR {
    take:
    ch_samplesheet // records: pxd, ref_sdrf (refine mode, optional), ref_dir (review-existing mode)

    main:
    ch_annotated = channel.empty()
    ch_reviewed = channel.empty()
    ch_revised = channel.empty()
    ch_revised_review = channel.empty()
    ch_coverage = channel.empty()
    ch_final = channel.empty()
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
    else if (isTrue(params.review_existing)) {
        // Review an SDRF that is already annotated (the folder of an earlier annotate task, `ref_dir`):
        // no annotate step; the review, revise and stamp steps are those of annotate mode.
        ch_sdrf = ch_samplesheet
            .filter { r -> r.ref_dir }
            .map { r -> existingSdrf(r.pxd, r.ref_dir) }
            .filter { m ->
                if (!m.manifest) {
                    log.warn("--review_existing: ${m.pxd} has no ${m.pxd}.evidence.json in its ref_dir; skipped")
                }
                m.manifest != null
            }
            .map { m -> record(pxd: m.pxd, sdrf: m.sdrf, manifest: m.manifest, validation: m.validation, report: m.report, samples: m.samples, technical: m.technical, evidence: m.evidence) }
        REVIEW_REVISE(ch_sdrf, max_rounds)
        SUMMARISE_REVIEWS(REVIEW_REVISE.out.reviewed, REVIEW_REVISE.out.review_1, REVIEW_REVISE.out.review_2, REVIEW_REVISE.out.revised)
        ch_summary = SUMMARISE_REVIEWS.out.summary
        ch_reviewed = REVIEW_REVISE.out.reviewed
        ch_revised = REVIEW_REVISE.out.revised
        ch_revised_review = REVIEW_REVISE.out.revised_review
        ch_coverage = REVIEW_REVISE.out.coverage
        ch_final = SDRF_STAMP(REVIEW_REVISE.out.last_review.filter { r -> readReview(r.review).verdict == 'PASS' }.map { r -> record(pxd: r.pxd, sdrf: r.sdrf) })
    }
    else {
        ch_pxd = ch_samplesheet.map { r -> r.pxd }
        // The evidence sheet uses the ontology caches (--ontology_dir) and the corpus index (default: the bundled one)
        ontology_dir = params.ontology_dir ? file(params.ontology_dir) : null
        corpus_index = file(params.corpus_index ?: "${projectDir}/assets/corpus_index.tsv.gz")
        ch_start = isTrue(params.prefill)
            ? SDRF_PREFILL(ch_pxd.map { pxd -> record(pxd: pxd, ontology_dir: ontology_dir, corpus_index: corpus_index, qc: qcFiles(pxd, params.qc_index)) })
                .map { r -> record(pxd: r.pxd, prefill: r.prefill, sheet: isTrue(params.sheet) ? r.sheet : null) }
            : ch_pxd.map { pxd -> record(pxd: pxd, prefill: null, sheet: null) }
        ch_sdrf = SDRF_ANNOTATE(ch_start)
        REVIEW_REVISE(ch_sdrf, max_rounds)
        SUMMARISE_REVIEWS(REVIEW_REVISE.out.reviewed, REVIEW_REVISE.out.review_1, REVIEW_REVISE.out.review_2, REVIEW_REVISE.out.revised)
        ch_summary = SUMMARISE_REVIEWS.out.summary
        ch_annotated = ch_sdrf
        ch_reviewed = REVIEW_REVISE.out.reviewed
        ch_revised = REVIEW_REVISE.out.revised
        ch_revised_review = REVIEW_REVISE.out.revised_review
        ch_coverage = REVIEW_REVISE.out.coverage
        // The SDRF of a passing last review, with this pipeline named as its annotation tool
        ch_final = SDRF_STAMP(REVIEW_REVISE.out.last_review.filter { r -> readReview(r.review).verdict == 'PASS' }.map { r -> record(pxd: r.pxd, sdrf: r.sdrf) })
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
    final_sdrf = ch_final // records: pxd, sdrf, validation of each passing SDRF
    refine_decision = ch_refine_decision
    refine_verdict = ch_refine_verdict
    versions = ch_versions // path: software_versions.yml
}

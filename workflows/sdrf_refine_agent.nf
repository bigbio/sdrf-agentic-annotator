/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SCORE_SDRF as SCORE_BASELINE } from '../subworkflows/local/score_sdrf'
include { REVIEW_REVISE } from '../subworkflows/local/review_revise'
include { REFINE_GATE } from '../subworkflows/local/refine_gate'
include { verdictOf } from '../subworkflows/local/utils_sdrf_agent'

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

    // ---- baseline and refined score: coverage precheck + independent adversarial review ----
    ch_base_rev = SCORE_BASELINE(ch_refined.map { r -> record(pxd: r.pxd, sdrf: r.baseline_sdrf, manifest: r.baseline_manifest) }).review

    // The refined SDRF gets one revise round if its review fails. Without revise, only a PASS can compete.
    REVIEW_REVISE(ch_refined, params.revise ? 1 : 0)
    ch_final_rev = REVIEW_REVISE.out.last_review.filter { r -> params.revise || verdictOf(r.review) == 'PASS' }

    // ---- acceptance gate: accept refined only if strictly better ----
    REFINE_GATE(ch_base_rev, ch_final_rev)

    emit:
    refined = ch_refined
    baseline = ch_baseline
    baseline_review = ch_base_rev
    decision = REFINE_GATE.out.decision
    verdict = REFINE_GATE.out.verdict
    summary = REFINE_GATE.out.summary
}

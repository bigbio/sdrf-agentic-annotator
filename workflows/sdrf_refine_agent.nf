/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_FREEZE_BASELINE } from '../modules/local/sdrf_freeze_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SDRF_REVIEW as SDRF_REVIEW_BASELINE } from '../modules/local/sdrf_review'
include { SDRF_REVIEW as SDRF_REVIEW_REFINED } from '../modules/local/sdrf_review'
include { SDRF_REVIEW as SDRF_REVIEW_REFV2 } from '../modules/local/sdrf_review'
include { SDRF_COVERAGE as SDRF_COVERAGE_BASELINE } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REFINED } from '../modules/local/sdrf_coverage'
include { SDRF_COVERAGE as SDRF_COVERAGE_REFV2 } from '../modules/local/sdrf_coverage'
include { SDRF_REVISE } from '../modules/local/sdrf_revise'
include { REFINE_DECISION ; isTrue ; readReview ; withCoverage } from '../subworkflows/local/utils_sdrf_agent'

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
    ch_rows // records: pxd (String), ref_sdrf (Path or null)

    main:

    // ---- baseline acquisition: local path if given, else fetch from sdrf-annotated-datasets ----
    ch_has_ref = ch_rows
        .filter { r -> r.ref_sdrf != null }
        .map { r -> tuple(r.pxd, r.ref_sdrf) }
    ch_no_ref = ch_rows
        .filter { r -> r.ref_sdrf == null }
        .map { r -> r.pxd }
    // The baseline that is scored and published, and a separate copy for the refine agent
    ch_frozen = SDRF_FREEZE_BASELINE(ch_has_ref.mix(SDRF_FETCH_BASELINE(ch_no_ref)))
    ch_baseline = ch_frozen.map { pxd, baseline, _agent_copy -> record(pxd: pxd, baseline: baseline) }

    // ---- refine agent: seeded re-annotation + baseline evidence manifest ----
    ch_refined = SDRF_REFINE(ch_frozen.map { pxd, _baseline, agent_copy -> record(pxd: pxd, baseline: agent_copy) })

    // ---- baseline score: coverage precheck + independent adversarial review ----
    // The baseline scored (and published if kept) is the pipeline's copy, not the agent's.
    ch_base_in = ch_refined
        .map { r -> tuple(r.pxd, r.baseline_manifest) }
        .join(ch_baseline.map { r -> tuple(r.pxd, r.baseline) })
        .map { pxd, manifest, baseline -> record(pxd: pxd, sdrf: baseline, manifest: manifest) }
    ch_base_rev = SDRF_REVIEW_BASELINE(withCoverage(ch_base_in, SDRF_COVERAGE_BASELINE(ch_base_in.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })))

    // ---- refined score (initial) ----
    ch_ref_rev = SDRF_REVIEW_REFINED(withCoverage(ch_refined, SDRF_COVERAGE_REFINED(ch_refined.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })))

    // ---- latest review of the refined SDRF: revised once if its first review fails ----
    ch_final_rev = ch_ref_rev
    if (isTrue(params.revise) && (params.max_revise as Integer) >= 1) {
        ch_ref_pass = ch_ref_rev.filter { r -> readReview(r.review).verdict == 'PASS' }
        ch_rev = SDRF_REVISE(
            ch_ref_rev.filter { r -> readReview(r.review).verdict != 'PASS' }.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, review: r.review) }
        )
        ch_rev_view = SDRF_REVIEW_REFV2(withCoverage(ch_rev, SDRF_COVERAGE_REFV2(ch_rev.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })))
        ch_final_rev = ch_ref_pass.mix(ch_rev_view)
    }

    // ---- acceptance gate: accept refined only if strictly better ----
    REFINE_DECISION(ch_base_rev, ch_final_rev)

    emit:
    refined = ch_refined
    baseline = ch_baseline
    baseline_review = ch_base_rev
    decision = REFINE_DECISION.out.decision
    verdict = REFINE_DECISION.out.verdict
    summary = REFINE_DECISION.out.summary
}

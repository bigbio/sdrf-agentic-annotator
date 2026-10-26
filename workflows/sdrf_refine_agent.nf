/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
IMPORT MODULES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_FETCH_BASELINE } from '../modules/local/sdrf_fetch_baseline'
include { SDRF_REFINE } from '../modules/local/sdrf_refine'
include { SCORE_SDRF as SCORE_BASELINE } from '../subworkflows/local/score_sdrf'
include { REVIEW_REVISE } from '../subworkflows/local/review_revise'
include { verdictOf ; parseReview ; coverageFraction ; isBetter } from '../subworkflows/local/utils_sdrf_agent'

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

    // ---- baseline and refined score: coverage precheck + independent adversarial review ----
    ch_base_rev = SCORE_BASELINE(ch_refined.map { r -> record(pxd: r.pxd, sdrf: r.baseline_sdrf, manifest: r.baseline_manifest) }).review

    // The refined SDRF gets one revise round if its review fails. Without revise, only a PASS can compete.
    REVIEW_REVISE(ch_refined, params.revise ? 1 : 0)
    ch_final_rev = REVIEW_REVISE.out.last_review.filter { r -> params.revise || verdictOf(r.review) == 'PASS' }

    // ---- acceptance gate: accept refined only if strictly better ----
    ch_decision = ch_base_rev
        .map { r -> tuple(r.pxd, r) }
        .join(ch_final_rev.map { r -> tuple(r.pxd, r) }, remainder: true)
        .map { pxd, b, f ->
            def bv = parseReview(b.review)
            def bc = coverageFraction(b.coverage)
            def reason = 'kept original (no improvement)'
            def chosen = 'baseline'
            if (f) {
                def fv = parseReview(f.review)
                def fc = coverageFraction(f.coverage)
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

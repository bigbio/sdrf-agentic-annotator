/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REVIEW_REVISE - score an SDRF, then revise and score it again while the review fails
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nextflow cannot call a process in a loop, so the rounds are unrolled up to the schema
maximum of 2. A FAIL after the last round is a content outcome: it stays the final review.
----------------------------------------------------------------------------------------
 */

include { SCORE_SDRF } from '../score_sdrf'
include { REVISE_SDRF as REVISE_ROUND_1 } from '../revise_sdrf'
include { REVISE_SDRF as REVISE_ROUND_2 } from '../revise_sdrf'
include { verdictOf } from '../utils_sdrf_agent'

workflow REVIEW_REVISE {
    take:
    ch_sdrf // records: pxd, sdrf, manifest, validation, samples, technical, evidence (all but the first three optional)
    max_rounds // integer: number of revise rounds, 0 to 2

    main:
    SCORE_SDRF(ch_sdrf)
    ch_reviewed = SCORE_SDRF.out.review
    ch_evidence = ch_sdrf.map { r -> record(pxd: r.pxd, evidence: r.evidence) }

    ch_revised = channel.empty()
    ch_revised_review = channel.empty()
    ch_last_review = ch_reviewed
    if (max_rounds >= 1) {
        ch_failed_1 = ch_reviewed
            .filter { r -> verdictOf(r.review) != 'PASS' }
            .map { r -> record(pxd: r.pxd, review: r.review) }
            .join(ch_sdrf.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, samples: r.samples, technical: r.technical, evidence: r.evidence) }, by: 'pxd')
        REVISE_ROUND_1(ch_failed_1)
        ch_revised = ch_revised.mix(REVISE_ROUND_1.out.revised)
        ch_revised_review = ch_revised_review.mix(REVISE_ROUND_1.out.review)
        ch_last_review = ch_reviewed.filter { r -> verdictOf(r.review) == 'PASS' }.mix(REVISE_ROUND_1.out.review)

        if (max_rounds >= 2) {
            ch_failed_2 = REVISE_ROUND_1.out.review
                .filter { r -> verdictOf(r.review) != 'PASS' }
                .map { r -> record(pxd: r.pxd, review: r.review) }
                .join(REVISE_ROUND_1.out.revised.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, samples: r.samples, technical: r.technical) }, by: 'pxd')
                .join(ch_evidence, by: 'pxd')
            REVISE_ROUND_2(ch_failed_2)
            ch_revised = ch_revised.mix(REVISE_ROUND_2.out.revised)
            ch_revised_review = ch_revised_review.mix(REVISE_ROUND_2.out.review)
            ch_last_review = ch_last_review.filter { r -> verdictOf(r.review) == 'PASS' }.mix(REVISE_ROUND_2.out.review)
        }
    }

    emit:
    reviewed = ch_reviewed // records: pxd, sdrf, coverage, review of the first review
    coverage = SCORE_SDRF.out.coverage // records: pxd, coverage of the first review
    revised = ch_revised // records: SDRF_REVISE output of each round
    revised_review = ch_revised_review // records: pxd, sdrf, coverage, review of each round
    last_review = ch_last_review // records: pxd, sdrf, coverage, review of the last review
}

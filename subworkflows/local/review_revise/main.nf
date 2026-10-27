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
include { readReview } from '../utils_sdrf_agent'

workflow REVIEW_REVISE {
    take:
    ch_sdrf // records: pxd, sdrf, manifest, validation, samples, technical, evidence (all but the first three optional)
    max_rounds // integer: number of revise rounds, 0 to 2

    main:
    SCORE_SDRF(ch_sdrf)
    ch_reviewed = SCORE_SDRF.out.review
    ch_evidence = ch_sdrf.map { r -> record(pxd: r.pxd, evidence: r.evidence) }

    ch_review_1 = channel.empty()
    ch_review_2 = channel.empty()
    ch_revised = channel.empty()
    ch_last_review = ch_reviewed
    if (max_rounds >= 1) {
        ch_failed_1 = ch_reviewed
            .filter { r -> readReview(r.review).verdict != 'PASS' }
            .map { r -> record(pxd: r.pxd, review: r.review) }
            .join(ch_sdrf.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, samples: r.samples, technical: r.technical, evidence: r.evidence) }, by: 'pxd')
        REVISE_ROUND_1(ch_failed_1)
        ch_review_1 = REVISE_ROUND_1.out.review
        ch_revised = ch_revised.mix(REVISE_ROUND_1.out.revised.map { r -> revisedOutputs(r, 'revised') })
        ch_last_review = ch_reviewed.filter { r -> readReview(r.review).verdict == 'PASS' }.mix(ch_review_1)

        if (max_rounds >= 2) {
            ch_failed_2 = ch_review_1
                .filter { r -> readReview(r.review).verdict != 'PASS' }
                .map { r -> record(pxd: r.pxd, review: r.review) }
                .join(REVISE_ROUND_1.out.revised.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, samples: r.samples, technical: r.technical) }, by: 'pxd')
                .join(ch_evidence, by: 'pxd')
            REVISE_ROUND_2(ch_failed_2)
            ch_review_2 = REVISE_ROUND_2.out.review
            ch_revised = ch_revised.mix(REVISE_ROUND_2.out.revised.map { r -> revisedOutputs(r, 'revised_2') })
            ch_last_review = ch_last_review.filter { r -> readReview(r.review).verdict == 'PASS' }.mix(ch_review_2)
        }
    }

    ch_revised_review = ch_review_1
        .map { r -> record(pxd: r.pxd, review: r.review, coverage: r.coverage, dir: 'revised') }
        .mix(ch_review_2.map { r -> record(pxd: r.pxd, review: r.review, coverage: r.coverage, dir: 'revised_2') })

    emit:
    reviewed = ch_reviewed // records: pxd, sdrf, manifest, coverage, review of the first review
    coverage = SCORE_SDRF.out.coverage // records: pxd, coverage of the first review
    review_1 = ch_review_1 // records: pxd, sdrf, manifest, coverage, review after revise round 1
    review_2 = ch_review_2 // records: pxd, sdrf, manifest, coverage, review after revise round 2
    revised = ch_revised // records: SDRF_REVISE output of each round, with its publish dir
    revised_review = ch_revised_review // records: pxd, review, coverage of each round, with its publish dir
    last_review = ch_last_review // records: pxd, sdrf, manifest, coverage, review of the last review
}

// The files of one revise round to publish in <pxd>/<dir>/
def revisedOutputs(r, dir) {
    return record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest, validation: r.validation, report: r.report, samples: r.samples, technical: r.technical, dir: dir)
}

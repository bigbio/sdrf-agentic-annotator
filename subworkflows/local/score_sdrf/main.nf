/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SCORE_SDRF - coverage precheck and independent adversarial review of an SDRF
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 */

include { SDRF_COVERAGE } from '../../../modules/local/sdrf_coverage'
include { SDRF_REVIEW } from '../../../modules/local/sdrf_review'

workflow SCORE_SDRF {
    take:
    ch_sdrf // records: pxd, sdrf, manifest, validation (optional), evidence (optional)

    main:
    ch_coverage = SDRF_COVERAGE(ch_sdrf.map { r -> tuple(r.pxd, r.sdrf, r.manifest) })

    // The reviewer gets the original request and the hand-off files, never the producer report
    ch_review_in = ch_sdrf
        .map { r -> tuple(r.pxd, r) }
        .join(ch_coverage.map { pxd, cov, _sdrf, _manifest -> tuple(pxd, cov) }, failOnDuplicate: true)
        .map { pxd, r, cov -> record(pxd: pxd, sdrf: r.sdrf, manifest: r.manifest, coverage: cov, validation: r.validation, evidence: r.evidence) }
    ch_review = SDRF_REVIEW(ch_review_in)

    emit:
    review = ch_review // records: pxd, sdrf, coverage, review
    coverage = ch_coverage.map { pxd, cov, _sdrf, _manifest -> record(pxd: pxd, coverage: cov) }
}

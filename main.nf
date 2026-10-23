include { SDRF_ANNOTATE } from './modules/sdrf_annotate'
include { SDRF_REVIEW   } from './modules/sdrf_review'

params.pxd = 'PXD074155'

workflow {
    main:
    ch_annotated = SDRF_ANNOTATE(channel.of(params.pxd))

    // The reviewer gets the SDRF and the evidence manifest only, not the producer report
    ch_reviewed = SDRF_REVIEW(ch_annotated.map { r -> record(pxd: r.pxd, sdrf: r.sdrf, manifest: r.manifest) })

    ch_reviewed.view { r -> "${r.pxd}: verdict=${new groovy.json.JsonSlurper().parse(r.review.toFile()).verdict}" }

    publish:
    annotated = ch_annotated
    reviewed  = ch_reviewed
}

output {
    annotated { path { r -> r.pxd } }
    reviewed  { path { r -> r.pxd } }
}

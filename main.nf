#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
bigbio/sdrf-agentic-annotator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Github : https://github.com/bigbio/sdrf-agentic-annotator
----------------------------------------------------------------------------------------
 */

include { SDRF_AGENT } from './workflows/sdrf_agent'
include { SDRF_REFINE_AGENT } from './workflows/sdrf_refine_agent'
include { PIPELINE_INITIALISATION ; PIPELINE_REFINE_INITIALISATION ; PIPELINE_COMPLETION ; isTrue } from './subworkflows/local/utils_sdrf_agent'

workflow {

    main:
    // Unified publish channel placeholders: each is populated by the branch that produces it and
    // stays empty in the other mode, so the publish/output blocks below stay flat (no if/else).
    ch_summary = channel.empty()
    ch_annotated = channel.empty()
    ch_reviewed = channel.empty()
    ch_revised = channel.empty()
    ch_revised_review = channel.empty()
    ch_coverage = channel.empty()
    ch_refine_decision = channel.empty()
    ch_refine_verdict = channel.empty()

    if (isTrue(params.refine)) {
        PIPELINE_REFINE_INITIALISATION(params.input)
        SDRF_REFINE_AGENT(PIPELINE_REFINE_INITIALISATION.out.rows)
        PIPELINE_COMPLETION(SDRF_REFINE_AGENT.out.summary)
        ch_summary = SDRF_REFINE_AGENT.out.summary
        ch_refine_decision = SDRF_REFINE_AGENT.out.decision
        ch_refine_verdict = SDRF_REFINE_AGENT.out.verdict
    }
    else {
        PIPELINE_INITIALISATION(params.input)
        SDRF_AGENT(PIPELINE_INITIALISATION.out.pxds)
        PIPELINE_COMPLETION(SDRF_AGENT.out.summary)
        ch_summary = SDRF_AGENT.out.summary
        ch_annotated = SDRF_AGENT.out.annotated
        ch_reviewed = SDRF_AGENT.out.reviewed
        ch_revised = SDRF_AGENT.out.revised
        ch_revised_review = SDRF_AGENT.out.revised_review
        ch_coverage = SDRF_AGENT.out.coverage
    }

    publish:
    summary = ch_summary
    annotated = ch_annotated
    reviewed = ch_reviewed
    revised = ch_revised
    revised_review = ch_revised_review
    coverage = ch_coverage
    refine_decision = ch_refine_decision
    refine_verdict = ch_refine_verdict
}
output {
    annotated {
        path { r ->
            r.sdrf >> "${r.pxd}/${r.sdrf.name}"
            r.manifest >> "${r.pxd}/${r.manifest.name}"
            r.report >> "${r.pxd}/${r.report.name}"
        }
    }
    reviewed {
        path { r -> r.review >> "${r.pxd}/${r.review.name}" }
    }
    coverage {
        path { r -> r.coverage >> "${r.pxd}/${r.coverage.name}" }
    }
    // revise round 1 in <pxd>/revised/, round 2 in <pxd>/revised_2/
    revised {
        path { r ->
            r.sdrf >> "${r.pxd}/${r.dir}/${r.sdrf.name}"
            r.manifest >> "${r.pxd}/${r.dir}/${r.manifest.name}"
            r.report >> "${r.pxd}/${r.dir}/${r.report.name}"
        }
    }
    revised_review {
        path { r ->
            r.review >> "${r.pxd}/${r.dir}/${r.review.name}"
            r.coverage >> "${r.pxd}/${r.dir}/${r.coverage.name}"
        }
    }
    summary {
        path '.'
    }
    // the chosen SDRF (refined or existing) with its evidence manifest, review and coverage report
    refine_decision {
        path { r ->
            r.sdrf >> "${r.pxd}/${r.pxd}.sdrf.tsv"
            r.manifest >> "${r.pxd}/${r.pxd}.evidence.json"
            r.review >> "${r.pxd}/${r.pxd}.review.json"
            r.coverage >> "${r.pxd}/${r.pxd}.coverage.json"
        }
    }
    refine_verdict {
        path { r -> r.verdict >> "${r.pxd}/${r.verdict.name}" }
    }
}

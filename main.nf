#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
bigbio/sdrf-agentic-annotator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Github : https://github.com/bigbio/sdrf-agentic-annotator
----------------------------------------------------------------------------------------
 */

include { SDRF_AGENT } from './workflows/sdrf_agent'
include { PIPELINE_INITIALISATION } from './subworkflows/local/utils_sdrf_agent'
include { PIPELINE_COMPLETION } from './subworkflows/local/utils_sdrf_agent'

workflow {

    main:
    PIPELINE_INITIALISATION(params.input)

    SDRF_AGENT(PIPELINE_INITIALISATION.out.pxds)

    PIPELINE_COMPLETION(SDRF_AGENT.out.summary)

    publish:
    annotated = SDRF_AGENT.out.annotated
    reviewed = SDRF_AGENT.out.reviewed
    revised = SDRF_AGENT.out.revised
    revised_review = SDRF_AGENT.out.revised_review
    coverage = SDRF_AGENT.out.coverage
    summary = SDRF_AGENT.out.summary
}
output {
    annotated {
        path { r -> r.pxd }
    }
    reviewed {
        path { r -> r.pxd }
    }
    revised {
        path { r -> "${r.pxd}/revised" }
    }
    revised_review {
        path { r -> "${r.pxd}/revised" }
    }
    coverage {
        path { r -> r.pxd }
    }
    summary {
        path '.'
    }
}

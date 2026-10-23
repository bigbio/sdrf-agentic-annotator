#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
jonasscheid/nf-agent-sdrf
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Github : https://github.com/jonasscheid/nf-agent-sdrf
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
    summary {
        path '.'
    }
}

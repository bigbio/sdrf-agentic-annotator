# -*- coding: utf-8 -*-
"""Benchmark data table: manual annotation vs skills (AI) annotation.

Fields per dataset:
    name              - PRIDE accession
    human_time_min    - manual annotation time (minutes), provided by the human annotator
    skills_time_min   - skills (AI) annotation wall-clock time (minutes), measured per task
    fresh_input_tokens - model input tokens excluding cached context reads
                         (inputTokens - cacheReadTokens from the model-io log)
    output_tokens     - model output tokens
"""

DATASETS = [
    # name,        human_time_min, skills_time_min, fresh_input_tokens, output_tokens
    ('PXD019515', 20.0, 4.322, 16_355, 11_953),
    ('PXD005354', 45.0, 10.480, 23_727, 19_704),
    ('PXD015744', 35.0, 3.141, 27_431, 11_148),
    ('PXD013923', 46.0, 3.650, 23_409, 12_633),
]


def stats():
    """Return aggregate statistics for the current table."""
    import statistics
    human = [d[1] for d in DATASETS]
    skills = [d[2] for d in DATASETS]
    speedups = [h / s for h, s in zip(human, skills)]
    return {
        'datasets': [d[0] for d in DATASETS],
        'human_time': human,
        'skills_time': skills,
        'fresh_input_tokens': [d[3] for d in DATASETS],
        'output_tokens': [d[4] for d in DATASETS],
        'human_median': statistics.median(human),
        'skills_median': statistics.median(skills),
        'human_total': sum(human),
        'skills_total': sum(skills),
        'speedups': speedups,
        'median_speedup': statistics.median(human) / statistics.median(skills),
    }


if __name__ == '__main__':
    s = stats()
    print(f"{'dataset':12s} {'manual_min':>10s} {'skills_min':>10s} {'speedup':>8s} "
          f"{'input_tok':>10s} {'output_tok':>10s}")
    for i, name in enumerate(s['datasets']):
        print(f"{name:12s} {s['human_time'][i]:10.1f} {s['skills_time'][i]:10.2f} "
              f"{s['speedups'][i]:8.1f}x {s['fresh_input_tokens'][i]:10,d} "
              f"{s['output_tokens'][i]:10,d}")
    print(f"\nmedian: manual {s['human_median']:.1f} min vs skills {s['skills_median']:.2f} min "
          f"({s['median_speedup']:.1f}x)")
    print(f"total:  manual {s['human_total']:.1f} min vs skills {s['skills_total']:.2f} min")

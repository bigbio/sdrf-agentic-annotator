import json

from sdrf_model_bench.judge import judge
from sdrf_model_bench.providers import Completion


def test_median_of_three_and_blind_prompt():
    scores = iter([(10, 10, 10), (6, 4, 2), (8, 6, 4)])
    prompts = []

    def gen(msgs):
        prompts.append(msgs[-1]["content"])
        f, d, t = next(scores)
        return Completion(json.dumps({"factor_fidelity": f, "design_fidelity": d, "free_text": t}),
                          {"input_tokens": 1, "output_tokens": 1})

    r = judge(gen, "REF", "PRED")
    assert (r["factor_fidelity"], r["design_fidelity"], r["free_text"]) == (8, 6, 4)
    assert r["judge"] == 60.0 and r["usage"]["input_tokens"] == 3
    assert "REF" in prompts[0] and "PRED" in prompts[0]


def test_unparseable_judge_is_none():
    r = judge(lambda m: Completion("I refuse", {}), "a", "b")
    assert r["judge"] is None

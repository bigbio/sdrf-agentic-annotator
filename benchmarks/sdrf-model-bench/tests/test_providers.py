import sys
import types

import pytest

from sdrf_model_bench.config import ModelSpec
from sdrf_model_bench.providers import (
    Completion, anthropic_generate, custom_generate, make_generate, ollama_generate, openai_generate,
)

MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls, self.trust_env = payload, [], True

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResp(self.payload)


def test_ollama_sets_num_ctx_and_reads_counts():
    s = FakeSession({"message": {"content": "out"}, "prompt_eval_count": 11, "eval_count": 7, "done_reason": "stop"})
    c = ollama_generate(MSGS, model="m", num_ctx=8192, session=s)
    url, kw = s.calls[0]
    assert url.endswith("/api/chat")
    assert kw["json"]["options"] == {"num_ctx": 8192, "temperature": 0}
    assert (c.text, c.usage["input_tokens"], c.usage["output_tokens"]) == ("out", 11, 7)
    assert s.trust_env is False


def test_openai_usage():
    s = FakeSession({"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    c = openai_generate(MSGS, model="m", base_url="http://h/v1", session=s)
    assert c.usage == {"input_tokens": 3, "output_tokens": 2}


def test_anthropic_splits_system_and_reads_usage():
    captured = {}
    usage = types.SimpleNamespace(input_tokens=5, output_tokens=6,
                                  cache_read_input_tokens=None, cache_creation_input_tokens=1)
    msg = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="tsv")],
                                usage=usage, stop_reason="end_turn")

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return msg

    class Messages:
        def stream(self, **kw):
            captured.update(kw)
            return Stream()

    client = types.SimpleNamespace(messages=Messages())
    c = anthropic_generate(MSGS, model="claude-sonnet-5", client=client)
    assert captured["system"] == "sys" and captured["messages"] == [MSGS[1]]
    assert "temperature" not in captured
    assert c.usage == {"input_tokens": 5, "output_tokens": 6,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1}


def test_custom_accepts_str_or_tuple(tmp_path, monkeypatch):
    (tmp_path / "myprov.py").write_text(
        "def plain(messages):\n    return 'a'\n"
        "def rich(messages, **kw):\n    return 'b', {'input_tokens': 1}\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert custom_generate(MSGS, callable="myprov:plain", max_output_tokens=10).text == "a"
    assert custom_generate(MSGS, callable="myprov:rich").usage == {"input_tokens": 1}


def test_make_generate_rejects_skills_provider():
    with pytest.raises(ValueError):
        make_generate(ModelSpec(id="x", provider="claude-code", model="m", arm="skills"))


def test_completion_is_a_dataclass():
    assert Completion("t", {}).stop_reason == ""


def test_output_budget_reaches_every_provider():
    s = FakeSession({"message": {"content": "x"}, "prompt_eval_count": 1, "eval_count": 1})
    ollama_generate(MSGS, model="m", num_ctx=8192, max_output_tokens=4096, session=s)
    assert s.calls[0][1]["json"]["options"]["num_predict"] == 4096
    o = FakeSession({"choices": [{"message": {"content": "x"}}], "usage": {}})
    openai_generate(MSGS, model="m", base_url="http://h/v1", max_output_tokens=777, session=o)
    assert o.calls[0][1]["json"]["max_tokens"] == 777

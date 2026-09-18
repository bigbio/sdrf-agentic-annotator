import json
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


def _fake_claude(tmp_path, payload: dict, record=None, segments=None):
    """A stand-in `claude` that streams assistant text segments then one result event."""
    fake = tmp_path / "claude"
    rec = record or (tmp_path / "argv.json")
    segments = segments if segments is not None else ([payload["result"]] if payload.get("result") else [])
    events = [{"type": "assistant", "message": {"content": [{"type": "text", "text": seg}]}} for seg in segments]
    events.append(payload)
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'max': os.environ.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS')}}, open({str(rec)!r}, 'w'))\n"
        f"for e in {events!r}:\n    print(json.dumps(e))\n")
    fake.chmod(0o755)
    return fake, rec


def test_claude_cli_success(tmp_path):
    from sdrf_model_bench.providers import claude_cli_generate

    fake, rec = _fake_claude(tmp_path, {"type": "result", "subtype": "success", "is_error": False,
                                        "result": "```tsv\nx\n```", "total_cost_usd": 0.02,
                                        "usage": {"input_tokens": 10, "output_tokens": 5,
                                                  "cache_read_input_tokens": 3}})
    c = claude_cli_generate(MSGS, model="claude-haiku-4-5", max_output_tokens=4096, claude_bin=str(fake))
    assert c.text.startswith("```tsv") and c.cost_usd == 0.02 and c.usage["cache_read_input_tokens"] == 3
    call = json.loads(rec.read_text())
    argv = call["argv"]
    assert call["max"] == "4096"
    assert argv[argv.index("--system-prompt") + 1] == "sys"
    assert argv[argv.index("--tools") + 1] == "" and "--restricted" in argv and "--disable-slash-commands" in argv


def test_claude_cli_flattens_repair_history(tmp_path):
    from sdrf_model_bench.providers import claude_cli_generate

    fake, rec = _fake_claude(tmp_path, {"type": "result", "is_error": False, "result": "ok", "usage": {}})
    history = MSGS + [{"role": "assistant", "content": "draft"}, {"role": "user", "content": "fix it"}]
    claude_cli_generate(history, model="m", claude_bin=str(fake))
    prompt = json.loads(rec.read_text())["argv"][1]
    assert prompt.index("hi") < prompt.index("draft") < prompt.index("fix it")


def test_claude_cli_output_cap_is_a_truncation_not_a_crash(tmp_path):
    from sdrf_model_bench.providers import claude_cli_generate

    fake, _ = _fake_claude(tmp_path, {"type": "result", "is_error": True, "api_error_status": None,
                                      "result": "API Error: Claude's response exceeded the 60 output token maximum.",
                                      "usage": {"output_tokens": 60}}, segments=[])
    c = claude_cli_generate(MSGS, model="m", claude_bin=str(fake))
    assert c.text == "" and c.stop_reason == "length"


def test_claude_cli_rate_limit_raises_for_retry(tmp_path):
    from sdrf_model_bench.providers import ClaudeCliError, claude_cli_generate

    fake, _ = _fake_claude(tmp_path, {"type": "result", "is_error": True, "api_error_status": 429,
                                      "result": "rate limited", "usage": {}})
    with pytest.raises(ClaudeCliError):
        claude_cli_generate(MSGS, model="m", claude_bin=str(fake))


def test_ollama_thinking_off_by_default_and_budget_split():
    s = FakeSession({"message": {"content": "x"}, "prompt_eval_count": 1, "eval_count": 1})
    ollama_generate(MSGS, model="m", num_ctx=8192, max_output_tokens=4096, thinking_tokens=16384, session=s)
    body = s.calls[0][1]["json"]
    assert body["think"] is False and body["options"]["num_predict"] == 4096
    s2 = FakeSession({"message": {"content": "x", "thinking": "hmm"}, "prompt_eval_count": 1, "eval_count": 1})
    ollama_generate(MSGS, model="m", num_ctx=8192, think=True, max_output_tokens=4096, thinking_tokens=16384, session=s2)
    body = s2.calls[0][1]["json"]
    assert body["think"] is True and body["options"]["num_predict"] == 4096 + 16384


def test_claude_cli_cap_includes_thinking_allowance(tmp_path):
    from sdrf_model_bench.providers import claude_cli_generate

    fake, rec = _fake_claude(tmp_path, {"type": "result", "is_error": False, "result": "ok", "usage": {}})
    claude_cli_generate(MSGS, model="m", max_output_tokens=4096, thinking_tokens=16384, claude_bin=str(fake))
    assert json.loads(rec.read_text())["max"] == str(4096 + 16384)


def test_claude_cli_joins_auto_continued_segments(tmp_path):
    from sdrf_model_bench.providers import claude_cli_generate

    fake, _ = _fake_claude(tmp_path, {"type": "result", "is_error": False, "result": "\tb\n```",
                                      "usage": {"output_tokens": 50}},
                           segments=["```tsv\nsource name\tcomment[data file]\ns1", "\tb\n```"])
    c = claude_cli_generate(MSGS, model="m", max_output_tokens=4096, claude_bin=str(fake))
    assert c.text == "```tsv\nsource name\tcomment[data file]\ns1\tb\n```"


def test_claude_cli_over_budget_is_marked_length(tmp_path):
    from sdrf_model_bench.providers import claude_cli_generate

    fake, _ = _fake_claude(tmp_path, {"type": "result", "is_error": False, "result": "x",
                                      "usage": {"output_tokens": 50000}})
    c = claude_cli_generate(MSGS, model="m", max_output_tokens=4096, thinking_tokens=16384, claude_bin=str(fake))
    assert c.stop_reason == "length"

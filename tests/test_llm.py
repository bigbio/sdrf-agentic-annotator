from unittest.mock import MagicMock

from sdrf_agentic_annotator.llm import (
    get_generate,
    messages_to_query,
    openai_generate,
    pride_llm_generate,
)

MESSAGES = [
    {"role": "system", "content": "You are an SDRF annotator."},
    {"role": "user", "content": "Annotate PXD000001."},
]


def _fake_session(json_body):
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    session = MagicMock()
    session.post.return_value = resp
    return session, resp


def test_messages_to_query_flattens_roles_in_order():
    q = messages_to_query(MESSAGES)
    assert q == "[SYSTEM]\nYou are an SDRF annotator.\n\n[USER]\nAnnotate PXD000001."


def test_messages_to_query_skips_empty():
    assert messages_to_query([{"role": "user", "content": "  "}, {"role": "user", "content": "hi"}]) == "[USER]\nhi"


def test_pride_llm_generate_sends_query_and_returns_response():
    session, resp = _fake_session({"response": "source name\tcharacteristics[organism]\n"})
    out = pride_llm_generate(MESSAGES, session=session)
    assert out == "source name\tcharacteristics[organism]"
    # our messages are sent as `query`, and the service system prompt is disabled
    payload = session.post.call_args.kwargs["json"]
    assert payload["use_system_prompt"] is False
    assert "[SYSTEM]" in payload["query"] and "Annotate PXD000001." in payload["query"]


def test_pride_llm_generate_handles_missing_response():
    session, _ = _fake_session({"response": None})
    assert pride_llm_generate(MESSAGES, session=session) == ""


def test_openai_generate_reads_choices():
    session, _ = _fake_session({"choices": [{"message": {"content": "ok"}}]})
    out = openai_generate(MESSAGES, base_url="http://vllm:8000/v1", model="qwen", session=session)
    assert out == "ok"
    assert session.post.call_args.args[0] == "http://vllm:8000/v1/chat/completions"


def test_get_generate_factory():
    assert callable(get_generate("pride-internal"))
    assert callable(get_generate("openai", base_url="http://x/v1", model="m"))
    try:
        get_generate("nope")
    except ValueError as e:
        assert "unknown LLM provider" in str(e)
    else:
        raise AssertionError("expected ValueError")

"""`generate(messages) -> Completion` for every supported raw-arm provider.

Messages are OpenAI-style `[{"role": "system"|"user"|"assistant", "content": str}]`.
Every provider reports usage with the same keys so cost and token plots line up.
"""

from __future__ import annotations

import importlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from sdrf_model_bench.config import ModelSpec


@dataclass
class Completion:
    text: str
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    wall_s: float = 0.0


Generate = Callable[[list[dict]], Completion]


def _session(session=None):
    sess = session or requests.Session()
    sess.trust_env = False  # never route local/API traffic through an inherited proxy
    return sess


def anthropic_generate(messages, *, model: str, max_tokens: int = 64000, client=None, **_opts) -> Completion:
    """Claude via the official SDK. No temperature (rejected by Opus 5 / Sonnet 5) and no
    server-side fallbacks (a fallback would mix models inside one benchmark run)."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic(max_retries=4)
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": chat}
    if system:
        kwargs["system"] = system
    t0 = time.monotonic()
    with client.messages.stream(**kwargs) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    u = msg.usage
    usage = {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
    }
    return Completion(text, usage, msg.stop_reason or "", time.monotonic() - t0)


def ollama_generate(messages, *, model: str, num_ctx: int, host: str = "http://localhost:11434",
                    timeout: int = 3600, session=None, **_opts) -> Completion:
    """Local Ollama. `num_ctx` is mandatory: Ollama's default window silently truncates prompts."""
    payload = {"model": model, "messages": list(messages), "stream": False,
               "options": {"num_ctx": int(num_ctx), "temperature": 0}}
    t0 = time.monotonic()
    resp = _session(session).post(host.rstrip("/") + "/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    d = resp.json()
    usage = {"input_tokens": d.get("prompt_eval_count", 0), "output_tokens": d.get("eval_count", 0)}
    return Completion(d["message"]["content"] or "", usage, d.get("done_reason", ""), time.monotonic() - t0)


def openai_generate(messages, *, model: str, base_url: str, api_key_env: str = "OPENAI_API_KEY",
                    timeout: int = 1800, session=None, **_opts) -> Completion:
    """Any OpenAI-compatible /chat/completions endpoint (vLLM, LiteLLM, hosted APIs)."""
    key = os.environ.get(api_key_env, "not-needed")
    t0 = time.monotonic()
    resp = _session(session).post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": list(messages)},
        timeout=timeout,
    )
    resp.raise_for_status()
    d = resp.json()
    choice = d["choices"][0]
    u = d.get("usage") or {}
    usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
    return Completion(choice["message"]["content"] or "", usage, choice.get("finish_reason") or "",
                      time.monotonic() - t0)


def custom_generate(messages, *, callable: str, **opts) -> Completion:
    """Collaborator hook: `module:function(messages, **options) -> str | (str, usage_dict)`."""
    module, name = callable.split(":", 1)
    fn = getattr(importlib.import_module(module), name)
    t0 = time.monotonic()
    out = fn(list(messages), **opts)
    text, usage = (out, {}) if isinstance(out, str) else (out[0], dict(out[1] or {}))
    return Completion(text, usage, "", time.monotonic() - t0)


def make_generate(spec: ModelSpec) -> Generate:
    opts = dict(spec.options)
    if spec.provider == "anthropic":
        return lambda m: anthropic_generate(m, model=spec.model, **opts)
    if spec.provider == "ollama":
        return lambda m: ollama_generate(m, model=spec.model, **opts)
    if spec.provider == "openai":
        return lambda m: openai_generate(m, model=spec.model, **opts)
    if spec.provider == "custom":
        return lambda m: custom_generate(m, **opts)
    raise ValueError(f"{spec.id}: provider {spec.provider!r} has no raw-arm generate()")

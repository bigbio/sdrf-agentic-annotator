"""LLM providers for the harness.

Everything downstream is model-agnostic: it takes a ``generate(messages) -> text``
callable (see :mod:`draft` / :mod:`pipeline`). This module supplies ready-made
``generate`` callables for the concrete backends so the core never depends on any
particular HTTP client, and a run can pick a provider by name.

Providers:
  * ``pride-internal`` — the EBI-internal PRIDE LLM service (no external tokens).
  * ``openai`` — any OpenAI-compatible ``/chat/completions`` endpoint (e.g. a vLLM
    server hosting Qwen), selected via ``base_url`` / ``model``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import requests

Message = dict[str, str]
Generate = Callable[[Sequence[Message]], str]

# EBI-internal PRIDE LLM service. Reachable without a proxy (curl --noproxy '*').
PRIDE_LLM_URL = (
    "http://hh-rke-wp-webadmin-44-worker-2.caas.ebi.ac.uk:32269"
    "/pride/ws/archive/pride-llm-api/v1/llm/query-smart"
)


def messages_to_query(messages: Sequence[Message]) -> str:
    """Flatten chat ``[{role, content}]`` messages into a single prompt string.

    The PRIDE service takes one ``query`` string rather than a messages list, so
    each message is emitted under a ``[ROLE]`` header in order. Empty messages are
    skipped.
    """
    parts = []
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = (m.get("role") or "user").strip().upper()
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


def _no_proxy_session() -> requests.Session:
    """A session that ignores environment proxies (equivalent to ``--noproxy '*'``)."""
    session = requests.Session()
    session.trust_env = False
    return session


def pride_llm_generate(
    messages: Sequence[Message],
    *,
    url: str = PRIDE_LLM_URL,
    timeout: float = 180,
    redact_pii: bool = False,
    use_tools: bool = False,
    session: requests.Session | None = None,
) -> str:
    """``generate(messages) -> text`` backed by the internal PRIDE LLM service.

    Our system+user messages already carry every instruction, so the service's own
    system prompt is disabled (``use_system_prompt=False``) and the flattened
    messages are sent as ``query``. Returns the model's ``response`` text.
    """
    payload = {
        "query": messages_to_query(messages),
        "redact_pii": redact_pii,
        "use_tools": use_tools,
        "use_system_prompt": False,
    }
    sess = session or _no_proxy_session()
    resp = sess.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return (resp.json().get("response") or "").strip()


def openai_generate(
    messages: Sequence[Message],
    *,
    base_url: str,
    model: str,
    api_key: str = "not-needed",
    timeout: float = 180,
    temperature: float = 0.0,
    session: requests.Session | None = None,
) -> str:
    """``generate(messages) -> text`` for any OpenAI-compatible ``/chat/completions``
    endpoint (e.g. a local vLLM server hosting Qwen)."""
    sess = session or _no_proxy_session()
    resp = sess.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": list(messages), "temperature": temperature},
        timeout=timeout,
    )
    resp.raise_for_status()
    return (resp.json()["choices"][0]["message"]["content"] or "").strip()


def get_generate(provider: str, **kwargs) -> Generate:
    """Return a ``generate(messages) -> text`` callable for a named provider.

    ``pride-internal`` -> :func:`pride_llm_generate`; ``openai`` ->
    :func:`openai_generate` (requires ``base_url`` and ``model``). Extra kwargs are
    bound to the chosen provider.
    """
    if provider == "pride-internal":
        return lambda messages: pride_llm_generate(messages, **kwargs)
    if provider == "openai":
        return lambda messages: openai_generate(messages, **kwargs)
    raise ValueError(f"unknown LLM provider {provider!r} (available: 'pride-internal', 'openai')")

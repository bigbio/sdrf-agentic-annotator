"""`generate(messages) -> Completion` for every supported raw-arm provider.

Messages are OpenAI-style `[{"role": "system"|"user"|"assistant", "content": str}]`.
Every provider reports usage with the same keys so cost and token plots line up.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import requests

from sdrf_model_bench.config import ModelSpec


@dataclass
class Completion:
    text: str
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    wall_s: float = 0.0
    cost_usd: float | None = None  # set when the provider reports it (Claude Code: API-equivalent)


Generate = Callable[..., Completion]  # generate(messages, max_output_tokens=None) -> Completion


def _session(session=None):
    sess = session or requests.Session()
    sess.trust_env = False  # never route local/API traffic through an inherited proxy
    return sess


def anthropic_generate(messages, *, model: str, max_output_tokens: int = 64000, thinking_tokens: int = 0,
                       client=None, **_opts) -> Completion:
    """Claude via the official SDK. No temperature (rejected by Opus 5 / Sonnet 5) and no
    server-side fallbacks (a fallback would mix models inside one benchmark run)."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic(max_retries=4)
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    # max_tokens covers thinking too, so the thinking allowance is added on top of the answer budget
    kwargs = {"model": model, "max_tokens": max_output_tokens + thinking_tokens, "messages": chat}
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


def ollama_generate(messages, *, model: str, num_ctx: int, max_output_tokens: int | None = None,
                    think: bool = False, thinking_tokens: int = 0, host: str = "http://localhost:11434",
                    timeout: int = 3600, session=None, **_opts) -> Completion:
    """Local Ollama. `num_ctx` is mandatory: Ollama's default window silently truncates prompts.
    `max_output_tokens` becomes `num_predict`; without it a looping model generates until the
    context is full. Thinking is off unless `think: true`: a thinking model otherwise spends the
    answer budget on hidden reasoning (and local thinking is slow); when on, it gets the same
    thinking allowance as Claude."""
    options = {"num_ctx": int(num_ctx), "temperature": 0}
    if max_output_tokens:
        options["num_predict"] = int(max_output_tokens) + (int(thinking_tokens) if think else 0)
    payload = {"model": model, "messages": list(messages), "stream": False, "think": bool(think),
               "options": options}
    t0 = time.monotonic()
    resp = _session(session).post(host.rstrip("/") + "/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    d = resp.json()
    usage = {"input_tokens": d.get("prompt_eval_count", 0), "output_tokens": d.get("eval_count", 0)}
    return Completion(d["message"]["content"] or "", usage, d.get("done_reason", ""), time.monotonic() - t0)


def openai_generate(messages, *, model: str, base_url: str, api_key_env: str = "OPENAI_API_KEY",
                    max_output_tokens: int | None = None, thinking_tokens: int = 0, timeout: int = 1800,
                    session=None, **_opts) -> Completion:
    """Any OpenAI-compatible /chat/completions endpoint (vLLM, LiteLLM, hosted APIs)."""
    key = os.environ.get(api_key_env, "not-needed")
    body = {"model": model, "messages": list(messages)}
    if max_output_tokens:
        body["max_tokens"] = int(max_output_tokens) + int(thinking_tokens)  # reasoning models count it here
    t0 = time.monotonic()
    resp = _session(session).post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    d = resp.json()
    choice = d["choices"][0]
    u = d.get("usage") or {}
    usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
    return Completion(choice["message"]["content"] or "", usage, choice.get("finish_reason") or "",
                      time.monotonic() - t0)


class ClaudeCliError(RuntimeError):
    """Rate limit, auth or API failure from the Claude Code CLI: retried, never scored."""


def find_claude(explicit: str | None = None) -> str:
    for cand in (explicit, shutil.which("claude"), str(Path.home() / ".local/bin/claude")):
        if cand and Path(cand).exists():
            return cand
    return "claude"


def _flatten(chat: list[dict]) -> str:
    """One prompt for `claude -p`: a single user turn as-is, a repair history as a labelled transcript."""
    if len(chat) == 1:
        return chat[0]["content"]
    return "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in chat)


def claude_cli_generate(messages, *, model: str, max_output_tokens: int | None = None, thinking_tokens: int = 0,
                        claude_bin: str | None = None, timeout: int = 3600, **_opts) -> Completion:
    """Claude through the Claude Code CLI with the user's own login (no API key): our system prompt
    replaces Claude Code's, no tools, no skills, no settings or MCP. Claude Code still adds ~2k input
    tokens of harness context per call, which the usage figures include."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    cmd = [find_claude(claude_bin), "-p", _flatten(chat), "--restricted", "--tools", "",
           "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence",
           "--model", model, "--output-format", "stream-json", "--verbose"]
    if system:
        cmd += ["--system-prompt", system]
    env = dict(os.environ)
    if max_output_tokens:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(int(max_output_tokens) + int(thinking_tokens))
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sdrf-bench-cli-") as cwd:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    # Claude Code auto-continues a reply that hits the output cap and its final `result` holds only
    # the last segment, so the answer is rebuilt from every streamed assistant text block.
    segments, d = [], None
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            segments += [b.get("text", "") for b in ev.get("message", {}).get("content", []) if b.get("type") == "text"]
        elif ev.get("type") == "result":
            d = ev
    if d is None:
        raise ClaudeCliError(f"no result from claude (exit {proc.returncode}): {proc.stderr[-300:]}")
    u = d.get("usage") or {}
    usage = {k: u.get(k, 0) or 0 for k in
             ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    text, stop = "".join(segments), d.get("stop_reason") or d.get("subtype") or ""
    if d.get("is_error"):
        if d.get("api_error_status") is None and "output token maximum" in (d.get("result") or ""):
            stop = "length"  # hit the output budget: keep whatever was written, score it as is
        else:
            raise ClaudeCliError(f"claude error (status {d.get('api_error_status')}): {(d.get('result') or '')[:300]}")
    cap = (max_output_tokens or 0) + int(thinking_tokens)
    if max_output_tokens and usage["output_tokens"] > cap:
        stop = "length"  # continued past the budget; the budget is recorded as exceeded
    return Completion(text, usage, stop, time.monotonic() - t0, cost_usd=d.get("total_cost_usd"))


def custom_generate(messages, *, callable: str, **opts) -> Completion:
    """Collaborator hook: `module:function(messages, **options) -> str | (str, usage_dict)`."""
    module, name = callable.split(":", 1)
    fn = getattr(importlib.import_module(module), name)
    params = inspect.signature(fn).parameters
    if not any(p.kind is p.VAR_KEYWORD for p in params.values()):
        opts = {k: v for k, v in opts.items() if k in params}  # e.g. drop max_output_tokens if unsupported
    t0 = time.monotonic()
    out = fn(list(messages), **opts)
    text, usage = (out, {}) if isinstance(out, str) else (out[0], dict(out[1] or {}))
    return Completion(text, usage, "", time.monotonic() - t0)


def make_generate(spec: ModelSpec) -> Generate:
    opts = dict(spec.options)
    if spec.provider == "anthropic":
        return lambda m, **kw: anthropic_generate(m, model=spec.model, **opts, **kw)
    if spec.provider == "ollama":
        return lambda m, **kw: ollama_generate(m, model=spec.model, **opts, **kw)
    if spec.provider == "openai":
        return lambda m, **kw: openai_generate(m, model=spec.model, **opts, **kw)
    if spec.provider == "claude-cli":
        return lambda m, **kw: claude_cli_generate(m, model=spec.model, **opts, **kw)
    if spec.provider == "custom":
        return lambda m, **kw: custom_generate(m, **opts, **kw)
    raise ValueError(f"{spec.id}: provider {spec.provider!r} has no raw-arm generate()")

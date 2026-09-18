"""Skills arm: Claude Code headless with only the sdrf-skills plugin, offline, sandboxed to a workspace.

Isolation, from strongest to weakest:
  * --bare: no user hooks, CLAUDE.md, other plugins, memory; --strict-mcp-config: no MCP servers.
  * a sanitised plugin copy: no bundled annotations/examples, audited for benchmark accessions.
  * permissions: web tools and subagents denied; Read denied under the home directory, where the
    curated datasets live; Bash only for `parse_sdrf validate-sdrf`.
  * post-hoc audit: any file tool touching a path outside the workspace flags the run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

KEEP = ["skills", "spec/sdrf-proteomics", "criteria", "scripts", "tools",
        "data/cell_line_manifest.tsv", ".claude-plugin/plugin.json"]
EVIDENCE_FILES = ["pride.json", "files.json"]
ACCESSION_RE = re.compile(r"\b(?:PXD|MSV|IPX|MTBLS)\d{3,}\b")
PATH_KEYS = ("file_path", "path", "notebook_path")
ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "TodoWrite",
           "Bash(parse_sdrf validate-sdrf:*)"]
DENIED = ["WebFetch", "WebSearch", "Agent", "Task", "Read(~/**)", "Glob(~/**)", "Grep(~/**)"]

PROMPT = """Create an SDRF-Proteomics file for the proteomics dataset {accession}.

Everything you may use is in ./evidence/: {listing}. There is no network access, so do not try to
fetch anything. Follow the SDRF skills (start with the sdrf-annotate skill). Validate with:
  parse_sdrf validate-sdrf -s ./output.sdrf.tsv --use_ols_cache_only{templates}
Write the final SDRF to ./output.sdrf.tsv. Do not ask questions: make your best judgement and finish."""


class LeakError(RuntimeError):
    pass


def build_sanitized_plugin(src: Path, dest: Path, forbidden) -> Path:
    src, dest = Path(src), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for rel in KEEP:
        s = src / rel
        if s.is_dir():
            shutil.copytree(s, dest / rel, ignore=shutil.ignore_patterns("*.sdrf.tsv", "__pycache__"))
        elif s.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, dest / rel)
    manifest = dest / ".claude-plugin" / "plugin.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        data.pop("hooks", None)
        manifest.write_text(json.dumps(data, indent=2))
    hits = []
    needles = [a for a in forbidden if a]
    for f in dest.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="ignore")
            hits += [f"{a} in {f.relative_to(dest)}" for a in needles if a in text]
    if hits:
        raise LeakError("benchmark accessions found in plugin copy: " + "; ".join(hits[:10]))
    return dest


def mentioned_accessions(plugin_dir: Path) -> set[str]:
    """Accessions the skills cite as examples; selection excludes them so no worked answer ships."""
    found: set[str] = set()
    for f in Path(plugin_dir).rglob("*"):
        if f.is_file():
            found |= set(ACCESSION_RE.findall(f.read_text(errors="ignore")))
    return found


def prepare_workspace(ws: Path, ev_dir: Path, manuscript: bool) -> list[str]:
    target = Path(ws) / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    names = EVIDENCE_FILES + (["manuscript.txt"] if manuscript else [])
    copied = []
    for n in names:
        if (Path(ev_dir) / n).exists():
            shutil.copy2(Path(ev_dir) / n, target / n)
            copied.append(n)
    return copied


def build_command(claude_bin: str, model: str, plugin_dir: Path, prompt: str) -> list[str]:
    return [
        claude_bin, "-p", prompt,
        "--bare", "--plugin-dir", str(plugin_dir), "--strict-mcp-config",
        "--model", model, "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--permission-mode", "dontAsk",
        "--allowedTools", *ALLOWED,
        "--disallowedTools", *DENIED,
    ]


def _outside(path: str, workspace: str) -> bool:
    return os.path.isabs(path) and not os.path.realpath(path).startswith(os.path.realpath(workspace))


def parse_stream(lines, workspace: str) -> dict:
    out = {"usage": {}, "cost_usd": None, "num_turns": 0, "is_error": True, "tool_calls": [], "leak_suspect": False}
    for line in lines:
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") != "tool_use":
                    continue
                inp = block.get("input") or {}
                out["tool_calls"].append({"name": block.get("name"), "input": inp})
                if any(_outside(str(inp.get(k, "")), workspace) for k in PATH_KEYS):
                    out["leak_suspect"] = True
        elif ev.get("type") == "result":
            u = ev.get("usage") or {}
            out["usage"] = {k: u.get(k, 0) or 0 for k in (
                "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
            out["cost_usd"] = ev.get("total_cost_usd")
            out["num_turns"] = ev.get("num_turns", 0)
            out["is_error"] = bool(ev.get("is_error"))
    return out


def run_skills(model: str, ev_dir: Path, accession: str, manuscript: bool, templates, run_dir: Path,
               plugin_dir: Path, claude_bin: str = "claude", timeout: int = 2700) -> dict:
    ws = Path(run_dir) / "workspace"
    if str(ws.resolve()).startswith(str(Path.home().resolve())):
        raise RuntimeError(f"skills workspace {ws} is under $HOME, which the agent cannot read; "
                           "set --outputs to a path outside the home directory")
    copied = prepare_workspace(ws, ev_dir, manuscript)
    local_plugin = ws / ".plugin"
    shutil.copytree(plugin_dir, local_plugin, dirs_exist_ok=True)
    tmpl = "".join(f" -t {t}" for t in templates)
    prompt = PROMPT.format(accession=accession, listing=", ".join(copied), templates=tmpl)
    cmd = build_command(claude_bin, model, local_plugin, prompt)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        stdout, returncode = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, returncode = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), -1
    (Path(run_dir) / "transcript.jsonl").write_text(stdout)
    parsed = parse_stream(stdout.splitlines(), str(ws))
    out_file = ws / "output.sdrf.tsv"
    return {
        **parsed,
        "sdrf": out_file.read_text() if out_file.exists() else None,
        "wall_s": time.monotonic() - t0,
        "returncode": returncode,
    }

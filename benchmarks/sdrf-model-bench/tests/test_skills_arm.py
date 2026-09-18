import json

import pytest

from sdrf_model_bench.skills_arm import (
    LeakError, build_command, build_sanitized_plugin, mentioned_accessions, parse_stream, prepare_workspace,
)


def fake_plugin(root, leak=False):
    (root / "skills" / "sdrf-annotate").mkdir(parents=True)
    (root / "skills" / "sdrf-annotate" / "SKILL.md").write_text("annotate " + ("PXD000001" if leak else ""))
    (root / "spec" / "sdrf-proteomics").mkdir(parents=True)
    (root / "spec" / "sdrf-proteomics" / "TERMS.tsv").write_text("t")
    (root / "annotations").mkdir()
    (root / "annotations" / "PXD000001.sdrf.tsv").write_text("truth!")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "sdrf-skills", "hooks": "./h.json"}))
    return root


def test_sanitized_plugin_drops_data_and_hooks(tmp_path):
    src = fake_plugin(tmp_path / "src")
    dest = build_sanitized_plugin(src, tmp_path / "clean", forbidden=["PXD000001"])
    assert (dest / "skills" / "sdrf-annotate" / "SKILL.md").exists()
    assert not (dest / "annotations").exists()
    assert "hooks" not in json.loads((dest / ".claude-plugin" / "plugin.json").read_text())


def test_leak_audit_raises(tmp_path):
    src = fake_plugin(tmp_path / "src", leak=True)
    with pytest.raises(LeakError, match="PXD000001"):
        build_sanitized_plugin(src, tmp_path / "clean", forbidden=["PXD000001"])


def test_mentioned_accessions(tmp_path):
    src = fake_plugin(tmp_path / "src", leak=True)
    assert mentioned_accessions(src / "skills") == {"PXD000001"}


def test_workspace_respects_manuscript_flag(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    for n in ("pride.json", "files.json", "manuscript.txt", "meta.json"):
        (ev / n).write_text("{}")
    assert sorted(prepare_workspace(tmp_path / "w1", ev, manuscript=False)) == ["files.json", "pride.json"]
    assert "manuscript.txt" in prepare_workspace(tmp_path / "w2", ev, manuscript=True)


def test_command_is_locked_down(tmp_path):
    cmd = build_command("claude", "claude-opus-5", tmp_path / "p", "do it")
    joined = " ".join(cmd)
    for flag in ("--bare", "--strict-mcp-config", "--plugin-dir", "--no-session-persistence"):
        assert flag in cmd
    assert "WebFetch" in joined and "Read(~/**)" in joined and "Bash(parse_sdrf validate-sdrf:*)" in joined


def test_parse_stream_usage_and_leaks(tmp_path):
    ws = str(tmp_path)
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": f"{ws}/evidence/pride.json"}},
            {"type": "tool_use", "name": "Glob", "input": {"pattern": "**/*.tsv", "path": "/Users/x/data"}}]}}),
        "not json",
        json.dumps({"type": "result", "is_error": False, "num_turns": 7, "total_cost_usd": 0.42,
                    "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900,
                              "cache_creation_input_tokens": 10}}),
    ]
    out = parse_stream(lines, ws)
    assert out["cost_usd"] == 0.42 and out["num_turns"] == 7
    assert out["usage"]["cache_read_input_tokens"] == 900
    assert out["leak_suspect"] and len(out["tool_calls"]) == 2

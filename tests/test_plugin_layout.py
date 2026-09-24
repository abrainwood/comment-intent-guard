import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = _REPO_ROOT / "comment_intent_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("comment_intent_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module()
_PLUGIN_JSON = _REPO_ROOT / ".claude-plugin" / "plugin.json"
_MARKETPLACE_JSON = _REPO_ROOT / ".claude-plugin" / "marketplace.json"
_HOOKS_JSON = _REPO_ROOT / "hooks" / "hooks.json"
_SKILL_MD = _REPO_ROOT / "skills" / "self-documenting-code" / "SKILL.md"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter(text):
    match = _FRONTMATTER_RE.match(text)
    assert match, "expected a --- delimited frontmatter block"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_plugin_json_has_name_version_and_description():
    manifest = json.loads(_PLUGIN_JSON.read_text())

    assert manifest["name"] == "comment-intent-guard"
    assert _SEMVER_RE.match(manifest["version"])
    assert manifest["description"]


def test_marketplace_json_has_one_plugin_matching_the_plugin_manifest():
    plugin_manifest = json.loads(_PLUGIN_JSON.read_text())
    marketplace = json.loads(_MARKETPLACE_JSON.read_text())

    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["name"] == plugin_manifest["name"]
    assert entry["source"] == "./"


def test_hooks_json_wires_pretooluse_on_write_or_edit_via_plugin_root():
    hooks = json.loads(_HOOKS_JSON.read_text())

    entries = hooks["hooks"]["PreToolUse"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["matcher"] == "Write|Edit"

    commands = [step["command"] for step in entry["hooks"]]
    assert len(commands) == 1
    command = commands[0]
    assert "${CLAUDE_PLUGIN_ROOT}/comment_intent_guard.py" in command
    assert "/Users" not in command


def test_state_path_defaults_under_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("COMMENT_INTENT_GUARD_STATE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    path = guard._state_path()

    assert path == str(tmp_path / ".claude" / "comment-intent-guard" / "state.json")


def test_state_path_honours_the_env_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-state.json"
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(override))

    assert guard._state_path() == str(override)


def test_record_edit_creates_the_state_directory_when_missing(tmp_path):
    state_path = tmp_path / "nested" / "state.json"

    guard.record_edit(state_path, "session-a", comment_lines=1, code_lines=2)

    assert state_path.exists()


def test_e2e_write_denied_when_run_as_a_plugin_with_claude_plugin_root_set(tmp_path):
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/tests/test_thing.py",
            "content": 'def test_x():\n    """doc"""\n',
        },
    }
    env = dict(
        os.environ,
        CLAUDE_PLUGIN_ROOT=str(_REPO_ROOT),
        COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state.json"),
    )

    result = subprocess.run(
        [sys.executable, str(_MODULE_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_skill_md_frontmatter_has_a_name_and_a_non_empty_description():
    fields = _parse_frontmatter(_SKILL_MD.read_text())

    assert fields["name"] == "self-documenting-code"
    assert fields["description"]


def test_hooks_json_wires_sessionstart_on_startup_resume_and_compact():
    hooks = json.loads(_HOOKS_JSON.read_text())

    entries = hooks["hooks"]["SessionStart"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["matcher"] == "startup|resume|compact"

    commands = [step["command"] for step in entry["hooks"]]
    assert len(commands) == 1
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py" in commands[0]

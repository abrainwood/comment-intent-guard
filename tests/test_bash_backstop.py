import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "hooks" / "bash_backstop.py"


def _run(payload, env):
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_non_git_cwd_produces_no_output(tmp_path):
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_heredoc_written_test_docstring_is_reported_as_a_bright_line(tmp_path):
    _init_git_repo(tmp_path)
    _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PostToolUse"
    assert "bright line" in hook_output["additionalContext"].lower()
    assert "test_x" in hook_output["additionalContext"]


def _write(path, relpath, content):
    target = path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def test_git_repo_with_no_changes_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_same_session_second_call_with_no_new_mtime_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    first = _run(payload, env)
    second = _run(payload, env)

    assert json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]
    assert second.returncode == 0
    assert second.stdout == ""


def test_a_different_session_id_is_reported_again(tmp_path):
    _init_git_repo(tmp_path)
    _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    first = _run({"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}, env)
    second = _run({"session_id": "session-b", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}, env)

    assert json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]
    assert json.loads(second.stdout)["hookSpecificOutput"]["additionalContext"]


def test_more_than_200_candidates_warns_and_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    for n in range(201):
        _write(tmp_path, f"pkg/module_{n}.py", f"VALUE_{n} = {n}\n")
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""
    assert "200" in result.stderr


def test_malformed_json_input_does_not_crash_uncaught(tmp_path):
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input="{not json",
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "bash_backstop" in result.stderr

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "hooks" / "bash_backstop.py"


def _import_bash_backstop():
    spec = importlib.util.spec_from_file_location("bash_backstop", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    baseline = _run(payload, env)
    assert baseline.stdout == ""

    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)

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
    return target


def _touch_future(path, seconds=5):
    future = time.time() + seconds
    os.utime(path, (future, future))


def test_git_repo_with_no_changes_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""


def _seed_stamp(tmp_path, session_id, stamp):
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "bash_backstop_stamps.json").write_text(json.dumps({session_id: stamp}))
    return str(state_dir / "state.json")


def test_same_session_second_call_with_no_new_mtime_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    stamp = 1_700_000_000
    os.utime(target, (stamp - 10, stamp - 10))
    state_path = _seed_stamp(tmp_path, "session-a", stamp)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=state_path)

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_mtime_equal_to_the_stamp_is_reported(tmp_path):
    _init_git_repo(tmp_path)
    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    stamp = 1_700_000_000
    os.utime(target, (stamp, stamp))
    state_path = _seed_stamp(tmp_path, "session-a", stamp)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=state_path)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_a_different_session_id_is_reported_again(tmp_path):
    _init_git_repo(tmp_path)
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    payload_a = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    payload_b = {"session_id": "session-b", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    assert _run(payload_a, env).stdout == ""

    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)

    first = _run(payload_a, env)
    assert json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]

    baseline_b = _run(payload_b, env)
    assert baseline_b.stdout == ""
    _touch_future(target, seconds=10)

    second = _run(payload_b, env)
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


def test_first_call_for_a_new_session_establishes_baseline_and_reports_nothing(tmp_path):
    _init_git_repo(tmp_path)
    _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    first = _run(payload, env)

    assert first.returncode == 0
    assert first.stdout == ""




def test_deleted_tracked_file_does_not_block_reporting_other_violations(tmp_path):
    _init_git_repo(tmp_path)
    tracked = _write(tmp_path, "pkg/tracked.py", "VALUE = 1\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=tmp_path, check=True)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    tracked.unlink()
    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_non_ascii_filename_is_reported_as_a_bright_line(tmp_path):
    _init_git_repo(tmp_path)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    target = _write(tmp_path, "tests/tést_ü.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_repo_root_lookup_timeout_is_caught_and_warned(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(module.subprocess, "run", _raise_timeout)

    result = module._repo_root(str(tmp_path))

    assert result is None
    assert "timed out" in capsys.readouterr().err.lower()


def test_git_paths_timeout_is_caught_and_warned(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(module.subprocess, "run", _raise_timeout)

    result = module._git_paths(str(tmp_path), ["diff", "--name-only", "HEAD"])

    assert result == []
    assert "timed out" in capsys.readouterr().err.lower()


def test_post_tool_use_hook_entry_declares_a_ten_second_timeout():
    hooks_config = json.loads((_REPO_ROOT / "hooks" / "hooks.json").read_text())

    post_tool_use = hooks_config["hooks"]["PostToolUse"][0]["hooks"][0]

    assert post_tool_use["timeout"] == 10


def test_clean_line_appended_to_a_file_with_a_preexisting_advisory_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    tracked = _write(tmp_path, "pkg/tracked.py", "# fixed on 2026-05-22 after the incident\npass\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=tmp_path, check=True)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    with tracked.open("a") as handle:
        handle.write("VALUE = 1\n")
    _touch_future(tracked)

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_violating_line_appended_to_a_tracked_file_reports_only_the_new_finding(tmp_path):
    _init_git_repo(tmp_path)
    tracked = _write(tmp_path, "pkg/tracked.py", "# fixed on 2026-05-22 after the incident\npass\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=tmp_path, check=True)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    with tracked.open("a") as handle:
        handle.write("# updated on 2026-09-24 with a new fix\nVALUE = 1\n")
    _touch_future(tracked)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context.count("date, measurement, or SHA") == 1
    assert "2026-09-24" not in context  # the finding message doesn't echo the date itself
    assert "near line 3" in context

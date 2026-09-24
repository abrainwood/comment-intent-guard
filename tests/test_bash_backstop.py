import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

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


def test_51_sessions_evicts_the_oldest(tmp_path):
    _init_git_repo(tmp_path)
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    for n in range(51):
        payload = {"session_id": f"session-{n}", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
        assert _run(payload, env).stdout == ""

    stamps_path = tmp_path / "state" / "bash_backstop_stamps.json"
    stamps = json.loads(stamps_path.read_text())
    assert "session-0" not in stamps
    assert "session-50" in stamps
    assert len(stamps) == 50


def test_partial_write_to_the_stamps_file_does_not_break_the_next_run(tmp_path):
    _init_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    stamps_path = state_dir / "bash_backstop_stamps.json"
    stamps_path.write_text('{"session-a": 123, "sess')
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(state_dir / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""
    # A corrupt stamps file is recovered from, not left broken: the baseline
    # call rewrites it as valid JSON, and a later write is reported normally.
    assert json.loads(stamps_path.read_text()) == {"session-a": pytest.approx(time.time(), abs=30)}

    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)
    second = _run(payload, env)

    assert "test_x" in json.loads(second.stdout)["hookSpecificOutput"]["additionalContext"]


def test_build_message_caps_at_40_findings_with_a_more_findings_note():
    module = _import_bash_backstop()
    lines = [f"finding {n}" for n in range(45)]

    message = module._build_message(lines)

    assert message.count("finding ") == 40
    assert "... and 5 more findings" in message


def test_build_message_with_exactly_40_findings_has_no_more_findings_note():
    module = _import_bash_backstop()
    lines = [f"finding {n}" for n in range(40)]

    message = module._build_message(lines)

    assert message.count("finding ") == 40
    assert "more findings" not in message


def test_build_message_caps_by_byte_budget_even_under_40_findings():
    module = _import_bash_backstop()
    finding_byte_size = 500
    finding_count = 10
    lines = ["x" * finding_byte_size for _ in range(finding_count)]
    trailer_note_headroom = 64
    assert finding_byte_size * finding_count > module._MAX_MESSAGE_BYTES

    message = module._build_message(lines)

    assert len(message.encode("utf-8")) <= module._MAX_MESSAGE_BYTES + trailer_note_headroom
    assert "more findings" in message


def test_exactly_200_candidates_does_not_warn(tmp_path):
    _init_git_repo(tmp_path)
    for n in range(200):
        _write(tmp_path, f"pkg/module_{n}.py", f"VALUE_{n} = {n}\n")
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = _run(payload, env)

    assert result.returncode == 0
    assert result.stderr == ""


def test_modified_tracked_file_is_reported_as_a_bright_line(tmp_path):
    _init_git_repo(tmp_path)
    tracked = _write(tmp_path, "tests/test_thing.py", "def test_x():\n    pass\n")
    subprocess.run(["git", "add", "tests/test_thing.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked test"], cwd=tmp_path, check=True)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    tracked.write_text('def test_x():\n    """doc"""\n')
    _touch_future(tracked)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "bright line" in output["hookSpecificOutput"]["additionalContext"].lower()


def test_cwd_in_subdirectory_of_repo_still_finds_changes(tmp_path):
    _init_git_repo(tmp_path)
    subdir = tmp_path / "pkg" / "sub"
    subdir.mkdir(parents=True)
    payload = {"session_id": "session-a", "cwd": str(subdir), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_import_of_comment_intent_guard_works_when_launched_from_an_unrelated_cwd(tmp_path):
    _init_git_repo(tmp_path)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(tmp_path),  # a directory that does not contain comment_intent_guard.py
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_warning_uses_a_single_bash_backstop_prefix_not_comment_intent_guard(tmp_path):
    _init_git_repo(tmp_path)
    for n in range(201):
        _write(tmp_path, f"pkg/module_{n}.py", f"VALUE_{n} = {n}\n")
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    result = _run(payload, env)

    assert result.stderr.count(":") >= 1
    assert "bash_backstop:" in result.stderr
    assert "comment_intent_guard:" not in result.stderr


def test_advisory_only_file_appears_without_a_bright_line_tag(tmp_path):
    _init_git_repo(tmp_path)
    tracked = _write(tmp_path, "pkg/tracked.py", "pass\n")
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
    assert "date, measurement, or SHA" in context
    assert "BRIGHT LINE" not in context

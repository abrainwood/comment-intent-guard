import importlib.util
import io
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


def _write(path, relpath, content):
    target = path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


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


def _touch_future(path, seconds=5):
    future = time.time() + seconds
    os.utime(path, (future, future))


def test_second_call_on_a_clean_repo_produces_no_output(tmp_path):
    _init_git_repo(tmp_path)
    untracked = _write(tmp_path, "pkg/untracked.py", '"""fixes #91"""\nVALUE = 1\n')
    old = time.time() - 100
    os.utime(untracked, (old, old))
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    baseline = _run(payload, env)
    assert baseline.stdout == ""

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


def test_backstop_does_not_re_report_an_unchanged_file_on_the_next_call(tmp_path):
    _init_git_repo(tmp_path)
    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    pass\n')
    seed_stamp = 1_700_000_000
    state_path = _seed_stamp(tmp_path, "session-a", seed_stamp)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=state_path)
    edit_stamp = seed_stamp + 10
    target.write_text('def test_x():\n    """doc"""\n')
    os.utime(target, (edit_stamp, edit_stamp))

    second = _run(payload, env)
    assert "test_x" in json.loads(second.stdout)["hookSpecificOutput"]["additionalContext"]

    third = _run(payload, env)

    assert third.stdout == ""


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


def test_more_than_200_candidates_warns_with_a_single_bash_backstop_prefix(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setattr(module, "_repo_root", lambda cwd: str(tmp_path))
    fake_paths = [f"pkg/module_{n}.py" for n in range(module._MAX_CANDIDATES + 1)]
    monkeypatch.setattr(module, "_candidate_files", lambda repo_root: (fake_paths, {}))
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))

    module._run()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{len(fake_paths)} changed files exceeds the {module._MAX_CANDIDATES}-file cap" in captured.err
    assert "bash_backstop:" in captured.err
    assert "comment_intent_guard:" not in captured.err


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


def test_unquote_git_header_path_handles_mixed_raw_and_octal_escapes_from_quote_path_false(tmp_path):
    module = _import_bash_backstop()

    raw = '"b/a\\"☃.py"'

    assert module._unquote_git_header_path(raw) == 'b/a"☃.py'


def test_unquote_git_header_path_handles_a_fully_octal_quoted_path(tmp_path):
    module = _import_bash_backstop()

    raw = '"b/a\\"\\342\\230\\203.py"'

    assert module._unquote_git_header_path(raw) == 'b/a"☃.py'


def test_unquote_git_header_path_strips_only_a_trailing_tab_not_a_leading_one():
    module = _import_bash_backstop()

    raw = "\tb/a\tb.py\t"

    assert module._unquote_git_header_path(raw) == "\tb/a\tb.py"


def test_unquote_git_header_path_falls_back_to_the_raw_quoted_string_when_not_valid_utf8():
    module = _import_bash_backstop()
    raw = '"b/a\\377.py"'

    assert module._unquote_git_header_path(raw) == raw


def test_c_unquote_body_treats_a_trailing_lone_backslash_as_a_literal_character():
    module = _import_bash_backstop()

    assert module._c_unquote_body("a\\") == b"a\\"


def test_c_unquote_body_keeps_an_unrecognized_escape_as_backslash_and_char():
    module = _import_bash_backstop()

    assert module._c_unquote_body("a\\zb") == b"a\\zb"


def test_c_unquote_body_stops_an_octal_escape_at_three_digits():
    module = _import_bash_backstop()

    assert module._c_unquote_body("\\1234") == bytes([0o123]) + b"4"


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


def test_violating_line_appended_to_a_tracked_file_reports_the_new_finding_without_echoing_the_date(tmp_path):
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
    assert "2026-09-24" not in context
    assert "near line 3" in context


def test_51_sessions_evicts_the_oldest(tmp_path, monkeypatch, capsys):
    _init_git_repo(tmp_path)
    module = _import_bash_backstop()
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setattr(module, "_repo_root", lambda cwd: str(tmp_path))
    monkeypatch.setattr(module, "_candidate_files", lambda repo_root: ([], {}))

    session_count = module.guard.MAX_TRACKED_SESSIONS + 1
    for n in range(session_count):
        payload = {"session_id": f"session-{n}", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
        monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
        module._run()
        assert capsys.readouterr().out == ""

    stamps_path = tmp_path / "state" / "bash_backstop_stamps.json"
    stamps = json.loads(stamps_path.read_text())
    assert "session-0" not in stamps
    assert f"session-{session_count - 1}" in stamps
    assert len(stamps) == module.guard.MAX_TRACKED_SESSIONS


def test_partial_write_to_the_stamps_file_is_rewritten_as_valid_json_on_the_next_run(tmp_path):
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
    assert json.loads(stamps_path.read_text()) == {"session-a": pytest.approx(time.time(), abs=30)}

    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)
    second = _run(payload, env)

    assert "test_x" in json.loads(second.stdout)["hookSpecificOutput"]["additionalContext"]


def test_build_message_caps_at_40_findings_with_a_more_findings_note():
    module = _import_bash_backstop()
    over_the_cap = module._MAX_FINDINGS + 5
    lines = [f"finding {n}" for n in range(over_the_cap)]

    message = module._build_message(lines)

    assert message.count("finding ") == module._MAX_FINDINGS
    assert "... and 5 more findings" in message


def test_build_message_with_exactly_40_findings_has_no_more_findings_note():
    module = _import_bash_backstop()
    lines = [f"finding {n}" for n in range(module._MAX_FINDINGS)]

    message = module._build_message(lines)

    assert message.count("finding ") == module._MAX_FINDINGS
    assert "more findings" not in message


def test_build_message_byte_cap_reports_the_exact_omitted_count():
    module = _import_bash_backstop()
    finding_byte_size = 500
    finding_count = module._MAX_FINDINGS + 5
    lines = ["x" * finding_byte_size for _ in range(finding_count)]

    message = module._build_message(lines)

    kept = message.count("x" * finding_byte_size)
    assert message.endswith(f"... and {finding_count - kept} more findings")


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


def test_exactly_200_candidates_does_not_warn(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setattr(module, "_repo_root", lambda cwd: str(tmp_path))
    fake_paths = [f"pkg/module_{n}.py" for n in range(module._MAX_CANDIDATES)]
    monkeypatch.setattr(module, "_candidate_files", lambda repo_root: (fake_paths, {}))
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))

    module._run()

    assert capsys.readouterr().err == ""


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
        cwd=str(tmp_path),
    )

    assert result.returncode == 0
    assert result.stderr == ""


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


def _git_call_count_for_a_modified_candidate_scan(repo_dir, monkeypatch, file_count):
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    for n in range(file_count):
        _write(repo_dir, f"pkg/module_{n}.py", f"VALUE_{n} = {n}\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add modules"], cwd=repo_dir, check=True)
    module = _import_bash_backstop()
    payload = {"session_id": "session-a", "cwd": str(repo_dir), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(repo_dir / "state" / "state.json"))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    module._run()

    for n in range(file_count):
        target = repo_dir / "pkg" / f"module_{n}.py"
        target.write_text(f"VALUE_{n} = {n + 1}\n")
    for target in (repo_dir / "pkg").glob("*.py"):
        _touch_future(target)

    real_run = subprocess.run
    call_count = 0

    def _counting_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_run(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", _counting_run)
    monkeypatch.setattr(module.guard.subprocess, "run", _counting_run)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))

    module._run()

    return call_count


def test_git_call_count_stays_constant_regardless_of_candidate_count(tmp_path, monkeypatch):
    one_candidate = _git_call_count_for_a_modified_candidate_scan(tmp_path / "one", monkeypatch, file_count=1)
    fifty_candidates = _git_call_count_for_a_modified_candidate_scan(tmp_path / "fifty", monkeypatch, file_count=50)

    assert one_candidate == fifty_candidates


def test_backstop_reports_blocking_findings_from_an_unanalyzable_file(tmp_path, monkeypatch):
    _init_git_repo(tmp_path)
    target = _write(tmp_path, "pkg/tracked.py", "pass\n")
    module = _import_bash_backstop()
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    module._run()
    _touch_future(target)

    def _raise_unavailable(file_path, text):
        exc = module.guard.AnalysisUnavailable("could not analyze")
        exc.blocking = [("BLOCKED - unanalyzable file", (1, 1))]
        raise exc

    monkeypatch.setattr(module.guard, "_findings_for_file", _raise_unavailable)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    stdout = io.StringIO()
    monkeypatch.setattr(module.sys, "stdout", stdout)

    module._run()

    output = json.loads(stdout.getvalue())
    assert "BRIGHT LINE - BLOCKED - unanalyzable file" in output["hookSpecificOutput"]["additionalContext"]


def test_diff_against_missing_head_stays_silent(tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    module = _import_bash_backstop()

    result = module._tracked_diff_added_lines(str(tmp_path), set())

    assert result == {}
    assert capsys.readouterr().err == ""


def test_git_paths_failure_other_than_missing_head_is_warned(tmp_path, monkeypatch, capsys):
    _init_git_repo(tmp_path)
    module = _import_bash_backstop()

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="fatal: index file corrupt")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    result = module._git_paths(str(tmp_path), ["diff", "--name-only", "HEAD"])

    assert result == []
    assert "index file corrupt" in capsys.readouterr().err


def test_diff_failure_other_than_missing_head_is_warned(tmp_path, monkeypatch, capsys):
    _init_git_repo(tmp_path)
    module = _import_bash_backstop()

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="fatal: index file corrupt")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    result = module._tracked_diff_added_lines(str(tmp_path), set())

    assert result == {}
    assert "index file corrupt" in capsys.readouterr().err


def test_missing_session_id_still_tracks_a_baseline_stamp_and_stops_reporting_once_the_stamp_passes_the_mtime(
    tmp_path,
):
    _init_git_repo(tmp_path)
    payload = {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    target = _write(tmp_path, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_future(target)
    first = _run(payload, env)
    assert first.returncode == 0
    assert "test_x" in json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]

    stamps_path = tmp_path / "state" / "bash_backstop_stamps.json"
    stamps = json.loads(stamps_path.read_text())
    future_mtime = int(os.path.getmtime(target))
    stamps_path.write_text(json.dumps({key: future_mtime + 1 for key in stamps}))

    third = _run(payload, env)

    assert third.stdout == ""


def test_heredoc_written_yaml_with_an_issue_reference_is_reported_as_a_bright_line(tmp_path):
    _init_git_repo(tmp_path)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    baseline = _run(payload, env)
    assert baseline.stdout == ""

    target = _write(tmp_path, "config/thing.yaml", "# fixes #482 by capping retries\nkey: value\n")
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "BRIGHT LINE" in context
    assert "thing.yaml" in context


def test_tracked_file_with_a_space_in_its_name_is_reported(tmp_path):
    _init_git_repo(tmp_path)
    target = _write(tmp_path, "pkg/my file.py", "pass\n")
    subprocess.run(["git", "add", "pkg/my file.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add spaced file"], cwd=tmp_path, check=True)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    with target.open("a") as handle:
        handle.write("# updated on 2026-09-24 with a fix (issue #482)\nVALUE = 1\n")
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "my file.py" in context
    assert "BRIGHT LINE" in context


def test_added_line_starting_with_plus_plus_does_not_break_a_later_hunk(tmp_path):
    _init_git_repo(tmp_path)
    original = "\n".join(f"line_{n} = {n}" for n in range(1, 11)) + "\n"
    target = _write(tmp_path, "pkg/tracked.py", original)
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=tmp_path, check=True)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    assert _run(payload, env).stdout == ""

    lines = [f"line_{n} = {n}" for n in range(1, 11)]
    lines.insert(1, "++ this looks like a diff header but is not")
    lines.append("# updated on 2026-09-24 with a fix")
    target.write_text("\n".join(lines) + "\n")
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "tracked.py" in context
    assert "date, measurement, or SHA" in context


def test_candidate_missing_from_disk_warns_with_its_path(tmp_path, monkeypatch, capsys):
    _init_git_repo(tmp_path)
    target = _write(tmp_path, "pkg/gone.py", "pass\n")
    subprocess.run(["git", "add", "pkg/gone.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add gone"], cwd=tmp_path, check=True)
    with target.open("a") as handle:
        handle.write("VALUE = 1\n")
    _touch_future(target)
    module = _import_bash_backstop()
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    module._run()

    real_getmtime = module.os.path.getmtime

    def _raise_for_gone(path):
        if path.endswith("gone.py"):
            raise OSError("simulated stat failure")
        return real_getmtime(path)

    monkeypatch.setattr(module.os.path, "getmtime", _raise_for_gone)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))

    module._run()

    assert "gone.py" in capsys.readouterr().err


def test_tracked_diff_timeout_is_caught_and_warned(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(module.subprocess, "run", _raise_timeout)

    result = module._tracked_diff_added_lines(str(tmp_path), set())

    assert result == {}
    assert "timed out" in capsys.readouterr().err.lower()


def test_heredoc_written_jinja_with_an_issue_reference_is_reported_as_a_bright_line(tmp_path):
    _init_git_repo(tmp_path)
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    baseline = _run(payload, env)
    assert baseline.stdout == ""

    target = _write(tmp_path, "templates/thing.jinja", "{# fixes #482 by capping retries #}\nkey: {{ value }}\n")
    _touch_future(target)

    result = _run(payload, env)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "BRIGHT LINE" in context
    assert "thing.jinja" in context


def test_second_call_over_the_cap_skips_before_any_per_file_read_or_stat(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setattr(module, "_repo_root", lambda cwd: str(tmp_path))
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setattr(module, "_candidate_files", lambda repo_root: ([], {}))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    module._run()

    nonexistent_paths = [f"pkg/module_{n}.py" for n in range(module._MAX_CANDIDATES + 1)]
    monkeypatch.setattr(module, "_candidate_files", lambda repo_root: (nonexistent_paths, {}))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))

    module._run()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{len(nonexistent_paths)} changed files exceeds the {module._MAX_CANDIDATES}-file cap" in captured.err
    assert "could not read" not in captured.err
    assert "could not stat" not in captured.err

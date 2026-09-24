import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _clock import FIXED_CLOCK as _FIXED_CLOCK

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "hooks" / "bash_backstop.py"


def _import_bash_backstop():
    spec = importlib.util.spec_from_file_location("bash_backstop", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_subprocess(payload, env):
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


@pytest.fixture
def run_backstop(monkeypatch):
    module = _import_bash_backstop()

    def _call(payload, state_path, clock=_FIXED_CLOCK):
        monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
        stdout = io.StringIO()
        monkeypatch.setattr(module.sys, "stdout", stdout)
        monkeypatch.setattr(module.time, "time", lambda: clock)
        monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", state_path)
        module._run()
        return stdout.getvalue()
    return _call


def _write(path, relpath, content):
    target = path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_main_prints_the_exception_type_and_message_to_stderr_instead_of_crashing(monkeypatch, capsys):
    module = _import_bash_backstop()

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_run", _raise)

    module.main()

    assert "bash_backstop: RuntimeError:" in capsys.readouterr().err


def test_non_git_cwd_produces_no_output(tmp_path):
    payload = {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state.json"))

    result = _run_subprocess(payload, env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_heredoc_written_test_docstring_is_reported_as_a_bright_line(git_repo, run_backstop):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    baseline = run_backstop(payload, state_path)
    assert baseline == ""

    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PostToolUse"
    assert "bright line" in hook_output["additionalContext"].lower()
    assert "test_x" in hook_output["additionalContext"]


def _touch_ahead(path, seconds=5, clock=_FIXED_CLOCK):
    future = clock + seconds
    os.utime(path, (future, future))


def test_second_call_does_not_report_an_untracked_file_older_than_the_baseline(git_repo, run_backstop):
    untracked = _write(git_repo, "pkg/untracked.py", '"""fixes #91"""\nVALUE = 1\n')
    old = _FIXED_CLOCK - 100
    os.utime(untracked, (old, old))
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    baseline = run_backstop(payload, state_path)
    assert baseline == ""

    result = run_backstop(payload, state_path)

    assert result == ""


def _seed_stamp(tmp_path, session_id, stamp):
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "bash_backstop_stamps.json").write_text(json.dumps({session_id: stamp}))
    return str(state_dir / "state.json")


def test_same_session_second_call_with_no_new_mtime_produces_no_output(git_repo, run_backstop):
    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    stamp = int(_FIXED_CLOCK)
    os.utime(target, (stamp - 10, stamp - 10))
    state_path = _seed_stamp(git_repo, "session-a", stamp)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}

    result = run_backstop(payload, state_path)

    assert result == ""


def test_mtime_equal_to_the_stamp_is_reported(git_repo, run_backstop):
    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    stamp = int(_FIXED_CLOCK)
    os.utime(target, (stamp, stamp))
    state_path = _seed_stamp(git_repo, "session-a", stamp)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_report_uses_the_posttooluse_hook_event_name(git_repo, run_backstop):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert output["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_file_with_mtime_equal_to_the_truncated_clock_is_reported_on_the_next_call(git_repo, run_backstop):
    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    pass\n')
    seed_stamp = int(_FIXED_CLOCK)
    state_path = _seed_stamp(git_repo, "session-a", seed_stamp)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    edit_stamp = seed_stamp + 10
    target.write_text('def test_x():\n    """doc"""\n')
    os.utime(target, (edit_stamp, edit_stamp))

    scan_clock = edit_stamp + 5
    first_scan = run_backstop(payload, state_path, clock=scan_clock)
    assert "test_x" in json.loads(first_scan)["hookSpecificOutput"]["additionalContext"]

    repeat_scan = run_backstop(payload, state_path, clock=scan_clock)

    assert repeat_scan == ""


def test_a_different_session_id_is_reported_again(git_repo, run_backstop):
    state_path = str(git_repo / "state" / "state.json")
    payload_a = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    payload_b = {"session_id": "session-b", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    assert run_backstop(payload_a, state_path) == ""

    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)

    first = run_backstop(payload_a, state_path)
    assert json.loads(first)["hookSpecificOutput"]["additionalContext"]

    baseline_b = run_backstop(payload_b, state_path)
    assert baseline_b == ""
    _touch_ahead(target, seconds=10)

    second = run_backstop(payload_b, state_path)
    assert json.loads(second)["hookSpecificOutput"]["additionalContext"]


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


def test_first_call_for_a_new_session_establishes_baseline_and_reports_nothing(git_repo, run_backstop):
    _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")

    first = run_backstop(payload, state_path)

    assert first == ""




def test_deleted_tracked_file_does_not_block_reporting_other_violations(git_repo, run_backstop):
    tracked = _write(git_repo, "pkg/tracked.py", "VALUE = 1\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    tracked.unlink()
    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_non_ascii_filename_is_reported_as_a_bright_line(git_repo, run_backstop):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    target = _write(git_repo, "tests/tést_ü.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_parse_diff_added_lines_single_line_hunk_header_without_a_count_adds_exactly_one_line():
    module = _import_bash_backstop()

    result = module._parse_diff_added_lines("+++ b/a.py\n@@ -0,0 +5 @@\n", {"a.py"})

    assert result == {"a.py": {5}}


def test_parse_diff_added_lines_hunk_header_with_an_explicit_count_adds_every_line_in_range():
    module = _import_bash_backstop()

    result = module._parse_diff_added_lines("+++ b/a.py\n@@ -0,0 +5,3 @@\n", {"a.py"})

    assert result == {"a.py": {5, 6, 7}}


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


def test_is_no_head_yet_is_false_for_exit_128_with_an_unrelated_git_error():
    module = _import_bash_backstop()
    result = subprocess.CompletedProcess(
        args=["git"], returncode=128,
        stdout="", stderr="fatal: detected dubious ownership in repository at '/repo'\n",
    )

    assert module._is_no_head_yet(result) is False


def test_is_no_head_yet_is_true_for_exit_128_with_an_unborn_head_error():
    module = _import_bash_backstop()
    result = subprocess.CompletedProcess(
        args=["git"], returncode=128,
        stdout="", stderr="fatal: ambiguous argument 'HEAD': unknown revision or path not in the working tree.\n",
    )

    assert module._is_no_head_yet(result) is True


def test_git_paths_warns_on_stderr_for_a_non_no_head_exit_128(tmp_path, monkeypatch, capsys):
    module = _import_bash_backstop()

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=128,
            stdout="", stderr="fatal: detected dubious ownership in repository at '/repo'\n",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    result = module._git_paths(str(tmp_path), ["ls-files", "--others", "--exclude-standard"])

    assert result == []
    err = capsys.readouterr().err
    assert "bash_backstop:" in err
    assert "dubious ownership" in err


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


def test_clean_line_appended_to_a_file_with_a_preexisting_advisory_produces_no_output(git_repo, run_backstop):
    tracked = _write(git_repo, "pkg/tracked.py", "# fixed on 2026-05-22 after the incident\npass\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    with tracked.open("a") as handle:
        handle.write("VALUE = 1\n")
    _touch_ahead(tracked)

    result = run_backstop(payload, state_path)

    assert result == ""


def test_violating_line_appended_to_a_tracked_file_reports_the_new_finding_without_echoing_the_date(git_repo, run_backstop):
    tracked = _write(git_repo, "pkg/tracked.py", "# fixed on 2026-05-22 after the incident\npass\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    with tracked.open("a") as handle:
        handle.write("# updated on 2026-09-24 with a new fix\nVALUE = 1\n")
    _touch_ahead(tracked)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context.count("date, measurement, or SHA") == 1
    assert "2026-09-24" not in context
    assert "near line 3" in context


def test_partial_write_to_the_stamps_file_is_rewritten_as_valid_json_on_the_next_run(git_repo, run_backstop):
    state_dir = git_repo / "state"
    state_dir.mkdir()
    stamps_path = state_dir / "bash_backstop_stamps.json"
    stamps_path.write_text('{"session-a": 123, "sess')
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(state_dir / "state.json")

    result = run_backstop(payload, state_path)

    assert result == ""
    assert json.loads(stamps_path.read_text()) == {"session-a": int(_FIXED_CLOCK)}

    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)
    second = run_backstop(payload, state_path)

    assert "test_x" in json.loads(second)["hookSpecificOutput"]["additionalContext"]


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
    lines = ["x" * (module._MAX_MESSAGE_BYTES - 30)]

    message = module._build_message(lines)

    assert message.endswith("... and 1 more findings")


def test_build_message_byte_cap_with_several_lines_already_kept_reports_the_exact_omitted_count():
    module = _import_bash_backstop()
    header = module._build_message([])
    budget = module._MAX_MESSAGE_BYTES - len(header.encode("utf-8"))
    # smallest length where a 4th line would overflow the budget, with 3 already fitting
    line_length = (budget - 6) // 4 + 1
    line = "x" * line_length
    lines = [line] * 6

    message = module._build_message(lines)

    assert message == header + "\n\n".join([line] * 3) + "\n\n... and 3 more findings"


def test_build_message_omitted_count_combines_the_finding_cap_and_the_byte_cap():
    module = _import_bash_backstop()
    header = module._build_message([])
    budget = module._MAX_MESSAGE_BYTES - len(header.encode("utf-8"))
    kept_count = 5
    # largest length where kept_count lines fit the budget with separators between them
    line_length = (budget - 2 * (kept_count - 1)) // kept_count
    line = "x" * line_length
    over_the_cap = module._MAX_FINDINGS + 5
    lines = [line] * over_the_cap

    message = module._build_message(lines)

    assert message.count(line) == kept_count
    assert message.endswith(f"... and {over_the_cap - kept_count} more findings")


def test_build_message_keeps_a_line_that_exactly_fills_the_remaining_budget():
    module = _import_bash_backstop()
    header = module._build_message([])
    budget = module._MAX_MESSAGE_BYTES - len(header.encode("utf-8"))
    line = "x" * budget

    message = module._build_message([line])

    assert message == header + line
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


def test_modified_tracked_file_is_reported_as_a_bright_line(git_repo, run_backstop):
    tracked = _write(git_repo, "tests/test_thing.py", "def test_x():\n    pass\n")
    subprocess.run(["git", "add", "tests/test_thing.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked test"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    tracked.write_text('def test_x():\n    """doc"""\n')
    _touch_ahead(tracked)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert "bright line" in output["hookSpecificOutput"]["additionalContext"].lower()


def test_cwd_in_subdirectory_of_repo_still_finds_changes(git_repo, run_backstop):
    subdir = git_repo / "pkg" / "sub"
    subdir.mkdir(parents=True)
    payload = {"session_id": "session-a", "cwd": str(subdir), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_import_of_comment_intent_guard_works_when_launched_from_an_unrelated_cwd(git_repo):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(git_repo / "state" / "state.json"))

    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(git_repo),
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_advisory_only_file_appears_without_a_bright_line_tag(git_repo, run_backstop):
    tracked = _write(git_repo, "pkg/tracked.py", "pass\n")
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    with tracked.open("a") as handle:
        handle.write("# updated on 2026-09-24 with a new fix\nVALUE = 1\n")
    _touch_ahead(tracked)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "date, measurement, or SHA" in context
    assert "BRIGHT LINE" not in context


def _git_call_count_for_a_modified_candidate_scan(repo_dir, monkeypatch, file_count, git_repo_template):
    shutil.copytree(git_repo_template, repo_dir)
    for n in range(file_count):
        _write(repo_dir, f"pkg/module_{n}.py", f"VALUE_{n} = {n}\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add modules"], cwd=repo_dir, check=True)
    module = _import_bash_backstop()
    monkeypatch.setattr(module.time, "time", lambda: _FIXED_CLOCK)
    payload = {"session_id": "session-a", "cwd": str(repo_dir), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(repo_dir / "state" / "state.json"))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    module._run()

    for n in range(file_count):
        target = repo_dir / "pkg" / f"module_{n}.py"
        target.write_text(f"VALUE_{n} = {n + 1}\n")
    for target in (repo_dir / "pkg").glob("*.py"):
        _touch_ahead(target)

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


def test_git_call_count_stays_constant_regardless_of_candidate_count(tmp_path, monkeypatch, git_repo_template):
    one_candidate = _git_call_count_for_a_modified_candidate_scan(
        tmp_path / "one", monkeypatch, file_count=1, git_repo_template=git_repo_template
    )
    fifty_candidates = _git_call_count_for_a_modified_candidate_scan(
        tmp_path / "fifty", monkeypatch, file_count=50, git_repo_template=git_repo_template
    )

    assert one_candidate == fifty_candidates


def test_backstop_reports_blocking_findings_from_an_unanalyzable_file(git_repo, monkeypatch):
    _write(git_repo, "pkg/untracked.py", "pass\n")
    module = _import_bash_backstop()
    monkeypatch.setattr(module.time, "time", lambda: _FIXED_CLOCK)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(git_repo / "state" / "state.json"))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    module._run()

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


def test_git_paths_failure_other_than_missing_head_is_warned(git_repo, monkeypatch, capsys):
    module = _import_bash_backstop()

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="fatal: index file corrupt")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    result = module._git_paths(str(git_repo), ["diff", "--name-only", "HEAD"])

    assert result == []
    assert "index file corrupt" in capsys.readouterr().err


def test_diff_failure_other_than_missing_head_is_warned(git_repo, monkeypatch, capsys):
    module = _import_bash_backstop()

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="fatal: index file corrupt")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    result = module._tracked_diff_added_lines(str(git_repo), set())

    assert result == {}
    assert "index file corrupt" in capsys.readouterr().err


def test_missing_session_id_still_tracks_a_baseline_stamp_and_stops_reporting_once_the_stamp_passes_the_mtime(
    git_repo, run_backstop,
):
    payload = {"cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    target = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(target)
    first = run_backstop(payload, state_path, clock=_FIXED_CLOCK + 6)
    assert "test_x" in json.loads(first)["hookSpecificOutput"]["additionalContext"]

    third = run_backstop(payload, state_path)

    assert third == ""


def test_heredoc_written_yaml_with_an_issue_reference_is_reported_as_a_bright_line(git_repo, run_backstop):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    baseline = run_backstop(payload, state_path)
    assert baseline == ""

    target = _write(git_repo, "config/thing.yaml", "# fixes #482 by capping retries\nkey: value\n")
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "BRIGHT LINE" in context
    assert "thing.yaml" in context


def test_tracked_file_with_a_space_in_its_name_is_reported(git_repo, run_backstop):
    target = _write(git_repo, "pkg/my file.py", "pass\n")
    subprocess.run(["git", "add", "pkg/my file.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add spaced file"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    with target.open("a") as handle:
        handle.write("# updated on 2026-09-24 with a fix (issue #482)\nVALUE = 1\n")
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "my file.py" in context
    assert "BRIGHT LINE" in context


def test_added_line_starting_with_plus_plus_does_not_break_a_later_hunk(git_repo, run_backstop):
    original = "\n".join(f"line_{n} = {n}" for n in range(1, 11)) + "\n"
    target = _write(git_repo, "pkg/tracked.py", original)
    subprocess.run(["git", "add", "pkg/tracked.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add tracked"], cwd=git_repo, check=True)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    lines = [f"line_{n} = {n}" for n in range(1, 11)]
    lines.insert(1, "++ this looks like a diff header but is not")
    lines.append("# updated on 2026-09-24 with a fix")
    target.write_text("\n".join(lines) + "\n")
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "tracked.py" in context
    assert "date, measurement, or SHA" in context


def test_candidate_missing_from_disk_warns_with_its_path(git_repo, monkeypatch, capsys):
    target = _write(git_repo, "pkg/gone.py", "pass\n")
    subprocess.run(["git", "add", "pkg/gone.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add gone"], cwd=git_repo, check=True)
    with target.open("a") as handle:
        handle.write("VALUE = 1\n")
    _touch_ahead(target)
    module = _import_bash_backstop()
    monkeypatch.setattr(module.time, "time", lambda: _FIXED_CLOCK)
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", str(git_repo / "state" / "state.json"))
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


def test_heredoc_written_jinja_with_an_issue_reference_is_reported_as_a_bright_line(git_repo, run_backstop):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    baseline = run_backstop(payload, state_path)
    assert baseline == ""

    target = _write(git_repo, "templates/thing.jinja", "{# fixes #482 by capping retries #}\nkey: {{ value }}\n")
    _touch_ahead(target)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "BRIGHT LINE" in context
    assert "thing.jinja" in context


def test_an_unreadable_file_does_not_stop_a_later_file_from_being_reported(git_repo, monkeypatch, capsys):
    module = _import_bash_backstop()
    state_path = str(git_repo / "state" / "state.json")

    def _call(payload):
        monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
        stdout = io.StringIO()
        monkeypatch.setattr(module.sys, "stdout", stdout)
        monkeypatch.setattr(module.time, "time", lambda: _FIXED_CLOCK)
        monkeypatch.setenv("COMMENT_INTENT_GUARD_STATE", state_path)
        module._run()
        return stdout.getvalue()

    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    assert _call(payload) == ""

    unreadable = _write(git_repo, "pkg/blocked.py", "VALUE = 1\n")
    readable = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(unreadable)
    _touch_ahead(readable)
    real_open = open

    def _flaky_open(path, *args, **kwargs):
        if path == str(unreadable):
            raise OSError("Permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(module, "open", _flaky_open, raising=False)

    result = _call(payload)

    output = json.loads(result)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]
    stderr = capsys.readouterr().err
    assert "could not read" in stderr
    assert "blocked.py" in stderr


def test_a_file_that_disappears_before_stat_does_not_stop_a_later_file_from_being_reported(
    git_repo, run_backstop, monkeypatch, capsys,
):
    payload = {"session_id": "session-a", "cwd": str(git_repo), "tool_name": "Bash", "tool_input": {}}
    state_path = str(git_repo / "state" / "state.json")
    assert run_backstop(payload, state_path) == ""

    vanished = _write(git_repo, "pkg/vanished.py", "VALUE = 1\n")
    readable = _write(git_repo, "tests/test_thing.py", 'def test_x():\n    """doc"""\n')
    _touch_ahead(vanished)
    _touch_ahead(readable)
    real_getmtime = os.path.getmtime

    def _flaky_getmtime(path):
        if path == str(vanished):
            raise OSError("No such file or directory")
        return real_getmtime(path)

    monkeypatch.setattr(os.path, "getmtime", _flaky_getmtime)

    result = run_backstop(payload, state_path)

    output = json.loads(result)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]
    stderr = capsys.readouterr().err
    assert "could not stat" in stderr
    assert "vanished.py" in stderr


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

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "hooks" / "session_start.py"


def _import_session_start():
    spec = importlib.util.spec_from_file_location("session_start", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(payload_input, tmp_path):
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input=payload_input,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def test_session_start_emits_context_naming_the_skill(tmp_path):
    result = _run("", tmp_path)

    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert "self-documenting-code" in hook_output["additionalContext"]


def test_session_start_seeds_a_stamp_for_the_session_id(tmp_path):
    payload = json.dumps({"session_id": "session-a", "cwd": str(tmp_path), "source": "startup"})

    result = _run(payload, tmp_path)

    assert result.returncode == 0
    stamps_path = tmp_path / "state" / "bash_backstop_stamps.json"
    stamps = json.loads(stamps_path.read_text())
    assert "session-a" in stamps
    assert isinstance(stamps["session-a"], (int, float))


def test_second_session_start_call_for_the_same_id_leaves_the_stamp_unchanged(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    seeded_stamp = 1_700_000_000
    (state_dir / "bash_backstop_stamps.json").write_text(json.dumps({"session-a": seeded_stamp}))

    result = _run(json.dumps({"session_id": "session-a", "cwd": str(tmp_path), "source": "resume"}), tmp_path)

    assert result.returncode == 0
    stamps_path = state_dir / "bash_backstop_stamps.json"
    assert json.loads(stamps_path.read_text())["session-a"] == seeded_stamp


def test_first_backstop_call_after_a_session_start_seed_reports_a_write(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=tmp_path, check=True)
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))

    session_payload = json.dumps({"session_id": "session-a", "cwd": str(tmp_path), "source": "startup"})
    session_result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input=session_payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert session_result.returncode == 0

    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('def test_x():\n    """doc"""\n')
    future = time.time() + 5
    os.utime(target, (future, future))

    backstop_script = _SCRIPT_PATH.parent / "bash_backstop.py"
    backstop_payload = json.dumps(
        {"session_id": "session-a", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
    )
    backstop_result = subprocess.run(
        [sys.executable, str(backstop_script)],
        input=backstop_payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    assert backstop_result.returncode == 0
    output = json.loads(backstop_result.stdout)
    assert "test_x" in output["hookSpecificOutput"]["additionalContext"]


def test_seed_failure_does_not_lose_the_skill_stanza(tmp_path, monkeypatch, capsys):
    module = _import_session_start()
    env = dict(os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state" / "state.json"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def _raise(raw_input):
        raise OSError("simulated seeding failure")

    monkeypatch.setattr(module, "_seed_baseline_if_absent", _raise)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(""))

    module.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert "self-documenting-code" in hook_output["additionalContext"]
    assert "bash_backstop:" in captured.err

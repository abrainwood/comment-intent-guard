#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comment_intent_guard as guard  # noqa: E402

_TRACKED_GLOBS = ["*.py", "*.yaml", "*.yml", "*.jinja", "*.j2"]
_MAX_CANDIDATES = 200


def _stamps_path():
    return os.path.join(os.path.dirname(guard._state_path()), "bash_backstop_stamps.json")


def _last_run(stamps, session_id):
    stamp = stamps.get(session_id)
    return stamp if isinstance(stamp, (int, float)) else 0


def _repo_root(cwd):
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_paths(repo_root, args):
    result = subprocess.run(
        ["git", "-C", repo_root, *args, "--", *_TRACKED_GLOBS],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _candidate_files(repo_root):
    changed = _git_paths(repo_root, ["diff", "--name-only", "HEAD"])
    untracked = _git_paths(repo_root, ["ls-files", "--others", "--exclude-standard"])
    relpaths = sorted(set(changed) | set(untracked))
    return [os.path.join(repo_root, relpath) for relpath in relpaths]


def _findings_message(file_path, blocking, advisory):
    lines = [f"{file_path}: BRIGHT LINE - {message}" for message, _ in blocking]
    lines += [f"{file_path}: {message}" for message, _ in advisory]
    return lines


def main():
    try:
        _run()
    except Exception as exc:
        print(f"bash_backstop: {type(exc).__name__}: {exc}", file=sys.stderr)


def _run():
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    if not isinstance(cwd, str):
        return

    repo_root = _repo_root(cwd)
    if repo_root is None:
        return

    candidates = _candidate_files(repo_root)
    if len(candidates) > _MAX_CANDIDATES:
        guard._warn(
            f"{len(candidates)} changed files exceeds the {_MAX_CANDIDATES}-file cap - skipping this run"
        )
        return

    session_key = session_id if isinstance(session_id, str) else None
    stamps_path = _stamps_path()
    stamps = guard._load_state(stamps_path)

    if session_key is not None and session_key not in stamps:
        # First call for a session establishes the mtime baseline; the backstop
        # covers writes made during this session, not the repo's pre-existing state.
        stamps[session_key] = time.time()
        guard._save_state(stamps_path, stamps)
        return

    last_run = _last_run(stamps, session_key) if session_key else 0
    fresh = [f for f in candidates if os.path.getmtime(f) > last_run]

    lines = []
    for file_path in fresh:
        try:
            with open(file_path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            guard._warn(f"could not read {file_path} ({type(exc).__name__}) - skipping")
            continue
        try:
            blocking, advisory = guard._findings_for_file(file_path, text)
        except guard.AnalysisUnavailable as exc:
            blocking = getattr(exc, "blocking", [])
            advisory = []
        lines.extend(_findings_message(file_path, blocking, advisory))

    if isinstance(session_id, str):
        stamps[session_id] = time.time()
        guard._save_state(stamps_path, stamps)

    if not lines:
        return

    message = "COMMENT INTENT CHECK (Bash backstop):\n\n" + "\n\n".join(lines)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()

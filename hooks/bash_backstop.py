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
_GIT_TIMEOUT_SECONDS = 5


def _stamps_path():
    return os.path.join(os.path.dirname(guard._state_path()), "bash_backstop_stamps.json")


def _last_run(stamps, session_id):
    stamp = stamps.get(session_id)
    return stamp if isinstance(stamp, (int, float)) else 0


def _repo_root(cwd):
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        guard._warn("git rev-parse --show-toplevel timed out - skipping this run")
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_paths(repo_root, args):
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, *args, "-z", "--", *_TRACKED_GLOBS],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        guard._warn(f"git {' '.join(args)} timed out - skipping this listing")
        return []
    if result.returncode != 0:
        return []
    return [entry for entry in result.stdout.split("\0") if entry]


def _candidate_files(repo_root):
    changed = _git_paths(repo_root, ["diff", "--name-only", "--diff-filter=d", "--ignore-submodules", "HEAD"])
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

    # Captured before listing/scanning so the stamp we persist can never be
    # later than the mtimes it is meant to bound - see the >= comparison below.
    now = int(time.time())

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
        stamps[session_key] = now
        guard._save_state(stamps_path, stamps)
        return

    last_run = _last_run(stamps, session_key) if session_key else 0
    fresh = []
    for candidate in candidates:
        try:
            mtime = os.path.getmtime(candidate)
        except OSError:
            continue
        # mtime resolution is one second on some filesystems; >= trades an
        # occasional duplicate report for never missing a same-second write.
        if int(mtime) >= last_run:
            fresh.append(candidate)

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
        added = guard._added_line_numbers("HEAD", file_path)
        if added is not None:
            advisory = guard._restrict_to_added_lines(advisory, added)
        lines.extend(_findings_message(file_path, blocking, advisory))

    if session_key is not None:
        stamps[session_key] = now
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

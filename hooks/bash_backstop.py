#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comment_intent_guard as guard  # noqa: E402

_TRACKED_GLOBS = ["*.py", "*.yaml", "*.yml", "*.jinja", "*.j2"]
_MAX_CANDIDATES = 200
_GIT_TIMEOUT_SECONDS = 5
_MAX_FINDINGS = 40
_MAX_MESSAGE_BYTES = 4096
_ANONYMOUS_SESSION_KEY = "__no_session_id__"


def _stamps_path():
    return os.path.join(os.path.dirname(guard._state_path()), "bash_backstop_stamps.json")


def _save_stamps(stamps_path, session_key, stamp, stamps):
    stamps.pop(session_key, None)
    stamps[session_key] = stamp
    guard._evict_oldest_sessions(stamps)
    directory = os.path.dirname(stamps_path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".bash_backstop_stamps_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(stamps, handle)
            os.replace(tmp_path, stamps_path)
        except OSError:
            os.unlink(tmp_path)
            raise
    except OSError as exc:
        guard._warn(f"could not persist stamps to {stamps_path} ({type(exc).__name__})", prefix="bash_backstop")


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
        guard._warn("git rev-parse --show-toplevel timed out - skipping this run", prefix="bash_backstop")
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_no_head_yet(result):
    stderr = result.stderr.lower()
    return result.returncode == 128 and ("unknown revision" in stderr or "bad revision" in stderr)


def _git_paths(repo_root, args):
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, *args, "-z", "--", *_TRACKED_GLOBS],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        guard._warn(f"git {' '.join(args)} timed out - skipping this listing", prefix="bash_backstop")
        return []
    if result.returncode != 0:
        if not _is_no_head_yet(result):
            guard._warn(
                f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}",
                prefix="bash_backstop",
            )
        return []
    return [entry for entry in result.stdout.split("\0") if entry]


def _unquote_git_header_path(raw):
    # A path with a space gets a trailing tab (git's own disambiguation);
    # a path with control characters gets wrapped in C-quotes instead.
    raw = raw.removesuffix("\t")
    if raw.startswith('"') and raw.endswith('"'):
        try:
            raw = raw[1:-1].encode("latin1").decode("unicode_escape").encode("latin1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return raw


def _parse_diff_added_lines(diff_output, known_relpaths):
    added_by_relpath = {}
    current_relpath = None
    in_hunks = False
    for line in diff_output.splitlines():
        if line.startswith("diff --git "):
            in_hunks = False
            current_relpath = None
            continue
        if not in_hunks and line.startswith("+++ "):
            path_part = _unquote_git_header_path(line[len("+++ "):])
            current_relpath = None if path_part == "/dev/null" else path_part.removeprefix("b/")
            if current_relpath in known_relpaths:
                added_by_relpath.setdefault(current_relpath, set())
            else:
                current_relpath = None
            in_hunks = True
            continue
        match = guard._HUNK_HEADER_RE.match(line)
        if match is not None and current_relpath is not None:
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            added_by_relpath[current_relpath].update(range(start, start + count))
    return added_by_relpath


def _tracked_diff_added_lines(repo_root, known_relpaths):
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "-z",
             "--ignore-submodules", "--diff-filter=d", "HEAD", "--", *_TRACKED_GLOBS],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        guard._warn("git diff HEAD timed out - skipping this run", prefix="bash_backstop")
        return {}
    if result.returncode != 0:
        if not _is_no_head_yet(result):
            guard._warn(
                f"git diff HEAD failed (exit {result.returncode}): {result.stderr.strip()}",
                prefix="bash_backstop",
            )
        return {}
    return _parse_diff_added_lines(result.stdout, known_relpaths)


def _candidate_files(repo_root):
    tracked = set(_git_paths(repo_root, ["diff", "--name-only", "--diff-filter=d", "--ignore-submodules", "HEAD"]))
    untracked = _git_paths(repo_root, ["ls-files", "--others", "--exclude-standard"])
    added_by_relpath = _tracked_diff_added_lines(repo_root, tracked)
    relpaths = sorted(tracked | set(untracked))
    candidates = [os.path.join(repo_root, relpath) for relpath in relpaths]
    return candidates, added_by_relpath


def _findings_message(file_path, blocking, advisory):
    lines = [f"{file_path}: BRIGHT LINE - {message}" for message, _ in blocking]
    lines += [f"{file_path}: {message}" for message, _ in advisory]
    return lines


def _build_message(lines):
    header = "COMMENT INTENT CHECK (Bash backstop):\n\n"
    capped = lines[:_MAX_FINDINGS]
    omitted = len(lines) - len(capped)

    budget = _MAX_MESSAGE_BYTES - len(header.encode("utf-8"))
    kept = []
    used = 0
    for line in capped:
        piece = line if not kept else "\n\n" + line
        size = len(piece.encode("utf-8"))
        if used + size > budget:
            omitted += len(capped) - len(kept)
            break
        kept.append(line)
        used += size

    message = header + "\n\n".join(kept)
    if omitted:
        message += f"\n\n... and {omitted} more findings"
    return message


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

    candidates, added_by_relpath = _candidate_files(repo_root)
    if len(candidates) > _MAX_CANDIDATES:
        guard._warn(
            f"{len(candidates)} changed files exceeds the {_MAX_CANDIDATES}-file cap - skipping this run",
            prefix="bash_backstop",
        )
        return

    session_key = session_id if isinstance(session_id, str) else _ANONYMOUS_SESSION_KEY
    stamps_path = _stamps_path()
    stamps = guard._load_state(stamps_path)

    if session_key not in stamps:
        # First call for a session establishes the mtime baseline; the backstop
        # covers writes made during this session, not the repo's pre-existing state.
        _save_stamps(stamps_path, session_key, now, stamps)
        return

    last_run = _last_run(stamps, session_key)
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
            guard._warn(f"could not read {file_path} ({type(exc).__name__}) - skipping", prefix="bash_backstop")
            continue
        try:
            blocking, advisory = guard._findings_for_file(file_path, text)
        except guard.AnalysisUnavailable as exc:
            blocking = getattr(exc, "blocking", [])
            advisory = []
        relpath = os.path.relpath(file_path, repo_root)
        added = added_by_relpath.get(relpath)
        if added is not None:
            advisory = guard._restrict_to_added_lines(advisory, added)
        lines.extend(_findings_message(file_path, blocking, advisory))

    _save_stamps(stamps_path, session_key, now, stamps)

    if not lines:
        return

    message = _build_message(lines)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()

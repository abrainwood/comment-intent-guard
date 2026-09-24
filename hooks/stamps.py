#!/usr/bin/env python3
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comment_intent_guard as guard  # noqa: E402

ANONYMOUS_SESSION_KEY = "__no_session_id__"


def session_key_for(session_id):
    return session_id if isinstance(session_id, str) else ANONYMOUS_SESSION_KEY


def stamps_path():
    return os.path.join(os.path.dirname(guard._state_path()), "bash_backstop_stamps.json")


def load_stamps(path):
    return guard._load_state(path)


def last_run(stamps, session_key):
    stamp = stamps.get(session_key)
    return stamp if isinstance(stamp, (int, float)) else 0


def save_stamps(path, session_key, stamp, stamps):
    stamps.pop(session_key, None)
    stamps[session_key] = stamp
    guard._evict_oldest_sessions(stamps)
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".bash_backstop_stamps_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(stamps, handle)
            os.replace(tmp_path, path)
        except OSError:
            os.unlink(tmp_path)
            raise
    except OSError as exc:
        guard._warn(f"could not persist stamps to {path} ({type(exc).__name__})", prefix="bash_backstop")

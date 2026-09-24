#!/usr/bin/env python3
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comment_intent_guard as guard  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stamps  # noqa: E402

_STANZA = "\n".join(
    [
        "Self-documenting code, always: write code that needs no comment.",
        "If it needs one, that's an alarm about the design, not a fact to",
        "transcribe - answer it upstream (rename, retype, change the",
        "approach, split). Two residues survive: a body line for an",
        "external quirk or an algorithm's own requirement, or an interface",
        "docstring when name and types are exhausted. No test docstring",
        "ever survives - rename the test instead.",
        "Full rule and worked examples: /comment-intent-guard:self-documenting-code.",
    ]
)


def _seed_baseline_if_absent(raw_input):
    try:
        payload = json.loads(raw_input) if raw_input else {}
    except json.JSONDecodeError:
        payload = {}
    session_key = stamps.session_key_for(payload.get("session_id") if isinstance(payload, dict) else None)
    path = stamps.stamps_path()
    all_stamps = stamps.load_stamps(path)
    if session_key in all_stamps:
        return
    stamps.save_stamps(path, session_key, int(time.time()), all_stamps)


def main():
    raw_input = sys.stdin.read()
    try:
        _seed_baseline_if_absent(raw_input)
    except (OSError, ValueError) as exc:
        guard._warn(f"could not seed session baseline ({type(exc).__name__})", prefix="bash_backstop")
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _STANZA,
        }
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()

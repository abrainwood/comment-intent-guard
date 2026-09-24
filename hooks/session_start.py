#!/usr/bin/env python3
import json
import sys

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


def main():
    sys.stdin.read()
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _STANZA,
        }
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()

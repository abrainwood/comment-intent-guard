import json
import subprocess
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "hooks" / "session_start.py"


def test_session_start_emits_context_naming_the_skill():
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )

    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert "self-documenting-code" in hook_output["additionalContext"]

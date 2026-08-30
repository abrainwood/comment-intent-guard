import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"


def _load_module(module_path=_MODULE_PATH, name="comment_intent_guard_under_test"):
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module()


# home-assistant-config's differential test imports find_misplaced_rationale
# and DOCSTRING_LINE_THRESHOLD from this module directly - keep both listed
# below whenever this surface changes.
PUBLIC_FUNCTIONS = {
    "find_misplaced_rationale": ("text",),
    "find_yaml_findings": ("text",),
    "find_blocking_violations": ("text", "file_path"),
    "count_test_function_docstrings": ("text",),
    "count_comment_and_code_lines": ("text",),
    "aggregate_density_finding": ("comment_lines", "code_lines"),
    "record_edit": ("state_path", "session_id", "comment_lines", "code_lines"),
    "main": (),
}

PUBLIC_CONSTANTS = {
    "DOCSTRING_LINE_THRESHOLD": int,
    "COMMENT_RUN_LINE_THRESHOLD": int,
    "YAML_COMMENT_RUN_LINE_THRESHOLD": int,
    "JINJA_BLOCK_LINE_THRESHOLD": int,
    "YAML_DESCRIPTION_LINE_THRESHOLD": int,
    "PEER_COMMENT_DENSITY": float,
    "MIN_CODE_LINES_FOR_DENSITY": int,
    "MAX_TRACKED_SESSIONS": int,
}

PUBLIC_EXCEPTIONS = {
    "AnalysisUnavailable": Exception,
}


def _missing_declared_functions(module, functions):
    return [name for name in functions if not hasattr(module, name)]


def test_declared_functions_exist_on_the_module():
    missing = _missing_declared_functions(guard, PUBLIC_FUNCTIONS)
    assert not missing, f"declared public functions missing from the module: {missing}"


def test_declared_function_parameters_match_the_declared_arity():
    for name, params in PUBLIC_FUNCTIONS.items():
        actual = tuple(inspect.signature(getattr(guard, name)).parameters)
        assert actual == params, f"{name} has parameters {actual}, declared as {params}"


def test_finding_producing_functions_return_lists_of_message_and_span_pairs():
    prose = "\n".join(f"    reason {i}" for i in range(guard.DOCSTRING_LINE_THRESHOLD + 1))
    misplaced = guard.find_misplaced_rationale(f'"""\n{prose}\n"""\n')

    yaml_lines = "\n".join(f"# reason {i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1))
    yaml_findings = guard.find_yaml_findings(f"{yaml_lines}\nkey: value\n")

    blocking = guard.find_blocking_violations(
        'def test_thing():\n    """Checks the thing."""\n    assert True\n',
        "/repo/tests/test_thing.py",
    )

    for findings in (misplaced, yaml_findings, blocking):
        assert findings
        for finding in findings:
            message, span = finding
            assert isinstance(message, str)
            start, end = span
            assert isinstance(start, int) and isinstance(end, int)


def test_declared_constants_have_the_declared_type():
    for name, expected_type in PUBLIC_CONSTANTS.items():
        actual = getattr(guard, name)
        assert type(actual) is expected_type, f"{name} is {type(actual).__name__}, declared as {expected_type.__name__}"


def test_declared_exceptions_exist_and_derive_from_the_declared_base():
    for name, base in PUBLIC_EXCEPTIONS.items():
        assert hasattr(guard, name), f"declared public exception {name!r} is missing from the module"
        assert issubclass(getattr(guard, name), base)


def _run_cli(args):
    return subprocess.run(
        [sys.executable, str(_MODULE_PATH), *args],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_cli_exit_codes_are_0_clean_1_advisory_3_bright_line_4_internal_error(tmp_path):
    clean = tmp_path / "clean.yaml"
    clean.write_text("key: value\n")
    assert _run_cli(["--all", str(clean)]).returncode == 0

    advisory = tmp_path / "advisory.yaml"
    advisory.write_text(
        "\n".join(f"# reason {i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1))
        + "\nkey: value\n"
    )
    assert _run_cli(["--all", str(advisory)]).returncode == 1

    bright_line = tmp_path / "jira123_fix.py"
    bright_line.write_text("VALUE = 1\n")
    assert _run_cli(["--all", str(bright_line)]).returncode == 3

    missing = tmp_path / "does_not_exist.yaml"
    assert _run_cli(["--all", str(missing)]).returncode == 4


def test_existence_check_catches_a_declared_function_renamed_on_the_module():
    renamed = _load_module(name="comment_intent_guard_renamed_for_test")
    renamed.find_misplaced_rationale_v2 = renamed.find_misplaced_rationale
    del renamed.find_misplaced_rationale

    missing = _missing_declared_functions(renamed, PUBLIC_FUNCTIONS)

    assert missing == ["find_misplaced_rationale"]

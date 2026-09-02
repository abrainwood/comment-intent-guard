import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"


def _load_module(module_path=_MODULE_PATH, name="comment_intent_guard_under_test"):
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module()


# A private downstream consumer's differential test imports find_misplaced_rationale
# and DOCSTRING_LINE_THRESHOLD from this module directly - keep both listed
# below whenever this surface changes.
PUBLIC_FUNCTIONS = {
    "find_misplaced_rationale": ("text",),
    "find_yaml_findings": ("text",),
    "find_blocking_violations": ("text", "file_path"),
    "find_issue_reference_violations": ("text",),
    "find_yaml_issue_reference_violations": ("text",),
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


def _shape_problems(findings):
    problems = []
    for finding in findings:
        try:
            message, span = finding
        except (TypeError, ValueError) as exc:
            problems.append(str(exc))
            continue
        if not isinstance(message, str):
            problems.append(f"message is {type(message).__name__}, not str")
        try:
            start, end = span
        except (TypeError, ValueError) as exc:
            problems.append(str(exc))
            continue
        if not (isinstance(start, int) and isinstance(end, int)):
            problems.append(f"span is ({type(start).__name__}, {type(end).__name__}), not (int, int)")
    return problems


def _oversize_docstring_text():
    prose = "\n".join(f"    reason {i}" for i in range(guard.DOCSTRING_LINE_THRESHOLD + 1))
    return f'"""\n{prose}\n"""\n'


def _misplaced_rationale_sample():
    return guard.find_misplaced_rationale(_oversize_docstring_text())


# The same downstream consumer's differential test also couples to this literal
# message prefix from find_misplaced_rationale, via f.startswith(...) -
# renaming the wording (not just the symbol) is a breaking change too.
CONSUMER_MESSAGE_PREFIXES = {
    "find_misplaced_rationale": "Docstring spans",
}


def _missing_consumer_prefixes(module):
    missing = []
    for fn_name, prefix in CONSUMER_MESSAGE_PREFIXES.items():
        findings = getattr(module, fn_name)(_oversize_docstring_text())
        if not any(message.startswith(prefix) for message, _ in findings):
            missing.append((fn_name, prefix))
    return missing


def _yaml_findings_sample():
    yaml_lines = "\n".join(f"# reason {i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1))
    return guard.find_yaml_findings(f"{yaml_lines}\nkey: value\n")


def _blocking_violations_sample():
    return guard.find_blocking_violations(
        'def test_thing():\n    """Checks the thing."""\n    assert True\n',
        "/repo/tests/test_thing.py",
    )


@pytest.mark.parametrize(
    "build_findings",
    [_misplaced_rationale_sample, _yaml_findings_sample, _blocking_violations_sample],
    ids=["find_misplaced_rationale", "find_yaml_findings", "find_blocking_violations"],
)
def test_finding_producing_function_returns_well_shaped_findings(build_findings):
    findings = build_findings()
    assert findings
    assert _shape_problems(findings) == []


def test_docstring_finding_span_tracks_where_the_docstring_actually_sits():
    body_line_count = guard.DOCSTRING_LINE_THRESHOLD + 1
    prose = "\n".join(f"    reason {i}" for i in range(body_line_count))

    for leading_lines in (0, 5):
        prefix = "x = 1\n" * leading_lines
        text = f'{prefix}"""\n{prose}\n"""\n'

        findings = guard.find_misplaced_rationale(text)

        _, span = next(f for f in findings if f[0].startswith("Docstring spans"))
        start, end = span
        assert start <= end
        assert span == (1 + leading_lines, body_line_count + 2 + leading_lines)


def test_yaml_comment_run_span_tracks_where_the_run_actually_sits():
    run_len = guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1
    run_lines = "\n".join(f"# reason {i}" for i in range(run_len))

    for leading_lines in (0, 5):
        prefix = "key0: value\n" * leading_lines
        text = f"{prefix}{run_lines}\nkey: value\n"

        findings = guard.find_yaml_findings(text)

        _, span = next(f for f in findings if f[0].startswith("Comment run"))
        start, end = span
        assert start <= end
        assert span == (1 + leading_lines, run_len + leading_lines)


def test_blocking_violation_span_tracks_where_the_flagged_docstring_actually_sits():
    for leading_lines in (0, 5):
        prefix = "x = 1\n" * leading_lines
        text = f'{prefix}"""MG-1 golden case\nsecond line\nthird line\n"""\nVALUE = 1\n'

        violations = guard.find_blocking_violations(text, "/repo/tests/test_gap.py")

        _, span = next(v for v in violations if "MG-1" in v[0])
        start, end = span
        assert start <= end
        assert span == (1 + leading_lines, 4 + leading_lines)


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


def _clean_yaml(tmp_path):
    path = tmp_path / "clean.yaml"
    path.write_text("key: value\n")
    return path


def _advisory_yaml(tmp_path):
    path = tmp_path / "advisory.yaml"
    path.write_text(
        "\n".join(f"# reason {i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1))
        + "\nkey: value\n"
    )
    return path


def _bright_line_py(tmp_path):
    path = tmp_path / "jira123_fix.py"
    path.write_text("VALUE = 1\n")
    return path


def _missing_yaml(tmp_path):
    return tmp_path / "does_not_exist.yaml"


@pytest.mark.parametrize(
    "build_file, expected_code",
    [(_clean_yaml, 0), (_advisory_yaml, 1), (_bright_line_py, 3), (_missing_yaml, 4)],
    ids=["clean", "advisory", "bright_line", "internal_error"],
)
def test_cli_exit_code_matches_the_finding_severity(build_file, expected_code, tmp_path):
    path = build_file(tmp_path)
    assert _run_cli(["--all", str(path)]).returncode == expected_code


def test_cli_exit_code_for_a_missing_file_argument_is_a_usage_error():
    assert _run_cli(["--all"]).returncode == 2


def _module_public_names(module):
    return {
        name for name, obj in vars(module).items()
        if not name.startswith("_")
        and not inspect.ismodule(obj)
        and getattr(obj, "__module__", module.__name__) == module.__name__
    }


def _declared_public_names():
    return set(PUBLIC_FUNCTIONS) | set(PUBLIC_CONSTANTS) | set(PUBLIC_EXCEPTIONS)


def test_declared_surface_matches_the_modules_actual_public_surface():
    assert _module_public_names(guard) == _declared_public_names()


def test_surface_check_catches_a_new_public_function_left_undeclared():
    added = _load_module(name="comment_intent_guard_extra_symbol_for_test")
    added.a_new_undeclared_function = lambda: None
    added.a_new_undeclared_function.__module__ = added.__name__

    assert _module_public_names(added) != _declared_public_names()
    assert "a_new_undeclared_function" in _module_public_names(added) - _declared_public_names()


def test_surface_check_catches_a_declared_symbol_dropped_from_the_declaration():
    shrunk_declaration = _declared_public_names() - {"find_yaml_findings"}

    assert _module_public_names(guard) != shrunk_declaration


def test_shape_check_catches_a_finding_producer_returning_bare_strings():
    mutated = _load_module(name="comment_intent_guard_bare_strings_for_test")
    mutated.find_misplaced_rationale = lambda text: ["a bare string finding with no span at all"]

    problems = _shape_problems(mutated.find_misplaced_rationale("irrelevant"))

    assert problems


def test_consumer_message_prefixes_are_still_produced():
    assert _missing_consumer_prefixes(guard) == []


def test_consumer_prefix_check_catches_a_reworded_finding_message():
    reworded = _load_module(name="comment_intent_guard_reworded_message_for_test")
    real_finder = reworded.find_misplaced_rationale
    reworded.find_misplaced_rationale = lambda text: [
        (message.replace("Docstring spans", "Docstring covers"), span)
        for message, span in real_finder(text)
    ]

    missing = _missing_consumer_prefixes(reworded)

    assert missing == [("find_misplaced_rationale", "Docstring spans")]


def test_existence_check_catches_a_declared_function_renamed_on_the_module():
    renamed = _load_module(name="comment_intent_guard_renamed_for_test")
    renamed.find_misplaced_rationale_v2 = renamed.find_misplaced_rationale
    del renamed.find_misplaced_rationale

    missing = _missing_declared_functions(renamed, PUBLIC_FUNCTIONS)

    assert missing == ["find_misplaced_rationale"]

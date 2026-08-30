import ast
import importlib.util
import json
import subprocess
import sys
import tokenize
from pathlib import Path
from unittest.mock import patch

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"


def _run_hook(payload, env=None):
    result = subprocess.run(
        [sys.executable, str(_MODULE_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result


def _load_module():
    spec = importlib.util.spec_from_file_location("comment_intent_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_module()


def test_e2e_write_py_file_with_oversize_docstring_emits_advisory():
    prose_lines = "\n".join(f"    reason {i}" for i in range(13))
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/scripts/thing.py",
            "content": f'"""\n{prose_lines}\n"""\n',
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "docstring" in output["hookSpecificOutput"]["additionalContext"].lower()


def test_e2e_edit_py_file_with_evidence_marker_emits_advisory():
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/repo/scripts/thing.py",
            "old_string": "pass\n",
            "new_string": "# fixed on 2026-05-22 after the incident\npass\n",
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "date" in output["hookSpecificOutput"]["additionalContext"].lower() or \
        "review finding" in output["hookSpecificOutput"]["additionalContext"].lower()


def test_e2e_non_python_file_is_skipped_even_with_oversize_hash_run():
    prose_lines = "\n".join(f"# reason {i}" for i in range(20))
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/docs/design.md",
            "content": prose_lines,
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_e2e_write_yaml_file_with_oversize_hash_run_emits_advisory_never_deny():
    over_threshold_line_count = guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1
    prose_lines = "\n".join(f"# reason {i}" for i in range(over_threshold_line_count))
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/config/jira123_zones.yaml",
            "content": f"{prose_lines}\nkey: value\n",
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert f"Comment run of {over_threshold_line_count}" in output["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in output["hookSpecificOutput"]


def test_e2e_edit_yaml_file_only_analyses_the_new_string_fragment():
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/repo/config/automations.yaml",
            "old_string": (
                "# reason one\n"
                "# reason two\n"
                "# reason three\n"
                "# reason four\n"
                "# reason five\n"
                "old_key: value\n"
            ),
            "new_string": "timeout: 8  # fixed on 2026-05-22 (issue #32)\n",
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "date" in context.lower()
    assert "Comment run of 5" not in context


def test_e2e_malformed_json_fails_open():
    result = subprocess.run(
        [sys.executable, str(_MODULE_PATH)],
        input="not json at all {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_e2e_fail_open_leaves_stdout_empty_and_logs_to_stderr():
    result = subprocess.run(
        [sys.executable, str(_MODULE_PATH)],
        input="not json at all {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert "comment_intent_guard" in result.stderr
    assert "JSONDecodeError" in result.stderr


def test_e2e_clean_python_produces_no_advisory():
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/scripts/thing.py",
            "content": "def add(a, b):\n    return a + b\n",
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_version_guard_raises_analysis_unavailable_below_python_3_12():
    lines = "\n".join(f"    reason {i}" for i in range(13))
    text = f'"""\n{lines}\n"""\n'

    with patch("sys.version_info", (3, 9, 6, "final", 0)):
        with pytest.raises(guard.AnalysisUnavailable, match="3.12"):
            guard.find_misplaced_rationale(text)


def test_oversize_docstring_is_flagged():
    lines = "\n".join(f"    reason {i}" for i in range(13))
    text = f'"""\n{lines}\n"""\n'

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("docstring" in f.lower() for f, _ in findings)


def test_docstring_span_covers_the_full_block_including_the_closing_delimiter():
    body_line_count = guard.DOCSTRING_LINE_THRESHOLD + 1
    prose = "\n".join(f"    reason {i}" for i in range(body_line_count))
    text = f'"""\n{prose}\n"""\n'

    findings = guard.find_misplaced_rationale(text)

    _, span = next(f for f in findings if f[0].startswith("Docstring spans"))
    assert span == (1, body_line_count + 2)


def test_oversize_string_assigned_to_a_variable_is_not_flagged_as_a_docstring():
    lines = "\n".join(f"    reason {i}" for i in range(13))
    text = f'x = """\n{lines}\n"""\n'

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_mid_function_bare_triple_quoted_string_is_flagged_though_not_a_real_ast_docstring():
    prose = "\n".join(f"    reason {i}" for i in range(13))
    text = f'def f():\n    x = 1\n    """\n{prose}\n    """\n'
    assert ast.get_docstring(ast.parse(text).body[0]) is None

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Docstring spans") for f, _ in findings)


@pytest.mark.parametrize(
    "prefix",
    ["r", "R", "b", "f", "u", "rb", "fR"],
    ids=["r", "R-proves-case-insensitive", "b", "f", "u", "rb", "fR-proves-case-insensitive"],
)
@pytest.mark.parametrize("quote", ['"""', "'''"])
def test_prefixed_oversize_docstring_is_flagged(prefix, quote):
    lines = "\n".join(f"    reason {i}" for i in range(13))
    text = f"{prefix}{quote}\n{lines}\n{quote}\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("docstring" in f.lower() for f, _ in findings)


def test_short_docstring_naming_a_test_case_is_not_flagged():
    text = (
        '"""Test SP-3: setpoint clamps to the panel min when the desired\n'
        'value would push the fan below its floor."""\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_short_comment_with_a_date_is_flagged_despite_being_under_threshold():
    text = "# fixed the race condition on 2026-05-22\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("date" in f.lower() or "measurement" in f.lower() or "sha" in f.lower() for f, _ in findings)


def test_short_comment_with_a_measurement_is_flagged():
    text = "# retry took 340ms after the timeout\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings


def test_short_comment_with_a_sha_is_flagged():
    text = "# root-caused in abc1234, see the fix there\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings


def test_short_comment_with_a_plain_number_is_not_flagged_as_a_sha():
    text = "# retries: 1234567, unrelated to any commit\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_trailing_comment_with_a_sha_is_flagged():
    text = "MAX_GAP = 4  # per review of 56305c8ab\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("sha" in f.lower() or "date" in f.lower() or "measurement" in f.lower() for f, _ in findings)


def test_trailing_hash_inside_a_string_literal_is_not_a_comment():
    text = 'label = "value # 2026-05-22 not a comment"\n'

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_english_hex_looking_words_are_not_flagged_as_a_sha():
    text = "# the timeout defaced the deadbeef state and effaced the cache\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_single_letter_unit_requires_no_space_before_it():
    text = "# see step 3 m of the plan for context\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_shebang_and_encoding_lines_do_not_count_toward_a_comment_run():
    reason_lines_under_threshold_alone = guard.COMMENT_RUN_LINE_THRESHOLD - 1
    text = (
        "#!/usr/bin/env python3\n"
        "# -*- coding: utf-8 -*-\n"
        + "\n".join(f"# reason {i}" for i in range(reason_lines_under_threshold_alone))
        + "\n"
    )

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_trailing_comment_on_an_early_code_line_matching_the_encoding_pattern_is_not_swallowed():
    text = "import os  # coding: utf-8, added 2026-05-22\nx = 1\n"

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Comment near line 1") for f, _ in findings)


def test_unparseable_edit_fragment_with_oversize_docstring_is_still_flagged():
    prose_lines = "\n".join(f"        rationale line {i} of the fix" for i in range(40))
    text = (
        "    def _apply_fix(self):\n"
        f'        """\n{prose_lines}\n        """\n'
        "        return self.value\n"
    )

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("docstring" in f.lower() for f, _ in findings)


def test_oversize_docstring_after_a_same_line_docstring_is_still_flagged():
    prose_lines = "\n".join(f"    reason {i}" for i in range(20))
    text = (
        'def a():\n'
        '    """short."""\n'
        "\n"
        "def b():\n"
        f'    """\n{prose_lines}\n    """\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("docstring" in f.lower() for f, _ in findings)


def test_oversize_docstring_after_a_back_to_back_empty_docstring_is_still_flagged():
    prose_lines = "\n".join(f"    reason {i}" for i in range(20))
    text = (
        'def a():\n'
        '    """"""\n'
        "\n"
        "def b():\n"
        f'    """\n{prose_lines}\n    """\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("docstring" in f.lower() for f, _ in findings)


def test_edit_fragment_starting_with_a_bare_closing_delimiter_is_not_flagged():
    code_lines = "\n".join(f"    step_{i}()" for i in range(20))
    text = f'    """\n{code_lines}\n'

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_unterminated_docstring_opener_does_not_fabricate_a_length_finding_or_swallow_a_later_comment():
    code_lines = "\n".join(f"    step_{i}()" for i in range(20))
    text = (
        '    """opens here, never closes in this fragment\n'
        f"{code_lines}\n"
        "    # fixed on 2026-05-22\n"
    )

    findings = guard.find_misplaced_rationale(text)

    assert not any(f.startswith("Docstring spans") for f, _ in findings)
    assert any("Comment near line 22" in f for f, _ in findings)


def test_unterminated_fstring_docstring_does_not_swallow_a_later_comment():
    text = 'f"""opens here, never closes\nsome code\nmore code\n# fixed on 2026-05-22\n'

    findings = guard.find_misplaced_rationale(text)

    assert not any(f.startswith("Docstring") for f, _ in findings)
    assert any(f.startswith("Comment near line 4") for f, _ in findings)


def _opens_and_closes_on_separate_lines(prefix, body_line):
    return f'{prefix}"""\n    {body_line}\n    """'


def test_prefixed_docstring_does_not_desync_a_later_plain_oversize_docstring():
    prose = "\n".join(f"    reason {i}" for i in range(20))
    short_block = _opens_and_closes_on_separate_lines("r", "short prefixed docstring")
    text = (
        "def a():\n"
        f"    {short_block}\n"
        "\n"
        "def b():\n"
        f'    """\n{prose}\n    """\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Docstring spans") and "near line 7" in f for f, _ in findings)


def test_oversize_fstring_docstring_with_an_embedded_delimiter_in_an_interpolation_still_fires():
    text = (
        "def f():\n"
        '    f"""\n'
        "    reason 0\n"
        "    reason 1\n"
        "    reason 2\n"
        "    reason 3\n"
        "    reason 4\n"
        "    reason 5\n"
        "    reason 6\n"
        "    reason 7\n"
        "    {'\"\"\"'}\n"
        "    reason 8\n"
        "    reason 9\n"
        "    reason 10\n"
        '    """\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert any(
        f.startswith("Docstring spans 14 lines") and "near line 2" in f for f, _ in findings
    )


def test_oversize_fstring_docstring_with_a_genuinely_nested_fstring_interpolation_still_fires():
    text = (
        "def f():\n"
        '    f"""\n'
        "    reason 0\n"
        "    reason 1\n"
        "    reason 2\n"
        "    reason 3\n"
        "    reason 4\n"
        "    reason 5\n"
        "    reason 6\n"
        "    reason 7\n"
        "    {f'{1}'}\n"
        "    reason 8\n"
        "    reason 9\n"
        "    reason 10\n"
        '    """\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert any(
        f.startswith("Docstring spans 14 lines") and "near line 2" in f for f, _ in findings
    )


def test_lone_carriage_returns_do_not_desync_token_rows_from_source_rows():
    prose = "\n".join(f"reason {i}" for i in range(13))
    text = "a = 1\rb = 2\rc = 3\r\n" + f'"""\n{prose}\n"""\n'

    findings = guard.find_misplaced_rationale(text)

    assert any(
        f.startswith("Docstring spans 15 lines") and "near line 2" in f for f, _ in findings
    )


def test_oversize_docstring_as_the_literal_first_token_after_a_resync_is_flagged():
    prose = "\n".join(f"    reason {i}" for i in range(13))
    text = f"x = 'unterminated\n\"\"\"\n{prose}\n\"\"\"\n"

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Docstring spans") and "near line 2" in f for f, _ in findings)


def test_oversize_assignment_string_after_a_resync_is_not_flagged():
    prose = "\n".join(f"    reason {i}" for i in range(13))
    text = f"x = 'unterminated\ny = \"\"\"\n{prose}\n\"\"\"\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_docstring_after_two_resyncs_is_flagged_at_the_right_line():
    prose = "\n".join(f"    reason {i}" for i in range(20))
    text = f"x = 'unterminated\ny = 'also unterminated\ndef f():\n    \"\"\"\n{prose}\n    \"\"\"\n"

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Docstring spans") and "near line 4" in f for f, _ in findings)


def test_resync_offsets_accumulate_correctly_across_two_unterminated_strings():
    run1 = "\n".join(f"# reason {i}" for i in range(5))
    run2 = "\n".join(f"# reason {i}" for i in range(5, 10))
    text = f"x = 'unterminated\n{run1}\ny = 'unterminated\n{run2}\n"

    findings = guard.find_misplaced_rationale(text)

    assert any("starting near line 2" in f for f, _ in findings)
    assert any("starting near line 8" in f for f, _ in findings)


def test_resync_gap_flushes_the_comment_run_so_two_short_runs_dont_merge_into_a_false_positive():
    text = "# note one\n# note two\n'oops cut here\n# note three\n# note four\n# note five\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings == []


def test_resync_gap_flushes_the_comment_run_so_a_real_finding_keeps_its_own_start_line():
    text = (
        "# note one\n"
        "# note two\n"
        "'oops cut here\n"
        "# note three\n"
        "# note four\n"
        "# note five\n"
        "# note six\n"
        "# note seven\n"
    )

    findings = guard.find_misplaced_rationale(text)

    assert any("starting near line 4" in f for f, _ in findings)
    assert not any("starting near line 1" in f for f, _ in findings)


def test_resync_is_bounded_and_degrades_past_the_cap():
    blocks = "".join(
        f"bad_{i} = 'unterminated\n# reason {i}, added 2026-05-22\n" for i in range(70)
    )
    text = blocks + "# fixed on 2026-05-22\n"

    with patch.object(guard, "_MAX_RESYNC_PASSES", 5):
        low_cap_findings = guard.find_misplaced_rationale(text)
    with patch.object(guard, "_MAX_RESYNC_PASSES", 500):
        high_cap_findings = guard.find_misplaced_rationale(text)

    assert len(low_cap_findings) == 5
    assert len(high_cap_findings) == 70


def test_resync_fails_open_on_a_malformed_tokenizer_error_shape():
    with patch(
        "tokenize.generate_tokens",
        side_effect=tokenize.TokenError("no position info here"),
    ):
        findings = guard.find_misplaced_rationale("x = 1\n")

    assert findings == []


def test_dangling_open_bracket_fails_open_without_crashing():
    text = "foo(\n# reason for the open paren, added 2026-05-22\nbar,\nbaz,\n"

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Comment near line 2") for f, _ in findings)


def test_oversize_docstring_after_a_dangling_open_bracket_is_still_flagged():
    prose = "\n".join(f"    reason {i}" for i in range(20))
    text = (
        "foo(\n"
        "bar,\n"
        "baz,\n"
        "def b():\n"
        f'    """\n{prose}\n    """\n'
    )

    findings = guard.find_misplaced_rationale(text)

    assert any(f.startswith("Docstring spans") and "near line 5" in f for f, _ in findings)


def test_e2e_dangling_open_bracket_produces_no_crash_and_no_traceback_on_stdout():
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/scripts/thing.py",
            "content": "foo(\nbar,\nbaz,\n",
        },
    }

    result = _run_hook(payload)

    assert result.returncode == 0
    assert "Traceback" not in result.stdout


@pytest.mark.parametrize("exc, num_lines", [
    (tokenize.TokenError("no args"), 10),
    (tokenize.TokenError("bad pos", ("not", "a", "tuple")), 10),
    (tokenize.TokenError("non-int row", (1.5, 2)), 10),
    (tokenize.TokenError("row zero", (0, 5)), 10),
    (tokenize.TokenError("row past eof", (999, 5)), 10),
])
def test_trustworthy_row_returns_none_for_a_malformed_or_out_of_range_shape(exc, num_lines):
    assert guard._trustworthy_row(exc, num_lines) is None


def test_trustworthy_row_reads_lineno_for_syntax_errors():
    exc = SyntaxError("bad indent")
    exc.lineno = 3

    assert guard._trustworthy_row(exc, 10) == 3


def test_oversize_leading_module_docstring_is_flagged_no_exemption():
    prose_lines = "\n".join(f"reason {i} for this fixture existing" for i in range(20))
    text = f'"""\n{prose_lines}\n"""\nimport pytest\n\n\ndef fixture():\n    pass\n'

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("docstring" in f.lower() for f, _ in findings)


def test_oversize_comment_run_is_flagged():
    text = "\n".join(f"# reason line {i}" for i in range(5)) + "\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("comment" in f.lower() for f, _ in findings)


def test_rename_phrasing_only_appears_for_comment_runs_not_docstrings():
    comment_text = "\n".join(f"# reason line {i}" for i in range(5)) + "\n"
    docstring_lines = "\n".join(f"reason {i}" for i in range(13))
    docstring_text = f'"""\n{docstring_lines}\n"""\n'

    comment_findings = guard.find_misplaced_rationale(comment_text)
    docstring_findings = guard.find_misplaced_rationale(docstring_text)

    assert any("rename" in f.lower() for f, _ in comment_findings)
    assert not any("rename" in f.lower() for f, _ in docstring_findings)


def test_comment_run_with_a_paragraph_break_is_still_flagged():
    text = (
        "# reason line 0\n"
        "# reason line 1\n"
        "\n"
        "# reason line 2\n"
        "# reason line 3\n"
        "# reason line 4\n"
    )

    findings = guard.find_misplaced_rationale(text)

    assert findings
    assert any("comment" in f.lower() for f, _ in findings)


def test_comment_run_span_covers_a_paragraph_break_not_just_the_hash_lines():
    text = (
        "# reason line 0\n"
        "# reason line 1\n"
        "\n"
        "# reason line 2\n"
        "# reason line 3\n"
        "# reason line 4\n"
        "x = 1\n"
    )

    findings = guard.find_misplaced_rationale(text)

    _, span = next(f for f in findings if f[0].startswith("Comment run"))
    assert span == (1, 6)


def test_comment_run_message_does_not_claim_the_lines_are_consecutive_across_a_paragraph_break():
    text = (
        "# reason line 0\n"
        "# reason line 1\n"
        "\n"
        "# reason line 2\n"
        "# reason line 3\n"
        "# reason line 4\n"
        "x = 1\n"
    )

    findings = guard.find_misplaced_rationale(text)

    message, _ = next(f for f in findings if f[0].startswith("Comment run"))
    assert "consecutive" not in message


def test_short_comment_run_is_not_flagged():
    text = "\n".join(f"# reason line {i}" for i in range(4)) + "\n"

    findings = guard.find_misplaced_rationale(text)

    assert findings == []



def test_docstring_on_a_test_function_is_a_blocking_violation():
    source = 'def test_thing():\n    """Checks the thing."""\n    assert True\n'

    assert guard.find_blocking_violations(source, "/repo/tests/test_thing.py")


def test_e2e_test_docstring_denies_the_edit():
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/tests/test_thing.py",
            "content": 'def test_thing():\n    """Checks the thing."""\n    assert True\n',
        },
    }

    result = _run_hook(payload)

    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "test name" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_docstring_on_a_non_test_function_is_not_a_blocking_violation():
    source = 'def parse_rows(raw):\n    """Rows in file order; raises on a short header."""\n    return raw\n'

    assert guard.find_blocking_violations(source, "/repo/src/parse.py") == []


def test_external_id_in_a_module_docstring_is_a_blocking_violation():
    source = '"""MG-1 golden case (docs/golden-cases.md)."""\nVALUE = 1\n'

    violations = guard.find_blocking_violations(source, "/repo/tests/test_gap.py")

    assert any("MG-1" in v for v, _ in violations)


@pytest.mark.parametrize("standard", ["UTF-8", "SHA-256", "AES-256", "IPV-6"])
def test_standards_identifier_in_a_docstring_is_not_an_external_id(standard):
    source = f'"""Decodes the payload as {standard} before parsing."""\nVALUE = 1\n'

    assert guard.find_blocking_violations(source, "/repo/src/decode.py") == []


def test_external_id_in_a_test_function_name_is_a_blocking_violation():
    source = 'async def test_mg1_cool_demand_in_heat_season(hass):\n    assert True\n'

    violations = guard.find_blocking_violations(source, "/repo/tests/test_gap.py")

    assert any("mg1" in v for v, _ in violations)


def test_external_id_in_the_filename_is_a_blocking_violation():
    source = "VALUE = 1\n"

    violations = guard.find_blocking_violations(
        source, "/repo/tests/templates/test_desired_panel_setpoint_sp6.py"
    )

    assert any("sp6" in v for v, _ in violations)


def test_standards_token_in_the_filename_is_not_an_external_id():
    assert guard.find_blocking_violations("VALUE = 1\n", "/repo/tests/test_sha256_digest.py") == []


def test_external_id_inside_a_plain_string_literal_is_not_a_blocking_violation():
    source = 'CASE_LABEL = "MG-1 golden case"\n'

    assert guard.find_blocking_violations(source, "/repo/src/labels.py") == []


def test_external_id_in_a_triple_quoted_assigned_string_is_not_a_blocking_violation():
    source = 'CASE_LABEL = """MG-1 golden case"""\n'

    assert guard.find_blocking_violations(source, "/repo/src/labels.py") == []


def test_comment_beside_a_magic_literal_is_flagged_as_advisory():
    source = "TIMEOUT = 300  # five minutes\n"

    findings = guard.find_misplaced_rationale(source)

    assert any("named constant" in f for f, _ in findings)


def test_magic_literal_span_is_the_single_line_it_sits_on():
    source = "TIMEOUT = 300  # five minutes\n"

    findings = guard.find_misplaced_rationale(source)

    _, span = next(f for f in findings if "named constant" in f[0])
    assert span == (1, 1)


def test_comment_beside_a_subscript_index_is_not_flagged_as_a_magic_literal():
    source = "def _reported_row(exc):\n    return exc.args[1][0]  # TokenError: row is positional in .args\n"

    findings = guard.find_misplaced_rationale(source)

    assert not any("named constant" in f for f, _ in findings)


def test_comment_and_code_lines_are_counted_separately():
    source = "# leading note\nVALUE = 1  # trailing note\n\nOTHER = 2\n"

    assert guard.count_comment_and_code_lines(source) == (2, 2)


def test_aggregate_density_above_the_peer_baseline_is_flagged():
    finding = guard.aggregate_density_finding(comment_lines=30, code_lines=100)

    assert finding is not None
    assert "18" in finding


def test_aggregate_density_at_the_peer_baseline_is_not_flagged():
    assert guard.aggregate_density_finding(comment_lines=10, code_lines=100) is None


def test_aggregate_density_is_not_flagged_before_the_sample_is_large_enough():
    assert guard.aggregate_density_finding(comment_lines=3, code_lines=4) is None


def test_recorded_edits_accumulate_across_invocations(tmp_path):
    state = tmp_path / "state.json"

    guard.record_edit(state, "session-a", comment_lines=2, code_lines=10)
    totals = guard.record_edit(state, "session-a", comment_lines=3, code_lines=20)

    assert totals == (5, 30)


def test_recorded_edits_are_scoped_per_session(tmp_path):
    state = tmp_path / "state.json"

    guard.record_edit(state, "session-a", comment_lines=9, code_lines=9)
    totals = guard.record_edit(state, "session-b", comment_lines=1, code_lines=4)

    assert totals == (1, 4)


def test_a_corrupt_state_file_starts_fresh_and_warns(tmp_path, capsys):
    state = tmp_path / "state.json"
    state.write_text("{not json")

    totals = guard.record_edit(state, "session-a", comment_lines=1, code_lines=2)

    assert totals == (1, 2)
    assert "comment_intent_guard" in capsys.readouterr().err


def _dense_python(code_lines):
    return "".join(f"# note {i}\nVALUE_{i} = {i + 2}\n" for i in range(code_lines))


def test_e2e_aggregate_density_advisory_fires_once_the_session_total_drifts(tmp_path):
    import os as _os
    env = dict(_os.environ, COMMENT_INTENT_GUARD_STATE=str(tmp_path / "state.json"))
    payload = {
        "session_id": "session-a",
        "tool_name": "Write",
        "tool_input": {"file_path": "/repo/src/thing.py", "content": _dense_python(30)},
    }

    _run_hook(payload, env=env)
    result = _run_hook(payload, env=env)

    output = json.loads(result.stdout)
    assert "Aggregate comment density" in output["hookSpecificOutput"]["additionalContext"]


def test_state_keeps_only_the_most_recent_sessions(tmp_path):
    state = tmp_path / "state.json"

    for n in range(guard.MAX_TRACKED_SESSIONS + 5):
        guard.record_edit(state, f"session-{n}", comment_lines=1, code_lines=1)

    kept = json.loads(state.read_text())
    assert len(kept) == guard.MAX_TRACKED_SESSIONS
    assert "session-0" not in kept
    assert f"session-{guard.MAX_TRACKED_SESSIONS + 4}" in kept


def test_a_returning_session_is_not_evicted_by_newer_ones(tmp_path):
    state = tmp_path / "state.json"
    guard.record_edit(state, "long-runner", comment_lines=1, code_lines=1)

    for n in range(guard.MAX_TRACKED_SESSIONS - 1):
        guard.record_edit(state, f"other-{n}", comment_lines=1, code_lines=1)
        guard.record_edit(state, "long-runner", comment_lines=0, code_lines=1)

    assert "long-runner" in json.loads(state.read_text())


def test_test_function_docstrings_are_counted_across_a_module():
    source = (
        'def test_one():\n    """prose"""\n    assert True\n\n\n'
        'def test_two():\n    assert True\n\n\n'
        'def helper():\n    """contract"""\n    return 1\n\n\n'
        'def test_three():\n    """more prose"""\n    assert True\n'
    )

    assert guard.count_test_function_docstrings(source) == 2


def test_yaml_five_line_hash_run_is_flagged():
    text = (
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert any("Comment run of 5" in f for f, _ in findings)


def test_yaml_trailing_comment_with_evidence_marker_is_flagged():
    text = "timeout: 8  # fixed on 2026-05-22 (issue #32)\n"

    findings = guard.find_yaml_findings(text)

    assert any("date" in f.lower() for f, _ in findings)


def test_yaml_hash_immediately_after_a_digit_is_a_literal_scalar_not_a_comment():
    text = "val: 100#fixed on 2026-05-22\n"

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_hash_inside_a_quoted_string_is_inert_even_after_whitespace():
    text = 'title: "Status # 5 update on 2026-05-22"\n'

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_hash_inside_a_block_scalar_is_inert_regardless_of_whitespace():
    text = (
        "description: >-\n"
        "  #100 first line\n"
        "  #101 second line\n"
        "  #102 third line\n"
        "  #103 fourth line\n"
        "  #104 fifth line\n"
        "next_key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_jinja_comment_block_over_8_lines_is_flagged():
    body_line_count = guard.JINJA_BLOCK_LINE_THRESHOLD + 1
    body_lines = "\n".join(f"  reason {i}" for i in range(body_line_count))
    text = f"value_template: >-\n  {{#\n{body_lines}\n  #}}\n"

    findings = guard.find_yaml_findings(text)

    assert any("Jinja" in f and "block" in f for f, _ in findings)


def test_yaml_jinja_block_span_covers_the_opening_and_closing_markers():
    body_line_count = guard.JINJA_BLOCK_LINE_THRESHOLD + 1
    body_lines = "\n".join(f"  reason {i}" for i in range(body_line_count))
    text = f"value_template: >-\n  {{#\n{body_lines}\n  #}}\n"

    findings = guard.find_yaml_findings(text)

    _, span = next(f for f in findings if "Jinja" in f[0] and "block" in f[0])
    assert span == (2, body_line_count + 3)


def test_yaml_jinja_comment_block_of_8_lines_or_fewer_is_not_flagged():
    body_line_count = guard.JINJA_BLOCK_LINE_THRESHOLD - 2
    body_lines = "\n".join(f"  reason {i}" for i in range(body_line_count))
    text = f"value_template: >-\n  {{#\n{body_lines}\n  #}}\n"

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_two_separate_jinja_blocks_dont_swallow_a_real_comment_run_between_them():
    text = (
        "{# first block #}\n"
        "normal_key: value\n"
        "# real comment one\n"
        "# real comment two\n"
        "# real comment three\n"
        "# real comment four\n"
        "# real comment five\n"
        "other_key: value\n"
        "{# second block #}\n"
    )

    findings = guard.find_yaml_findings(text)

    assert any("Comment run of 5" in f for f, _ in findings)
    assert not any("Jinja" in f for f, _ in findings)


def test_yaml_jinja_block_sharing_a_line_with_real_content_does_not_extend_a_comment_run():
    text = (
        "value: {{ x }} {# note #}\n"
        "# real comment one\n"
        "# real comment two\n"
        "# real comment three\n"
        "# real comment four\n"
    )

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_description_block_over_12_lines_is_flagged():
    over_threshold_line_count = guard.YAML_DESCRIPTION_LINE_THRESHOLD + 1
    prose_lines = "\n".join(f"  reason {i}" for i in range(over_threshold_line_count))
    text = f"description: >-\n{prose_lines}\nnext_key: value\n"

    findings = guard.find_yaml_findings(text)

    assert any("Description" in f and str(over_threshold_line_count) in f for f, _ in findings)


def test_yaml_description_block_span_includes_the_header_line():
    over_threshold_line_count = guard.YAML_DESCRIPTION_LINE_THRESHOLD + 1
    prose_lines = "\n".join(f"  reason {i}" for i in range(over_threshold_line_count))
    text = f"description: >-\n{prose_lines}\nnext_key: value\n"

    findings = guard.find_yaml_findings(text)

    _, span = next(f for f in findings if "Description" in f[0])
    assert span == (1, over_threshold_line_count + 1)


def test_yaml_description_block_message_points_at_the_header_line():
    over_threshold_line_count = guard.YAML_DESCRIPTION_LINE_THRESHOLD + 1
    prose_lines = "\n".join(f"  reason {i}" for i in range(over_threshold_line_count))
    text = f"description: >-\n{prose_lines}\nnext_key: value\n"

    findings = guard.find_yaml_findings(text)

    message, _ = next(f for f in findings if "Description" in f[0])
    assert "starting near line 1." in message


def test_yaml_description_block_of_12_lines_or_fewer_is_not_flagged():
    prose_lines = "\n".join(f"  reason {i}" for i in range(guard.YAML_DESCRIPTION_LINE_THRESHOLD))
    text = f"description: >-\n{prose_lines}\nnext_key: value\n"

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_short_description_block_with_an_evidence_marker_is_flagged():
    text = "description: >-\n  fixed on 2026-05-22 after the incident\nnext_key: value\n"

    findings = guard.find_yaml_findings(text)

    assert any("Description" in f and "date" in f.lower() for f, _ in findings)


def test_yaml_long_commented_out_config_run_gets_the_dead_config_message():
    text = (
        "# sensor:\n"
        "#   - platform: template\n"
        "#     sensors:\n"
        "#       old_pool_temp:\n"
        '#         value_template: "{{ states(\'sensor.pool_raw\') }}"\n'
        "key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert any("dead config" in f.lower() for f, _ in findings)
    assert not any("design doc" in f for f, _ in findings)


def test_yaml_dead_config_message_does_not_claim_the_lines_are_consecutive():
    text = (
        "# sensor:\n"
        "#   - platform: template\n"
        "#     sensors:\n"
        "#       old_pool_temp:\n"
        '#         value_template: "{{ states(\'sensor.pool_raw\') }}"\n'
        "key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    message = next(f for f, _ in findings if "dead config" in f.lower())
    assert "consecutive" not in message


def test_yaml_comment_run_message_does_not_claim_the_lines_are_consecutive():
    prose_lines = "\n".join(f"# reason {i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1))
    text = f"{prose_lines}\nkey: value\n"

    findings = guard.find_yaml_findings(text)

    message = next(f for f, _ in findings if f.startswith("Comment run"))
    assert "consecutive" not in message


def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(_MODULE_PATH), *args],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
    )


def test_cli_all_mode_on_yaml_file_reports_findings_and_exits_nonzero(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "key: value\n"
    )

    result = _run_cli(["--all", str(yaml_file)])

    assert result.returncode == 1
    assert "Comment run of 5" in result.stdout


def test_cli_all_mode_with_no_findings_exits_zero(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("key: value\n")

    result = _run_cli(["--all", str(yaml_file)])

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_cli_all_mode_on_python_file_routes_to_the_python_analyser(tmp_path):
    py_file = tmp_path / "thing.py"
    lines = "\n".join(f"    reason {i}" for i in range(13))
    py_file.write_text(f'"""\n{lines}\n"""\n')

    result = _run_cli(["--all", str(py_file)])

    assert result.returncode == 1
    assert "docstring" in result.stdout.lower()


def _init_git_repo(repo_dir):
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo_dir, check=True)


def test_cli_base_mode_excludes_findings_on_preexisting_lines(tmp_path):
    _init_git_repo(tmp_path)
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "# old reason one\n"
        "# old reason two\n"
        "# old reason three\n"
        "# old reason four\n"
        "# old reason five\n"
        "old_key: value\n"
    )
    subprocess.run(["git", "add", "config.yaml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    yaml_file.write_text(
        "# old reason one\n"
        "# old reason two\n"
        "# old reason three\n"
        "# old reason four\n"
        "# old reason five\n"
        "old_key: value\n"
        "# new reason one\n"
        "# new reason two\n"
        "# new reason three\n"
        "# new reason four\n"
        "# new reason five\n"
        "new_key: value\n"
    )

    base_result = _run_cli(["--base", base_sha, "config.yaml"], cwd=tmp_path)
    all_result = _run_cli(["--all", "config.yaml"], cwd=tmp_path)

    assert "starting near line 7." in base_result.stdout
    assert "starting near line 1." not in base_result.stdout

    assert "starting near line 1." in all_result.stdout
    assert "starting near line 7." in all_result.stdout


def test_yaml_whole_line_comment_with_evidence_marker_is_flagged_below_run_threshold():
    text = "# fixed on 2026-05-22 after the incident\nkey: value\n"

    findings = guard.find_yaml_findings(text)

    assert any("date" in f.lower() for f, _ in findings)


def test_yaml_block_scalar_with_an_explicit_indentation_indicator_is_still_inert():
    text = (
        "description: |2\n"
        "  #100 first line\n"
        "  #101 second line\n"
        "  #102 third line\n"
        "  #103 fourth line\n"
        "  #104 fifth line\n"
        "next_key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_block_scalar_with_a_hyphenated_key_is_still_inert():
    text = (
        "friendly-name: >-\n"
        "  #100 first line\n"
        "  #101 second line\n"
        "  #102 third line\n"
        "  #103 fourth line\n"
        "  #104 fifth line\n"
        "next_key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_block_scalar_with_a_quoted_key_is_still_inert():
    text = (
        '"description": >-\n'
        "  #100 first line\n"
        "  #101 second line\n"
        "  #102 third line\n"
        "  #103 fourth line\n"
        "  #104 fifth line\n"
        "next_key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_block_scalar_with_a_quoted_description_key_still_gets_length_checked():
    over_threshold_line_count = guard.YAML_DESCRIPTION_LINE_THRESHOLD + 1
    prose_lines = "\n".join(f"  reason {i}" for i in range(over_threshold_line_count))
    text = f'"description": >-\n{prose_lines}\nnext_key: value\n'

    findings = guard.find_yaml_findings(text)

    assert any("Description" in f and str(over_threshold_line_count) in f for f, _ in findings)


def test_yaml_sequence_item_block_scalar_uses_the_keys_indent_not_the_dashes():
    text = (
        "- description: >-\n"
        "    reason 0\n"
        "    reason 1\n"
        "  # comment one\n"
        "  # comment two\n"
        "  # comment three\n"
        "  # comment four\n"
        "  # comment five\n"
    )

    findings = guard.find_yaml_findings(text)

    assert any("Comment run of 5" in f for f, _ in findings)


def test_yaml_escaped_double_quote_does_not_prematurely_close_the_string():
    text = 'a: "he said \\" # still in string on 2026-05-22"\n'

    findings = guard.find_yaml_findings(text)

    assert findings == []


def test_yaml_apostrophe_in_a_plain_scalar_does_not_suppress_a_trailing_comment():
    text = "name: the neighbour's house  # fixed on 2026-05-22\n"

    findings = guard.find_yaml_findings(text)

    assert any("date" in f.lower() for f, _ in findings)


def test_yaml_explanatory_prose_run_is_not_misclassified_as_dead_config():
    text = (
        "# Why: the sensor kept dropping readings during storms\n"
        "# Cause: the ESP32 brownouts under RF interference near the pump\n"
        "# Fix: added a decoupling capacitor across the 3.3V rail\n"
        "# Verified: stable for two weeks after the fix\n"
        "# Related: see also the pump controller firmware notes\n"
        "key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert not any("dead config" in f.lower() for f, _ in findings)
    assert any("design doc" in f for f, _ in findings)


def test_yaml_dead_config_run_does_not_also_get_a_design_doc_evidence_finding():
    text = (
        "# sensor:\n"
        "#   - platform: template\n"
        "#     sensors:\n"
        "#       old_pool_temp:  # removed 2026-05-22\n"
        '#         value_template: "{{ states(\'sensor.pool_raw\') }}"\n'
        "key: value\n"
    )

    findings = guard.find_yaml_findings(text)

    assert any("dead config" in f.lower() for f, _ in findings)
    assert not any("move it to the issue" in f for f, _ in findings)


def test_cli_all_mode_skips_a_non_utf8_file_and_keeps_processing_others(tmp_path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_bytes(b"key: \xff\xfe not valid utf-8\n")
    good_file = tmp_path / "config.yaml"
    good_file.write_text(
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "key: value\n"
    )

    result = _run_cli(["--all", str(bad_file), str(good_file)])

    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr
    assert "Comment run of 5" in result.stdout
    assert "bad.yaml" in result.stderr
    assert result.returncode == 4


def test_cli_exits_4_when_the_only_file_cannot_be_read(tmp_path):
    missing_file = tmp_path / "does_not_exist.yaml"

    result = _run_cli(["--all", str(missing_file)])

    assert result.returncode == 4


def test_added_line_numbers_warns_and_returns_none_when_git_is_not_on_path(capsys):
    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        result = guard._added_line_numbers("HEAD", "some.yaml")

    assert result is None
    assert "comment_intent_guard" in capsys.readouterr().err


def test_cli_base_mode_on_an_untracked_file_treats_everything_as_added(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "placeholder.txt").write_text("x\n")
    subprocess.run(["git", "add", "placeholder.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    yaml_file = tmp_path / "new_config.yaml"
    yaml_file.write_text(
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "key: value\n"
    )

    result = _run_cli(["--base", base_sha, "new_config.yaml"], cwd=tmp_path)

    assert "Comment run of 5" in result.stdout


def test_cli_base_mode_anchors_git_to_the_files_own_repo_not_the_caller_cwd(tmp_path):
    caller_cwd = tmp_path / "unrelated_caller_repo"
    caller_cwd.mkdir()
    _init_git_repo(caller_cwd)
    (caller_cwd / "placeholder.txt").write_text("x\n")
    subprocess.run(["git", "add", "placeholder.txt"], cwd=caller_cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "unrelated"], cwd=caller_cwd, check=True)

    file_repo = tmp_path / "the_files_own_repo"
    file_repo.mkdir()
    _init_git_repo(file_repo)
    yaml_file = file_repo / "config.yaml"
    yaml_file.write_text(
        "# old reason one\n"
        "# old reason two\n"
        "# old reason three\n"
        "# old reason four\n"
        "# old reason five\n"
        "old_key: value\n"
    )
    subprocess.run(["git", "add", "config.yaml"], cwd=file_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=file_repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=file_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    yaml_file.write_text(
        "# old reason one\n"
        "# old reason two\n"
        "# old reason three\n"
        "# old reason four\n"
        "# old reason five\n"
        "old_key: value\n"
        "# new reason one\n"
        "# new reason two\n"
        "# new reason three\n"
        "# new reason four\n"
        "# new reason five\n"
        "new_key: value\n"
    )

    result = _run_cli(["--base", base_sha, str(yaml_file)], cwd=caller_cwd)

    assert "starting near line 7." in result.stdout
    assert "starting near line 1." not in result.stdout


def test_cli_base_mode_reports_a_comment_run_that_grew_past_threshold_via_appended_lines(tmp_path):
    _init_git_repo(tmp_path)
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "# reason one\n"
        "# reason two\n"
        "# reason three\n"
        "key: value\n"
    )
    subprocess.run(["git", "add", "config.yaml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    yaml_file.write_text(
        "# reason one\n"
        "# reason two\n"
        "# reason three\n"
        "# reason four\n"
        "# reason five\n"
        "# reason six\n"
        "key: value\n"
    )

    result = _run_cli(["--base", base_sha, "config.yaml"], cwd=tmp_path)

    assert "Comment run of 6" in result.stdout


def test_cli_base_mode_reports_a_python_comment_run_with_a_blank_line_and_an_appended_marker(tmp_path):
    _init_git_repo(tmp_path)
    py_file = tmp_path / "thing.py"
    py_file.write_text(
        "# alpha\n"
        "# bravo\n"
        "\n"
        "# charlie\n"
        "# delta\n"
        "x = 1\n"
    )
    subprocess.run(["git", "add", "thing.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    py_file.write_text(
        "# alpha\n"
        "# bravo\n"
        "\n"
        "# charlie\n"
        "# delta\n"
        "# fixed on 2026-05-22\n"
        "x = 1\n"
    )

    result = _run_cli(["--base", base_sha, "thing.py"], cwd=tmp_path)

    assert "Comment run of 5" in result.stdout
    assert "date" in result.stdout.lower()


def test_cli_base_mode_reports_an_evidence_marker_appended_to_the_tail_of_a_preexisting_run(tmp_path):
    _init_git_repo(tmp_path)
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "# reason one\n"
        "# reason two\n"
        "key: value\n"
    )
    subprocess.run(["git", "add", "config.yaml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    yaml_file.write_text(
        "# reason one\n"
        "# reason two\n"
        "# confirmed on 2026-05-22\n"
        "key: value\n"
    )

    result = _run_cli(["--base", base_sha, "config.yaml"], cwd=tmp_path)

    assert "date" in result.stdout.lower()


def test_cli_base_mode_never_filters_a_bright_line_filename_violation(tmp_path):
    _init_git_repo(tmp_path)
    py_file = tmp_path / "jira123_fix.py"
    py_file.write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "jira123_fix.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    py_file.write_text("VALUE = 1\nOTHER = 2\n")

    result = _run_cli(["--base", base_sha, "jira123_fix.py"], cwd=tmp_path)

    assert "jira123" in result.stdout


def test_cli_exits_3_when_a_bright_line_violation_is_present(tmp_path):
    py_file = tmp_path / "jira123_fix.py"
    py_file.write_text("VALUE = 1\n")

    result = _run_cli(["--all", str(py_file)])

    assert result.returncode == 3


def test_cli_exits_1_when_only_advisory_findings_are_present(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "key: value\n"
    )

    result = _run_cli(["--all", str(yaml_file)])

    assert result.returncode == 1


def test_cli_exits_0_when_no_findings_are_present(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("key: value\n")

    result = _run_cli(["--all", str(yaml_file)])

    assert result.returncode == 0


def test_cli_exits_4_when_running_under_a_pre_3_12_interpreter(tmp_path, capsys):
    py_file = tmp_path / "config.py"
    py_file.write_text("VALUE = 1\n")

    with patch("sys.version_info", (3, 9, 6, "final", 0)):
        returncode = guard._cli_main(["--all", str(py_file)])

    assert returncode == 4
    assert "3.12" in capsys.readouterr().err


def test_cli_still_reports_a_bright_line_violation_when_analysis_is_unavailable(tmp_path, capsys):
    py_file = tmp_path / "jira123_fix.py"
    py_file.write_text("VALUE = 1\n")

    with patch("sys.version_info", (3, 9, 6, "final", 0)):
        returncode = guard._cli_main(["--all", str(py_file)])

    assert "jira123" in capsys.readouterr().out
    assert returncode == 4


def test_cli_exits_4_on_an_unanticipated_internal_error(tmp_path, capsys):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("key: value\n")

    with patch.object(guard, "_findings_for_file", side_effect=RuntimeError("boom")):
        returncode = guard._cli_main(["--all", str(yaml_file)])

    assert returncode == 4
    assert "comment_intent_guard" in capsys.readouterr().err


def test_yaml_hash_after_jinja_inside_a_block_scalar_stays_inert_and_a_real_jinja_block_still_fires():
    jinja_block_body = "\n".join(f"reason {i}" for i in range(guard.JINJA_BLOCK_LINE_THRESHOLD + 1))
    text = (
        "value_template: >-\n"
        "  # 100 {{ states('sensor.x') }}\n"
        "  # 101 second line\n"
        "  # 102 third line\n"
        "  # 103 fourth line\n"
        "  # 104 fifth line\n"
        "next_key: value\n"
        f"{{#\n{jinja_block_body}\n#}}\n"
    )

    findings = guard.find_yaml_findings(text)

    assert not any("Comment run" in f for f, _ in findings)
    assert any("Jinja" in f and "block" in f for f, _ in findings)


def _assert_finding_shape(finding, line_count):
    message, span = finding
    assert isinstance(message, str)
    start, end = span
    assert isinstance(start, int) and isinstance(end, int)
    assert 1 <= start <= end <= line_count


def test_every_python_finding_is_a_message_and_a_valid_line_span():
    prose_lines = "\n".join(f"    reason {i}" for i in range(guard.DOCSTRING_LINE_THRESHOLD))
    comment_lines = "\n".join(f"# reason {i}" for i in range(guard.COMMENT_RUN_LINE_THRESHOLD + 1))
    text = (
        f'"""\n{prose_lines}\n    confirmed on 2026-05-22\n"""\n'
        f"{comment_lines}\n"
        "# runtime measured at 5min\n"
        "TIMEOUT = 300  # five minutes\n"
    )
    line_count = len(guard._split_rows(text))

    findings = guard.find_misplaced_rationale(text)

    assert len(findings) == 5
    for finding in findings:
        _assert_finding_shape(finding, line_count)

    blocking_text = (
        '"""Contains JIRA-123 reference."""\n'
        "\n"
        "def test_sp7_thing():\n"
        '    """explains the test"""\n'
        "    pass\n"
    )
    blocking_line_count = len(guard._split_rows(blocking_text))

    blocking_findings = guard.find_blocking_violations(blocking_text, "sp6_fix.py")

    assert len(blocking_findings) == 4
    for finding in blocking_findings:
        _assert_finding_shape(finding, blocking_line_count)


def test_every_yaml_finding_is_a_message_and_a_valid_line_span():
    jinja_body_lines = [f"  reason {i}" for i in range(guard.JINJA_BLOCK_LINE_THRESHOLD)]
    jinja_body_lines[-1] = "  confirmed on 2026-05-22"
    jinja_body = "\n".join(jinja_body_lines)

    description_body_lines = [f"  para {i}" for i in range(guard.YAML_DESCRIPTION_LINE_THRESHOLD + 1)]
    description_body_lines[-1] = "  runtime measured at 5min"
    description_body = "\n".join(description_body_lines)

    prose_comment_lines = "\n".join(f"# reason {i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1))
    dead_config_lines = "\n".join(
        f"#   key_{i}: value_{i}" for i in range(guard.YAML_COMMENT_RUN_LINE_THRESHOLD + 1)
    )

    text = (
        f"value_template: >-\n  {{#\n{jinja_body}\n  #}}\n"
        f"description: |\n{description_body}\n"
        f"{prose_comment_lines}\n"
        "key: value\n"
        f"{dead_config_lines}\n"
        "other_key: value\n"
        "final_key: value  # confirmed on 2026-05-22\n"
    )
    line_count = len(guard._split_rows(text))

    findings = guard.find_yaml_findings(text)

    assert len(findings) == 7
    for finding in findings:
        _assert_finding_shape(finding, line_count)

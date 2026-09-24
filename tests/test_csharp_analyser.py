import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("comment_intent_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_module()


def test_line_comment_with_a_date_is_flagged():
    text = "int x = 1; // fixed on 2026-01-05\n"

    _, findings = guard._scan_csharp_comments(text)

    assert any("date, measurement, or SHA" in message for message, _ in findings)


def test_line_comment_with_an_issue_reference_is_blocked():
    text = "int x = 1; // see #123 for context\n"

    blocking, _ = guard._scan_csharp_comments(text)

    assert any("issue reference" in message for message, _ in blocking)


def test_oversize_line_comment_run_is_flagged():
    text = "\n".join(f"// reason {i}" for i in range(guard.COMMENT_RUN_LINE_THRESHOLD + 1)) + "\nvoid M() {}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert any(message.startswith("Comment run of") for message, _ in findings)


def test_short_line_comment_run_is_not_flagged_as_oversize():
    text = "// reason 0\n// reason 1\nvoid M() {}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert not any(message.startswith("Comment run of") for message, _ in findings)


def test_oversize_doc_comment_block_is_flagged():
    lines = "\n".join(f"/// reason {i}" for i in range(guard.DOCSTRING_LINE_THRESHOLD + 1))
    text = f"{lines}\nvoid M() {{}}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert any(message.startswith("XML doc comment spans") for message, _ in findings)


def test_short_doc_comment_block_is_not_flagged_as_oversize():
    text = "/// <summary>Short.</summary>\nvoid M() {}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert not any(message.startswith("XML doc comment spans") for message, _ in findings)


def test_find_csharp_findings_returns_the_advisory_half():
    text = "int x = 1; // fixed on 2026-01-05\n"

    findings = guard.find_csharp_findings(text)

    assert any("date, measurement, or SHA" in message for message, _ in findings)


def test_find_csharp_issue_reference_violations_returns_the_blocking_half():
    text = "int x = 1; // see #123 for context\n"

    violations = guard.find_csharp_issue_reference_violations(text)

    assert any("issue reference" in message for message, _ in violations)


def test_doc_comment_on_a_fact_test_method_is_a_blocking_violation():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert any("no caller" in message for message, _ in violations)


def test_doc_comment_before_a_test_attribute_among_other_attributes_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        '[Trait("Category", "unit")]\n'
        "[Theory]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert any("no caller" in message for message, _ in violations)


def test_external_id_in_a_doc_comment_block_is_a_blocking_violation():
    text = "/// Fixes JIRA-4821 for real this time.\npublic void DoesAThing()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/src/Thing.cs")

    assert any("JIRA-4821" in message for message, _ in violations)


def test_external_id_in_a_doc_comment_is_allowed_by_the_repo_config(tmp_path):
    (tmp_path / ".comment-intent-guard.json").write_text(json.dumps({"id_prefix_allowlist": ["jira"]}))
    text = "/// Fixes JIRA-4821 for real this time.\npublic void DoesAThing()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, str(tmp_path / "src" / "Thing.cs"))

    assert violations == []


def test_findings_for_file_routes_cs_files_to_the_csharp_analyser():
    text = "int x = 1; // fixed on 2026-01-05\n"

    blocking, advisory = guard._findings_for_file("/repo/src/Thing.cs", text)

    assert blocking == []
    assert any("date, measurement, or SHA" in message for message, _ in advisory)


def _run_hook(payload):
    return subprocess.run(
        [sys.executable, str(_MODULE_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_e2e_write_cs_file_with_test_doc_comment_denies_the_edit():
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/Tests/ThingTests.cs",
            "content": "/// <summary>Checks the thing.</summary>\n[Fact]\npublic void ChecksTheThing()\n{\n}\n",
        },
    }

    result = _run_hook(payload)

    output = json.loads(result.stdout)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "no caller" in reason


def test_e2e_edit_cs_file_with_a_dated_comment_emits_advisory():
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/repo/src/Thing.cs",
            "new_string": "int x = 1; // fixed on 2026-01-05\n",
        },
    }

    result = _run_hook(payload)

    output = json.loads(result.stdout)
    assert "date, measurement, or SHA" in output["hookSpecificOutput"]["additionalContext"]


def test_e2e_clean_cs_produces_no_advisory():
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/src/Thing.cs",
            "content": "public class Thing\n{\n    public void DoIt() {}\n}\n",
        },
    }

    result = _run_hook(payload)

    assert result.stdout == ""


def test_scan_pathspecs_include_cs_files():
    assert "*.cs" in guard._SCAN_PATHSPECS


def test_bash_backstop_tracked_globs_include_cs_files():
    backstop_path = Path(__file__).resolve().parent.parent / "hooks" / "bash_backstop.py"
    spec = importlib.util.spec_from_file_location("bash_backstop_under_test", backstop_path)
    backstop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backstop)

    assert "*.cs" in backstop._TRACKED_GLOBS


def test_doc_comment_on_a_non_test_method_is_not_a_blocking_violation():
    text = (
        "/// <summary>Does a thing.</summary>\n"
        "public void DoesAThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/src/Thing.cs")

    assert violations == []


def test_double_slash_inside_a_string_literal_is_not_a_comment():
    text = 'var s = "http://example.com";\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == []


def test_line_comment_yields_a_line_span_with_its_text():
    text = "int x = 1; // trailing note\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " trailing note")]


def test_triple_slash_yields_a_doc_span_not_a_line_span():
    text = "/// <summary>Does a thing.</summary>\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("doc", 0, 0, " <summary>Does a thing.</summary>")]


def test_char_literal_holding_a_quote_does_not_confuse_string_tracking():
    text = "char c = '\"'; // trailing\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " trailing")]


def test_verbatim_string_trailing_backslash_does_not_escape_the_closing_quote():
    # Verbatim strings treat backslash as a literal char, not an escape.
    text = 'var s = @"path\\"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real")]


def test_slash_star_inside_a_verbatim_string_is_not_a_block_comment():
    text = 'var s = @"a /* not a comment */ still string"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real")]


def test_raw_string_containing_triple_slash_is_not_a_doc_comment():
    text = 'var s = """embedded /// text""";\n// real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 1, 1, " real")]


def test_raw_string_trailing_backslash_before_the_closer_does_not_escape_it():
    # Raw strings, like verbatim strings, give backslash no escaping power.
    text = 'var s = """path\\""";\n// real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 1, 1, " real")]


def test_dollar_at_interpolated_verbatim_string_backslash_does_not_escape_the_closer():
    text = 'var s = $@"path\\"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real")]


def test_at_dollar_interpolated_verbatim_string_backslash_does_not_escape_the_closer():
    text = 'var s = @$"path\\"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real")]


def test_contiguous_triple_slash_lines_group_into_one_doc_span():
    text = "/// <summary>\n/// Does a thing.\n/// </summary>\nvoid M() {}\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("doc", 0, 2, " <summary>\n Does a thing.\n </summary>"),
    ]


def test_a_gap_line_breaks_the_doc_comment_run_into_two_spans():
    text = "/// first\n\n/// second\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("doc", 0, 0, " first"), ("doc", 2, 2, " second")]


def test_block_comment_containing_an_unmatched_quote_still_ends_at_the_real_close():
    # A quote inside a block comment is not a string - */ must end the
    # comment right there even though the quote looks "unterminated".
    text = 'x = 1; /* he said "hi */ok\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("block", 0, 0, ' he said "hi ')]

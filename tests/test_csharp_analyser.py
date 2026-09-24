import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("comment_intent_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_module()


def _csharp_test_doc_violation(name, row):
    return guard._test_docstring_violation(name, row, "an XML doc comment", "XML doc comment")


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


def test_line_comment_run_of_exactly_the_threshold_line_count_is_not_flagged():
    text = "\n".join(f"// reason {i}" for i in range(guard.COMMENT_RUN_LINE_THRESHOLD)) + "\nvoid M() {}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert findings == []


def test_oversize_line_comment_run_is_flagged_even_with_a_leading_bom():
    text = "﻿" + "\n".join(
        f"// reason {i}" for i in range(guard.COMMENT_RUN_LINE_THRESHOLD + 1)
    ) + "\nvoid M() {}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert any(message.startswith("Comment run of") for message, _ in findings)


def test_oversize_doc_comment_block_is_flagged():
    lines = "\n".join(f"/// reason {i}" for i in range(guard.DOCSTRING_LINE_THRESHOLD + 1))
    text = f"{lines}\nvoid M() {{}}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert any(message.startswith("XML doc comment spans") for message, _ in findings)


def test_short_doc_comment_block_is_not_flagged_as_oversize():
    text = "/// <summary>Short.</summary>\nvoid M() {}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert not any(message.startswith("XML doc comment spans") for message, _ in findings)


def test_doc_comment_block_of_exactly_the_threshold_line_count_is_not_flagged():
    lines = "\n".join(f"/// reason {i}" for i in range(guard.DOCSTRING_LINE_THRESHOLD))
    text = f"{lines}\nvoid M() {{}}\n"

    _, findings = guard._scan_csharp_comments(text)

    assert findings == []


def test_find_csharp_findings_returns_the_advisory_half():
    text = "int x = 1; // fixed on 2026-01-05\n"

    findings = guard.find_csharp_findings(text)

    assert any("date, measurement, or SHA" in message for message, _ in findings)


def test_find_csharp_issue_reference_violations_returns_the_blocking_half():
    text = "int x = 1; // see #123 for context\n"

    violations = guard.find_csharp_issue_reference_violations(text)

    assert any("issue reference" in message for message, _ in violations)


def test_doc_comment_on_a_test_method_says_xml_doc_comment_not_docstring():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert any("XML doc comment" in message and "docstring" not in message for message, _ in violations)


def test_doc_comment_on_a_fact_test_method_is_a_blocking_violation():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3)),
    ]


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

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4)),
    ]


def test_doc_comment_before_a_blank_line_then_attribute_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4)),
    ]


def test_doc_comment_with_a_stray_triple_slash_line_before_the_signature_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact]\n"
        "/// TODO: clean up\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    expected = (_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4))
    assert violations == [expected, expected]


def test_doc_comment_before_a_fully_qualified_attribute_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Xunit.Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3)),
    ]


def test_doc_comment_before_a_generic_test_method_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Theory]\n"
        "public void ChecksTheThing<TItem>()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3)),
    ]


def test_javadoc_style_block_comment_before_a_test_method_is_blocked():
    text = (
        "/** Checks the thing. */\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3)),
    ]


def test_javadoc_style_block_comment_span_has_doc_kind():
    text = "/** summary */\nint x = 1;\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans[0][0] == "doc"


def test_issue_reference_after_a_leading_block_comment_is_still_blocked():
    text = "/* header */\nclass A {\n    // closes #12\n}\n"

    blocking, _ = guard._scan_csharp_comments(text)

    assert blocking == [(guard._issue_reference_violation("Comment", 2), (3, 3))]


def test_issue_reference_inside_a_multi_line_block_comment_is_blocked():
    text = "/* a\n   see #12\n */\n"

    blocking, _ = guard._scan_csharp_comments(text)

    assert blocking == [(guard._issue_reference_violation("Comment", 0), (1, 3))]


def test_every_documented_test_method_is_blocked_even_after_a_plain_comment():
    text = (
        "// helpers\n"
        "/// <summary>Checks a.</summary>\n"
        "[Fact]\n"
        "public void ChecksA()\n"
        "{\n"
        "}\n"
        "\n"
        "/// <summary>Checks b.</summary>\n"
        "[Fact]\n"
        "public void ChecksB()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksA", 4), (4, 4)),
        (_csharp_test_doc_violation("ChecksB", 10), (10, 10)),
    ]


def test_every_external_id_is_blocked_even_after_a_plain_comment():
    text = (
        "// helpers\n"
        "/// Fixes JIRA-4821 for real this time.\n"
        "public void DoesAThingA()\n"
        "{\n"
        "}\n"
        "\n"
        "/// Fixes JIRA-9001 for real this time.\n"
        "public void DoesAThingB()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (guard._external_id_violation("JIRA-4821", "an XML doc comment", 2), (2, 2)),
        (guard._external_id_violation("JIRA-9001", "an XML doc comment", 7), (7, 7)),
    ]


def test_doc_comment_before_a_same_line_attribute_and_signature_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (
            _csharp_test_doc_violation("ChecksTheThing", 2),
            (2, 2),
        )
    ]


def test_doc_comment_before_a_same_line_attribute_does_not_misattribute_the_body():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] public void ChecksTheThing()\n"
        "{\n"
        "    Assert.Equal(1, 1);\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert not any("Equal" in message for message, _ in violations)
    assert any("ChecksTheThing" in message for message, _ in violations)


@pytest.mark.parametrize(
    "name",
    ["Fact", "Theory", "Test", "TestCase", "TestMethod", "FactAttribute", "Xunit.Fact", "Xunit.FactAttribute"],
)
def test_is_csharp_test_attribute_recognises_test_attribute_names(name):
    assert guard._is_csharp_test_attribute(name)


@pytest.mark.parametrize("name", ["HttpGet", "Obsolete", "Serializable", "HttpGetAttribute"])
def test_is_csharp_test_attribute_rejects_non_test_attribute_names(name):
    assert not guard._is_csharp_test_attribute(name)


def test_doc_comment_on_an_http_get_method_is_not_blocked():
    text = "/// <summary>Gets the thing.</summary>\n[HttpGet]\npublic void GetsTheThing()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/src/Thing.cs")

    assert violations == []


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


def test_findings_for_file_tokenizes_a_cs_file_at_most_once(monkeypatch):
    text = "int x = 1; // fixed on 2026-01-05\n/// <summary>doc</summary>\n[Fact]\nvoid T() {}\n"
    calls = []
    real_spans = guard._csharp_comment_spans

    def counting_spans(t):
        calls.append(t)
        return real_spans(t)

    monkeypatch.setattr(guard, "_csharp_comment_spans", counting_spans)

    guard._findings_for_file("/repo/src/Thing.cs", text)

    assert len(calls) == 1


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


def test_doc_comment_before_an_mstest_test_method_attribute_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[TestMethod]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (
            _csharp_test_doc_violation("ChecksTheThing", 3),
            (3, 3),
        )
    ]


def test_doc_comment_on_a_different_member_than_the_test_attribute_is_not_blocked():
    text = (
        "/// <summary>The widget config.</summary>\n"
        "public Config Configuration { get; set; }\n"
        "\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_not_adjacent_to_the_test_method_is_not_blocked():
    text = (
        "/// <summary>Old note.</summary>\n"
        "public int Count;\n"
        "\n"
        "[Fact]\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_double_slash_inside_a_string_literal_is_not_a_comment():
    text = 'var s = "http://example.com";\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == []


def test_unterminated_regular_string_does_not_swallow_the_next_real_comment():
    text = 'var s = "oops\n// fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 1, 1, " fixed on 2026-01-05")]


def test_unterminated_block_comment_consumes_the_rest_of_the_file_as_a_single_span():
    text = "/* a // closes #12"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("block", 0, 0, " a // closes #12")]


def test_two_tightly_adjacent_block_comments_on_one_line_each_get_their_own_span():
    text = "/*a*//*b*/ // closes #12\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("block", 0, 0, "a"),
        ("block", 0, 0, "b"),
        ("line", 0, 0, " closes #12"),
    ]


def test_empty_block_comment_close_search_starts_immediately_after_the_opener():
    text = "/**/ // closes #12\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("block", 0, 0, ""),
        ("line", 0, 0, " closes #12"),
    ]


def test_adjacent_quotes_in_a_regular_string_are_not_doubling_escaped():
    text = 'var s = "" // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05")]


def test_regular_string_escapes_a_quote_with_backslash_not_doubling():
    text = 'var s = "a\\"" // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05")]


def test_escaped_quote_in_interpolated_string_text_is_not_a_comment_boundary():
    text = 'var s = $"a \\" // not"; // real #1\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #1")]


def test_skip_char_literal_consumes_an_escaped_quote_whole():
    text = "'\\''"

    end = guard._csharp_skip_char_literal(text, 0)

    assert end == len(text)


def test_skip_char_literal_consumes_an_escaped_backslash_whole():
    text = "'\\\\'"

    end = guard._csharp_skip_char_literal(text, 0)

    assert end == len(text)


def test_escaped_quote_char_literal_is_skipped_whole():
    text = "char c = '\\''; // real #2\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #2")]


def test_escaped_backslash_char_literal_is_skipped_whole():
    text = "char c = '\\\\'; // real #3\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #3")]


def test_skip_raw_interpolation_hole_tracks_nested_brace_depth_past_a_literal():
    hole = '{{ new { a = "}" } }}'

    end = guard._csharp_skip_raw_interpolation_hole(hole, 2, 2)

    assert end == len(hole)


def test_nested_brace_depth_in_a_single_dollar_raw_string_hole_is_tracked_past_the_first_close():
    text = 'var j = $"""{ new { a = 1 } } // not"""; // closes #12\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " closes #12")]


def test_nested_braces_and_string_inside_a_raw_interpolation_hole_are_skipped():
    text = 'var j = $$"""{{ new { a = "}" } }}"""; // real #4\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #4")]


def test_skip_interpolated_string_consumes_a_literal_double_brace_pair():
    text = '"{x} }} end"'

    end = guard._csharp_skip_interpolated_string(text, 0, False)

    assert end == len(text)


def test_double_brace_immediately_before_the_closing_quote_stays_inside_the_string():
    text = 'var s = $"{x}}}"; // closes #12\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " closes #12")]


def test_double_brace_literal_inside_a_regular_interpolated_string_is_not_a_hole():
    text = 'var s = $"{x} }} end"; // real #5\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #5")]


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


def test_verbatim_string_doubled_quote_followed_by_a_backslash_stays_in_the_string():
    text = 'var s = @"""\\"; // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05")]


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


def test_interpolation_hole_with_a_nested_escaped_quote_does_not_confuse_the_closer():
    text = 'var s = $"X: {Get("a\\"b")}"; // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05")]


def test_doubled_braces_in_an_interpolated_string_are_literal_not_a_hole():
    text = 'var s = $"{{literal}} {Name}"; // real\n'

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


def test_dollar_dollar_raw_interpolated_string_with_json_braces_has_no_findings():
    text = (
        'var s = $$"""\n'
        '{"a": {{x}} } // not comment #9\n'
        '""";\n'
    )

    blocking, findings = guard._scan_csharp_comments(text)

    assert blocking == []
    assert findings == []


def test_dollar_raw_interpolated_string_with_single_brace_hole_has_no_findings():
    text = (
        'var s = $"""\n'
        '{x} // not comment #9\n'
        '""";\n'
    )

    blocking, findings = guard._scan_csharp_comments(text)

    assert blocking == []
    assert findings == []


def test_dollar_dollar_raw_interpolated_string_single_line_has_no_findings():
    text = 'var s = $$"""{{x}} and { "//q #5" }""";\n'

    blocking, findings = guard._scan_csharp_comments(text)

    assert blocking == []
    assert findings == []


def test_unterminated_interpolation_hole_does_not_swallow_later_comments():
    text = 'var s = $"{x;\n// real #1\nint y; // real #2\n'

    blocking, findings = guard._scan_csharp_comments(text)

    assert len(blocking) == 2


def test_doc_comment_after_the_attribute_and_before_the_signature_is_blocked():
    text = (
        "[Fact]\n"
        "/// b\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]


def test_doc_comment_before_an_attribute_with_a_bracket_inside_a_string_argument_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        '[Fact(DisplayName = "a]b")]\n'
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3)),
    ]

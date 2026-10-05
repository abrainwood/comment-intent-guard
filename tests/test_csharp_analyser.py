import importlib.util
import itertools
import json
import random
import re
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
        "/// doc\n"
        "[Fact]\n"
        '[Trait("a", "b")]\n'
        "/// stray\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 5), (5, 5))]


def test_doc_comment_before_an_attribute_with_an_unterminated_comment_closing_on_a_later_line_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* oops real code\n"
        "some other stray text */\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4))]


def test_doc_comment_before_a_block_comment_spanning_two_attribute_lines_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* start\n"
        'end */ [Trait("x", "y")]\n'
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4))]


def test_doc_comment_before_two_chained_block_comments_where_the_second_is_unterminated_is_blocked():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* a */ /* b\n"
        "c */\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4))]


def test_doc_comment_before_two_chained_block_comments_does_not_name_a_method_inside_the_second_comment():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* a */ /* b\n"
        "public void Fake()\n"
        "c */\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 5), (5, 5))]


def test_comment_spans_truncate_a_never_closing_block_comment_at_end_of_its_opening_line():
    text = "/* unterminated\n/// doc\npublic void X()\n{\n}\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("block", 0, 0, " unterminated", None),
        ("doc", 1, 1, " doc", None),
    ]


def test_doc_comment_before_a_comment_closing_with_trailing_real_code_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* start\n"
        "see Helper() */ public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_a_comment_closing_with_a_trailing_attribute_and_code_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* a\n"
        'end */ [Trait("x", "y")] public void ChecksTheThing()\n'
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_an_attribute_whose_block_comment_never_closes_still_finds_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* never closed\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_an_attribute_whose_opener_overlaps_a_false_close_marker_finds_the_real_close():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /*/ start\n"
        "end */\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 4), (4, 4))]


def test_a_block_comment_whose_close_overlaps_its_opener_before_an_attribute_before_a_doc_comment_names_the_method():
    text = (
        "/*/ x */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_an_attribute_with_a_block_comment_spanning_three_or_more_lines_finds_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        "[Fact] /* a\n"
        "b\n"
        "c\n"
        "d */\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 6), (6, 6))]


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

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 2), (2, 2))]


def test_attribute_with_a_block_comment_before_a_doc_comment_names_the_method():
    text = (
        '[Fact] /* a */ [Trait("x", "y")]\n'
        "/// <summary>Checks the thing.</summary>\n"
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_a_block_comment_between_two_attributes_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        '[Fact] /* a */ [Trait("x", "y")]\n'
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_a_block_comment_between_attributes_with_a_trailing_line_comment_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        '[Fact] /* a */ [Trait("x", "y")] // trailing\n'
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_two_chained_block_comments_between_attributes_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        '[Fact] /* a */ /* b */ [Trait("x", "y")]\n'
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_three_attributes_separated_by_two_block_comments_names_the_method():
    text = (
        "/// <summary>Checks the thing.</summary>\n"
        '[Fact] /* a */ [Trait("x", "y")] /* b */ [Category("c")]\n'
        "public void ChecksTheThing()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("ChecksTheThing", 3), (3, 3))]


def test_doc_comment_before_a_non_test_attribute_then_block_comment_then_fact_names_the_method():
    text = (
        "/// <summary>x</summary>\n"
        '[Trait("x", "y")] /* a */ [Fact]\n'
        "public void M()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("M", 3), (3, 3))]


def test_non_test_attribute_then_block_comment_then_fact_before_a_doc_comment_names_the_method():
    text = (
        '[Trait("x", "y")] /* a */ [Fact]\n'
        "/// <summary>x</summary>\n"
        "public void M()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("M", 3), (3, 3))]


def test_doc_comment_before_a_non_test_attribute_then_block_comment_then_another_non_test_attribute_is_not_blocked():
    text = (
        "/// <summary>x</summary>\n"
        '[Trait("x", "y")] /* a */ [Obsolete]\n'
        "public void M()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_before_a_generic_attribute_whose_type_argument_names_a_test_attribute_is_not_blocked():
    text = (
        "/// <summary>x</summary>\n"
        "[Foo<int, Fact>]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_before_a_dotted_generic_attribute_whose_type_argument_names_a_test_attribute_is_not_blocked():
    text = (
        "/// <summary>x</summary>\n"
        "[Foo.Bar<int, Fact>]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


@pytest.mark.parametrize(
    "attribute_args",
    [
        "InlineData(1 < 2), Theory",
        "Foo(1 << 2), Fact",
        "Foo(a <= b), Fact",
        "Foo<int>, Fact",
        "Foo<Bar<int>>, Fact",
    ],
)
def test_doc_comment_before_a_test_attribute_after_a_relational_or_generic_token_in_the_section_names_the_method(
    attribute_args,
):
    text = f"/// x\n[{attribute_args}]\npublic void X()\n{{\n}}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_two_doc_commented_test_methods_declared_on_the_same_row_are_both_blocked():
    text = "/** a */ [Fact] public void A() {} /** b */ [Fact] public void B() {}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("A", 1), (1, 1)),
        (_csharp_test_doc_violation("B", 1), (1, 1)),
    ]


def test_doc_comment_before_a_tuple_returning_method_names_the_method_not_the_modifier():
    text = (
        "/// <summary>x</summary>\n"
        "[Fact]\n"
        "public (int, int) X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_tuple_returning_method_with_a_tuple_parameter_names_the_method():
    text = (
        "/// <summary>x</summary>\n"
        "[Fact]\n"
        "public (int, int) X((int, int) pair)\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


@pytest.mark.parametrize(
    "signature",
    [
        "public static (int,int) X<T>()",
        "public (int,int)[] X()",
        "public (int,int)? X()",
        "public new (int, int) X()",
    ],
)
def test_doc_comment_before_a_decorated_tuple_returning_signature_names_the_method(signature):
    text = f"/// x\n[Fact]\n{signature}\n{{\n}}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_generic_task_of_tuple_returning_method_names_the_method():
    text = (
        "/// x\n"
        "[Fact]\n"
        "public async Task<(int a,int b)> X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_truncated_parameter_list_at_end_of_file_falls_back_to_the_method_name():
    text = "/// x\n[Fact]\npublic void X(\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_signature_followed_by_unrecognised_trailing_text_falls_back_to_the_method_name():
    text = "/// x\n[Fact]\npublic void X() Y\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_method_whose_body_deconstructs_a_tuple_names_the_method_not_the_deconstruction():
    text = (
        "/// <summary>x</summary>\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "    (var a, var b) = Get();\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_generic_constrained_method_names_the_method():
    text = (
        "/// x\n"
        "[Fact]\n"
        "public void X<T>() where T : new()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_an_expression_bodied_tuple_returning_method_names_the_method():
    text = "/// x\n[Fact]\npublic (int, int) X() => (1, 2);\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_an_abstract_bodyless_tuple_returning_method_names_the_method():
    text = "/// x\n[Fact]\npublic abstract (int, int) X();\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_line_comment_containing_a_bracket_group_is_not_blocked():
    text = (
        "/// <summary>x</summary>\n"
        "[Obsolete] // [Fact]\n"
        "public void M()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_line_comment_containing_a_bracket_group_before_a_doc_comment_is_not_blocked():
    text = (
        "[Obsolete] // [Fact]\n"
        "/// <summary>x</summary>\n"
        "public void M()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_attribute_with_a_multi_line_block_comment_before_a_doc_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "end */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_attribute_with_a_multi_line_block_comment_and_trailing_attribute_before_a_doc_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "middle\n"
        'end */ [Trait("x", "y")]\n'
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_test_attribute_after_a_multi_line_block_comment_close_before_a_doc_comment_names_the_method():
    text = (
        "[Obsolete] /* a\n"
        "end */ [Fact]\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_non_test_attribute_with_a_multi_line_block_comment_before_a_doc_comment_is_not_blocked():
    text = (
        "[Obsolete] /* a\n"
        "end */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_inside_an_open_block_comment_before_an_attribute_is_not_blocked():
    text = (
        "[Fact] /* x\n"
        "/// doc\n"
        "*/ public void M()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_multi_line_block_comment_before_an_attribute_before_a_doc_comment_names_the_method():
    text = (
        "/* a\n"
        "b */\n"
        "[Fact]\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_an_unrelated_earlier_self_contained_block_comment_does_not_name_a_later_method():
    text = (
        "[Fact] /* flaky */\n"
        "public void Y()\n"
        "{\n"
        "}\n"
        "/// <summary>d</summary>\n"
        "public void Helper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_unrelated_earlier_multi_line_block_comment_does_not_name_a_later_method():
    text = (
        "[Fact] /* a\n"
        "b */\n"
        "public void A() {}\n"
        "/// doc\n"
        "public void B() {}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_block_comment_marker_inside_an_attribute_string_argument_does_not_name_a_later_method():
    text = (
        '[Theory(Skip = "/*")]\n'
        "public void Y()\n"
        "{\n"
        "}\n"
        "/// <summary>d</summary>\n"
        "public void Helper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_block_comment_marker_inside_a_line_comment_does_not_name_a_later_method():
    text = (
        "[Fact] // see /* x\n"
        "public void Y()\n"
        "{\n"
        "}\n"
        "/// <summary>d</summary>\n"
        "public void Helper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_block_comment_close_marker_inside_a_string_on_the_line_above_the_doc_is_not_blocked():
    text = (
        "[Fact]\n"
        'var s = "*/";\n'
        "/// <summary>d</summary>\n"
        "public void Helper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_attribute_with_a_multi_line_block_comment_whose_close_line_opens_another_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "end */ /* b */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_multi_line_block_comment_closed_before_a_trailing_attribute_with_a_comment_marker_names_the_method():
    text = (
        "[Fact] /* a\n"
        'end */ [Trait("k", "/*")]\n'
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_multi_line_block_comment_closed_before_a_trailing_line_comment_with_a_comment_marker_names_the_method():
    text = (
        "[Fact] /* a\n"
        "end */ // see /* x\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_an_attribute_then_a_block_comment_and_line_comment_on_one_line_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "/* a */ // c\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_an_attribute_then_a_block_comment_and_line_comment_on_one_line_before_a_doc_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/* a */ // b\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_a_block_comment_and_line_comment_on_one_line_then_an_attribute_names_the_method():
    text = (
        "/// doc\n"
        "/* a */ // c\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_a_trailing_block_comment_on_an_earlier_method_line_does_not_name_a_later_method():
    text = (
        "[Fact] /* flaky */\n"
        "public void Y() { } /* done */\n"
        "/// <summary>d</summary>\n"
        "public void Helper() { }\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_two_stacked_block_comments_on_one_line_before_a_doc_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "b */ /* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_doc_comment_before_an_attribute_then_two_standalone_block_comments_on_one_line_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "/* a */ /* b */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_an_attribute_then_a_chain_of_blocks_ending_in_a_multi_line_block_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "/* a */ /* b\n"
        "c */ public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_two_standalone_block_comments_on_one_line_before_an_attribute_before_a_doc_comment_names_the_method():
    text = (
        "/* a */ /* b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_two_stacked_block_comments_on_separate_lines_before_a_doc_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "b */\n"
        "/* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 6), (6, 6))]


def test_three_stacked_block_comments_before_a_doc_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "b */ /* c\n"
        "d */\n"
        "/* e\n"
        "f */\n"
        "/// <summary>g</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 7), (7, 7))]


def test_two_stacked_block_comments_before_a_non_test_attribute_is_not_blocked():
    text = (
        "[Obsolete] /* a\n"
        "b */ /* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_code_line_between_the_attribute_and_a_stacked_comment_does_not_name_a_later_method():
    text = (
        "[Fact] /* flaky */\n"
        "public void Y()\n"
        "{\n"
        "}\n"
        "/* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void Helper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_stacked_comment_opener_on_a_code_line_does_not_name_a_later_method():
    text = (
        "public void Y() /* a\n"
        "b */ /* c\n"
        "d */\n"
        "/// doc\n"
        "public void Z()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_stacked_comment_with_a_trailing_attribute_on_its_middle_close_line_names_the_method():
    text = (
        "[Fact] /* a\n"
        'b */ [Trait("x", "y")] /* c\n'
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_an_attribute_line_without_a_comment_marker_above_a_standalone_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_an_attribute_inside_an_open_block_comment_does_not_name_the_method():
    text = (
        "[Obsolete] /* a\n"
        "[Fact]\n"
        "/* b\n"
        "c */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_attribute_inside_an_open_block_comment_before_a_single_line_comment_does_not_name_the_method():
    text = (
        "[Obsolete] /* a\n"
        "[Fact]\n"
        "/* c */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_blank_line_between_two_stacked_single_line_block_comments_names_the_method():
    text = (
        "[Fact] /* a */\n"
        "\n"
        "/* c */\n"
        "/// d\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_blank_line_between_two_stacked_multi_line_block_comments_names_the_method():
    text = (
        "[Fact] /* a\n"
        "b */\n"
        "\n"
        "/* c\n"
        "d */\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 7), (7, 7))]


def test_an_earlier_unrelated_block_comment_does_not_hide_a_bare_attribute_names_the_method():
    text = (
        "[Fact] /* flaky */\n"
        "public void Y() { }\n"
        "[Fact]\n"
        "/* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 7), (7, 7))]


def test_a_license_header_block_comment_does_not_hide_a_bare_attribute_names_the_method():
    text = (
        "/* license */\n"
        "class T {\n"
        "[Fact]\n"
        "/* c\n"
        "d */\n"
        "/// d\n"
        "public void X()\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 7), (7, 7))]


def test_an_earlier_block_comment_does_not_hide_a_bare_attribute_before_a_single_line_comment_names_the_method():
    text = (
        "/* h */\n"
        "[Fact]\n"
        "/* c */\n"
        "/// d\n"
        "public void X()\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_blank_line_before_a_bare_attributes_stacked_comment_names_the_method():
    text = (
        "[Fact]\n"
        "\n"
        "/* c\n"
        "d */\n"
        "/// <summary>d</summary>\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 6), (6, 6))]


def test_a_line_comment_between_a_stacked_block_comment_and_the_doc_comment_names_the_method():
    text = (
        "[Fact] /* a\n"
        "b */\n"
        "// c\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_test_attribute_on_an_earlier_member_behind_a_line_comment_and_a_commented_field_does_not_name_a_later_method():
    text = (
        "[Fact]\n"
        "// c\n"
        "/* c */ int y;\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_same_line_commented_test_attribute_on_an_earlier_field_does_not_name_a_later_method():
    text = (
        "/* c */ [Fact]\n"
        "/* d */ int y;\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_blank_line_between_stacked_bare_attributes_before_a_doc_comment_names_the_method():
    text = (
        "[Fact]\n"
        "\n"
        "[Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_two_bare_attribute_lines_before_a_doc_comment_names_the_method():
    text = (
        "[Fact]\n"
        '[Trait("x", "y")]\n'
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_an_earlier_member_declared_on_its_attribute_line_does_not_hide_the_test_attribute_before_a_doc_comment():
    text = (
        "[Fact] public void A() { }\n"
        "[Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_an_earlier_member_after_a_leading_block_comment_does_not_hide_the_test_attribute_before_a_doc_comment():
    text = (
        "[Obsolete]\n"
        "/* c */ public void A() { }\n"
        "[Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_same_line_block_comment_before_an_attribute_before_a_doc_comment_names_the_method():
    text = (
        "/* c */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_a_same_line_block_comment_before_a_non_test_attribute_before_a_doc_comment_is_not_blocked():
    text = (
        "/* c */ [Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_before_an_attribute_followed_by_two_stacked_standalone_block_comments_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "/* a */\n"
        "/* b */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_multi_line_block_comment_closing_on_the_attribute_line_before_a_doc_comment_names_the_method():
    text = (
        "/* a\n"
        "b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_a_multi_line_block_comment_closing_on_a_non_test_attribute_line_before_a_doc_comment_is_not_blocked():
    text = (
        "/* a\n"
        "b */ [Obsolete]\n"
        "/// doc\n"
        "public class C\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_bare_attribute_before_a_block_comment_closing_on_a_non_test_attribute_before_a_doc_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/* a\n"
        "b */ [Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


@pytest.mark.parametrize(
    "name",
    [
        "Fact", "Theory", "Test", "TestCase", "TestMethod", "FactAttribute",
        "DataTestMethod", "TestCaseSource", "SkippableFact", "SkippableTheory",
    ],
)
def test_is_csharp_test_attribute_recognises_test_attribute_names(name):
    assert guard._is_csharp_test_attribute(name)


@pytest.mark.parametrize("name", ["HttpGet", "Obsolete", "Serializable", "HttpGetAttribute", "Factory", "FactoryAttribute"])
def test_is_csharp_test_attribute_rejects_non_test_attribute_names(name):
    assert not guard._is_csharp_test_attribute(name)


@pytest.mark.parametrize("name", ["CustomFact", "UIFact", "CustomTheory", "CustomFactAttribute"])
def test_is_csharp_test_attribute_recognises_fact_and_theory_suffixed_names(name):
    assert guard._is_csharp_test_attribute(name)


@pytest.mark.parametrize("name", ["STATestMethod", "UITestMethod"])
def test_is_csharp_test_attribute_recognises_test_method_suffixed_names(name):
    assert guard._is_csharp_test_attribute(name)


def test_is_csharp_test_attribute_rejects_artifact():
    assert not guard._is_csharp_test_attribute("Artifact")


@pytest.mark.parametrize("attribute", ["Xunit.Fact", "Xunit.FactAttribute", "Xunit.SkippableFactAttribute"])
def test_doc_comment_before_a_dotted_test_attribute_is_blocked(attribute):
    text = f"/// x\n[{attribute}]\npublic void X()\n{{\n}}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_custom_fact_attribute_is_blocked():
    text = "/// x\n[CustomFact]\npublic void X()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_a_plain_block_comment_opened_with_three_stars_before_a_fact_is_not_blocked():
    text = "/*** not a doc comment */\n[Fact]\npublic void TestFoo()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_external_id_inside_a_three_star_block_comment_is_not_a_blocking_violation():
    text = "/*** Fixes JIRA-4821, not an XML doc comment ***/\npublic void DoesAThing()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/src/Thing.cs")

    assert violations == []


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


def test_a_trailing_line_comment_on_a_preprocessor_line_is_still_a_blocking_issue_reference():
    text = "#if DEBUG\nint x;\n#endif // closes #12\n"

    blocking, _advisory = guard._findings_for_file("/repo/src/Thing.cs", text)

    assert blocking == [(guard._issue_reference_violation("Comment", 2), (3, 3))]


def test_a_trailing_line_comment_on_a_preprocessor_line_carries_both_blocking_and_advisory():
    text = "#pragma warning disable CS0168 // see issue #42, fixed on 2026-01-05\n"

    blocking, advisory = guard._findings_for_file("/repo/src/Thing.cs", text)

    assert blocking == [(guard._issue_reference_violation("Comment", 0), (1, 1))]
    assert advisory == [(guard._evidence_finding("Comment", 0), (1, 1))]


def test_a_trailing_line_comment_on_an_if_directive_is_an_advisory_finding():
    text = "#if DEBUG // fixed on 2026-01-05\n#endif\n"

    blocking, advisory = guard._findings_for_file("/repo/src/Thing.cs", text)

    assert blocking == []
    assert advisory == [(guard._evidence_finding("Comment", 0), (1, 1))]


def test_a_triple_slash_trailing_a_preprocessor_line_is_not_a_leading_doc_comment():
    text = "#if X /// d\n[Fact]\npublic void T()\n{\n}\n#endif\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_triple_slash_trailing_a_preprocessor_line_does_not_merge_with_the_doc_above():
    text = "/// a\n#if X /// b\n#endif\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("doc", 0, 0, " a", None),
        ("line", 1, 1, "/ b", None),
    ]


def test_a_double_slash_inside_a_string_literal_on_a_directive_line_is_not_a_comment():
    text = '#line 1 "a//b.cs"\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == []


def test_a_hash_not_at_the_start_of_a_line_is_not_a_preprocessor_directive():
    text = "x = #1 /* oops */ // fixed on 2026-01-05\n"

    spans = list(guard._csharp_comment_spans(text))
    _blocking, advisory = guard._findings_for_file("/repo/src/Thing.cs", text)

    assert spans == [
        ("block", 0, 0, " oops ", 15),
        ("line", 0, 0, " fixed on 2026-01-05", None),
    ]
    assert advisory == [(guard._evidence_finding("Comment", 0), (1, 1))]


@pytest.mark.parametrize(
    "second_line",
    ["int y; /// b", '"x" /// b', "x /// b", "} /// b"],
)
def test_a_doc_comment_after_real_code_on_its_line_does_not_merge_with_the_doc_above(second_line):
    text = f"/// a\n{second_line}\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("doc", 0, 0, " a", None),
        ("doc", 1, 1, " b", None),
    ]


def test_a_multi_digit_method_name_is_still_recognised_as_one_identifier():
    text = "/// d\n[Fact]\npublic void Method1()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("Method1", 3), (3, 3))]


def test_a_never_closing_block_comment_lets_the_next_lines_date_still_be_found():
    text = "/* x\n// fixed on 2026-01-05\n"

    blocking, advisory = guard._findings_for_file("/repo/src/Thing.cs", text)

    assert blocking == []
    assert advisory == [(guard._evidence_finding("Comment", 1), (2, 2))]


def test_a_lone_form_feed_before_a_doc_line_still_merges_it_with_the_doc_above():
    text = "/// a\n\f/// b\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("doc", 0, 1, " a\n b", None)]


def test_findings_for_file_runs_the_csharp_lexer_exactly_once(monkeypatch):
    text = "int x = 1; // fixed on 2026-01-05\n/// <summary>doc</summary>\n[Fact]\nvoid T() {}\n"
    lex_calls = []
    real_lex = guard._csharp_lex

    def counting_lex(t):
        lex_calls.append(t)
        return real_lex(t)

    monkeypatch.setattr(guard, "_csharp_lex", counting_lex)

    guard._findings_for_file("/repo/src/Thing.cs", text)

    assert len(lex_calls) == 1


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


def test_four_slash_comment_is_a_plain_line_comment_span():
    spans = guard._csharp_comment_spans("//// c\n")

    assert spans == [("line", 0, 0, "// c", None)]


def test_unterminated_regular_string_does_not_swallow_the_next_real_comment():
    text = 'var s = "oops\n// fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 1, 1, " fixed on 2026-01-05", None)]


def test_unterminated_block_comment_without_a_newline_runs_to_end_of_text():
    text = "/* a // closes #12"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("block", 0, 0, " a // closes #12", None)]


def test_two_tightly_adjacent_block_comments_on_one_line_each_get_their_own_span():
    text = "/*a*//*b*/ // closes #12\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("block", 0, 0, "a", 3),
        ("block", 0, 0, "b", 8),
        ("line", 0, 0, " closes #12", None),
    ]


def test_empty_block_comment_close_search_starts_immediately_after_the_opener():
    text = "/**/ // closes #12\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("block", 0, 0, "", 2),
        ("line", 0, 0, " closes #12", None),
    ]


def test_multi_line_block_comment_close_col_is_measured_on_its_own_close_line():
    text = "/* a\n  b */\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("block", 0, 1, " a\n  b ", 4)]


def test_comment_spans_do_not_open_a_block_comment_on_a_preprocessor_line():
    text = "#region a /* b\n/// doc\n[Fact]\npublic void X()\n{\n}\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("doc", 1, 1, " doc", None)]


def test_adjacent_quotes_in_a_regular_string_are_not_doubling_escaped():
    text = 'var s = "" // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05", None)]


def test_regular_string_escapes_a_quote_with_backslash_not_doubling():
    text = 'var s = "a\\"" // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05", None)]


def test_escaped_quote_in_interpolated_string_text_is_not_a_comment_boundary():
    text = 'var s = $"a \\" // not"; // real #1\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #1", None)]


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

    assert spans == [("line", 0, 0, " real #2", None)]


def test_escaped_backslash_char_literal_is_skipped_whole():
    text = "char c = '\\\\'; // real #3\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #3", None)]


def test_skip_raw_interpolation_hole_tracks_nested_brace_depth_past_a_literal():
    text = '$$"""{{ new { a } + """q""" }}"""'

    end = guard._csharp_try_skip_literal(text, 0)

    assert end == len(text)


def test_a_raw_interpolation_hole_only_opens_on_at_least_as_many_braces_as_dollars():
    text = '$$"""{{ """a""" }}"""'

    end = guard._csharp_try_skip_literal(text, 0)

    assert end == len(text)


def test_nested_brace_depth_in_a_single_dollar_raw_string_hole_is_tracked_past_the_first_close():
    text = 'var j = $"""{ new { a = 1 } } // not"""; // closes #12\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " closes #12", None)]


def test_nested_braces_and_string_inside_a_raw_interpolation_hole_are_skipped():
    text = 'var j = $$"""{{ new { a = "}" } }}"""; // real #4\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #4", None)]


def test_doubled_open_brace_in_an_interpolated_string_is_a_literal_brace_not_a_hole():
    text = 'var s = $"{{"; // c\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " c", None)]


def test_double_brace_immediately_before_the_closing_quote_stays_inside_the_string():
    text = 'var s = $"{x}}}"; // closes #12\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " closes #12", None)]


def test_a_hole_with_one_level_of_nested_braces_requires_both_closes_to_end_the_hole():
    text = '$"{a{b}"X"}c"'

    end = guard._csharp_try_skip_literal(text, 0)

    assert end == len(text)


def test_a_hole_with_two_levels_of_nested_braces_requires_all_three_closes_to_end_the_hole():
    text = '$"{a{b{c}"X"}d}e"'

    end = guard._csharp_try_skip_literal(text, 0)

    assert end == len(text)


def test_doubled_quote_in_a_verbatim_interpolated_string_is_a_literal_quote_not_the_closer():
    text = '$@"{x} "" y"'

    end = guard._csharp_try_skip_literal(text, 0)

    assert end == len(text)


def test_a_verbatim_interpolated_string_nested_in_a_hole_keeps_its_own_verbatim_flag():
    text = 'x = $"{ $@"a\\" } // not"; // c\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " c", None)]


def test_a_raw_interpolated_string_nested_in_a_hole_keeps_its_own_dollar_count():
    text = 'x = $"{$$"""{\\"}"""}"; // marker\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " marker", None)]


def test_double_brace_literal_inside_a_regular_interpolated_string_is_not_a_hole():
    text = 'var s = $"{x} }} end"; // real #5\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real #5", None)]


def test_line_comment_yields_a_line_span_with_its_text():
    text = "int x = 1; // trailing note\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " trailing note", None)]


def test_triple_slash_yields_a_doc_span_not_a_line_span():
    text = "/// <summary>Does a thing.</summary>\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("doc", 0, 0, " <summary>Does a thing.</summary>", None)]


def test_char_literal_holding_a_quote_does_not_confuse_string_tracking():
    text = "char c = '\"'; // trailing\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " trailing", None)]


def test_verbatim_string_trailing_backslash_does_not_escape_the_closing_quote():
    # Verbatim strings treat backslash as a literal char, not an escape.
    text = 'var s = @"path\\"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real", None)]


def test_verbatim_string_doubled_quote_followed_by_a_backslash_stays_in_the_string():
    text = 'var s = @"""\\"; // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05", None)]


def test_slash_star_inside_a_verbatim_string_is_not_a_block_comment():
    text = 'var s = @"a /* not a comment */ still string"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real", None)]


def test_raw_string_containing_triple_slash_is_not_a_doc_comment():
    text = 'var s = """embedded /// text""";\n// real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 1, 1, " real", None)]


def test_raw_string_trailing_backslash_before_the_closer_does_not_escape_it():
    # Raw strings, like verbatim strings, give backslash no escaping power.
    text = 'var s = """path\\""";\n// real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 1, 1, " real", None)]


def test_dollar_at_interpolated_verbatim_string_backslash_does_not_escape_the_closer():
    text = 'var s = $@"path\\"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real", None)]


def test_at_dollar_interpolated_verbatim_string_backslash_does_not_escape_the_closer():
    text = 'var s = @$"path\\"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real", None)]


def test_interpolation_hole_with_a_nested_escaped_quote_does_not_confuse_the_closer():
    text = 'var s = $"X: {Get("a\\"b")}"; // fixed on 2026-01-05\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " fixed on 2026-01-05", None)]


def test_doubled_braces_in_an_interpolated_string_are_literal_not_a_hole():
    text = 'var s = $"{{literal}} {Name}"; // real\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("line", 0, 0, " real", None)]


def test_contiguous_triple_slash_lines_group_into_one_doc_span():
    text = "/// <summary>\n/// Does a thing.\n/// </summary>\nvoid M() {}\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [
        ("doc", 0, 2, " <summary>\n Does a thing.\n </summary>", None),
    ]


def test_a_gap_line_breaks_the_doc_comment_run_into_two_spans():
    text = "/// first\n\n/// second\n"

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("doc", 0, 0, " first", None), ("doc", 2, 2, " second", None)]


def test_block_comment_containing_an_unmatched_quote_still_ends_at_the_real_close():
    # A quote inside a block comment is not a string - */ must end the
    # comment right there even though the quote looks "unterminated".
    text = 'x = 1; /* he said "hi */ok\n'

    spans = list(guard._csharp_comment_spans(text))

    assert spans == [("block", 0, 0, ' he said "hi ', 22)]


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


def test_doc_comment_before_a_second_attribute_names_the_method_not_the_attribute():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '[Trait("a", "b")]\n'
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 4), (4, 4))]


def test_doc_comment_before_two_stacked_attributes_names_the_method():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '[Trait("a", "b")]\n'
        "[Trait(\"c\", \"d\")]\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 5), (5, 5))]


def test_doc_comment_before_and_after_the_attribute_produces_one_finding():
    text = (
        "/// before\n"
        "[Fact]\n"
        "/// after\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 4), (4, 4))]


def test_doc_comment_before_a_blank_line_then_the_signature_names_the_method():
    text = (
        "[Fact]\n"
        "/// doc\n"
        "\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 4), (4, 4))]


def test_doc_comment_before_a_stray_triple_slash_line_then_the_signature_names_the_method():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '[Trait("a", "b")]\n'
        "/// stray\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 5), (5, 5))]


def test_doc_comment_before_a_blank_line_and_a_stray_triple_slash_line_names_the_method():
    text = (
        "[Fact]\n"
        "/// doc\n"
        "\n"
        "/// stray\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 5), (5, 5))]


def test_doc_comment_before_an_attribute_then_a_line_comment_then_the_signature_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "// c\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_a_line_comment_then_an_attribute_then_the_signature_names_the_method():
    text = (
        "/// doc\n"
        "// c\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_attribute_above_a_stray_triple_slash_line_and_a_line_comment_names_the_method_after_the_doc_comment():
    text = (
        "[Fact]\n"
        "/// a\n"
        "// c\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_a_line_comment_before_a_signature_containing_a_url_literal_still_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "// c\n"
        'public void X(string url = "http://example.com")\n'
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_a_same_line_second_attribute_and_signature_names_the_method():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '[Trait("a", "b")] public void T()\n'
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]


def test_doc_comment_before_an_attribute_with_no_method_following_is_not_blocked():
    text = (
        "[Fact]\n"
        "/// doc\n"
        "int x = 5;\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_before_an_attribute_at_end_of_file_is_not_blocked():
    text = (
        "[Fact]\n"
        "/// doc\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_before_a_second_attribute_with_a_trailing_line_comment_is_blocked():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '[Trait("a", "b")] // note\n'
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 4), (4, 4))]


def test_doc_comment_before_a_second_attribute_with_a_trailing_block_comment_is_blocked():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '[Trait("a", "b")] /* note */\n'
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 4), (4, 4))]


def test_doc_comment_before_an_attribute_with_a_trailing_line_comment_is_blocked():
    text = (
        "/// doc\n"
        "[Fact] // note\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]


def test_doc_comment_before_an_attribute_with_a_trailing_block_comment_is_blocked():
    text = (
        "/// doc\n"
        "[Fact] /* note */\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]


def test_javadoc_block_between_the_attribute_and_the_signature_is_blocked():
    text = (
        "[Fact]\n"
        "/** doc */\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]


def test_doc_comment_before_an_attribute_followed_by_a_standalone_multi_line_block_comment_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "/* lead\n"
        "x */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_doc_comment_before_an_attribute_followed_by_a_block_comment_whose_close_line_has_the_signature_names_the_method():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "/* lead\n"
        "*/ public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_a_same_line_block_comment_then_attribute_then_signature_names_the_method():
    text = (
        "/// doc\n"
        "/* c */ [Fact] public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 2), (2, 2))]


def test_doc_comment_before_a_same_line_block_comment_then_test_attribute_names_the_method():
    text = (
        "/// doc\n"
        "/* c */ [Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_doc_comment_before_a_non_test_attribute_then_a_multi_line_block_comment_closing_on_an_attribute_line_names_the_method():
    text = (
        "/// doc\n"
        "[Obsolete]\n"
        "/* c\n"
        "*/ [Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_doc_comment_before_a_non_test_attribute_then_a_block_comment_closing_on_the_attribute_and_signature_names_the_method():
    text = (
        "/// doc\n"
        "[Obsolete]\n"
        "/* c\n"
        "*/ [Fact] public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_comment_before_a_non_test_attribute_then_a_standalone_block_comment_then_fact_names_the_method():
    text = (
        "/// doc\n"
        "[Obsolete]\n"
        "/* c */\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


@pytest.mark.parametrize(
    "attribute_line",
    [
        pytest.param("[Fact] // x", id="trailing_line_comment"),
        pytest.param("[Fact] /* a */ /* b */", id="two_trailing_block_comments"),
    ],
)
def test_doc_comment_after_an_attribute_with_a_trailing_comment_is_blocked(attribute_line):
    text = (
        f"{attribute_line}\n"
        "/// doc\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]


def test_doc_comment_after_a_blank_line_after_a_test_attribute_is_blocked():
    text = (
        "[Fact]\n"
        "\n"
        "/// doc\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 4), (4, 4))]


def test_doc_comment_after_a_blank_line_after_a_non_attribute_line_after_an_attribute_is_not_blocked():
    text = (
        "using System;\n"
        "[Fact]\n"
        "GC.Collect();\n"
        "\n"
        "/// doc\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_comment_after_an_attribute_with_real_trailing_code_is_not_blocked():
    text = (
        "[Fact] someMethod();\n"
        "/// doc\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


@pytest.mark.parametrize(
    "attribute_line",
    [
        pytest.param("[Fact] /* a */ // b", id="block_then_line_comment"),
        pytest.param("[Fact] /* a */ /* b */", id="two_block_comments"),
        pytest.param("[Fact] // a /* b */", id="line_comment_containing_block_syntax"),
        pytest.param("[Fact] // see */", id="line_comment_containing_bare_close"),
    ],
)
def test_attribute_line_with_mixed_trailing_comments_is_blocked(attribute_line):
    text = (
        "/// doc\n"
        f"{attribute_line}\n"
        "public void T()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("T", 3), (3, 3))]

def test_backward_attribute_binds_to_code_after_last_block_comment_close_on_a_mixed_line():
    text = (
        "/* a */ int q; /* b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_backward_attribute_after_last_block_comment_close_that_is_not_a_test_attribute_finds_nothing():
    text = (
        "/* a */ int q; /* b */ [Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_triple_slash_after_code_is_a_doc_comment_for_the_next_member():
    text = (
        "int y = 1; /// x\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_triple_slash_after_a_leading_block_comment_is_still_a_doc_comment():
    text = (
        "/* a */ /// x\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_triple_slash_after_code_does_not_bind_an_attribute_from_the_line_above():
    text = (
        "[Fact]\n"
        "int y; /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_triple_slash_after_a_method_signature_does_not_bind_that_methods_attribute_to_the_next_member():
    text = (
        "[Fact]\n"
        "public void A() /// t\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_triple_slash_after_code_does_not_bind_a_fallback_attribute_from_the_line_above():
    text = (
        "/* a */ int q; /* b */ [Fact]\n"
        "int y; /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_four_slash_comment_does_not_bind_an_attribute_across_a_following_code_and_doc_line():
    text = (
        "[Fact] //// x\n"
        "int y = 1; /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_multi_line_javadoc_after_the_attribute_is_blocked():
    text = (
        "[Fact]\n"
        "/** doc\n"
        "*/\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_triple_slash_after_a_multi_line_block_comments_close_after_the_attribute_is_blocked():
    text = (
        "[Fact]\n"
        "/* a\n"
        "*/ /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_triple_slash_after_a_block_comment_after_the_attribute_is_blocked():
    text = (
        "[Fact]\n"
        "/* a */ /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_tab_indented_doc_comment_after_the_attribute_is_blocked():
    text = (
        "\t[Fact]\n"
        "\t/// doc\n"
        "\tpublic void X()\n"
        "\t{\n"
        "\t}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_triple_slash_after_a_multi_line_block_opened_after_the_attribute_is_blocked():
    text = (
        "[Fact] /* a\n"
        "*/ /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_javadoc_after_code_on_its_own_start_line_does_not_bind_an_attribute():
    text = (
        "[Fact]\n"
        "int y = 1; /** doc */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_backward_fallback_match_stops_the_walk_at_the_member_boundary():
    text = (
        "[Fact] // c\n"
        "/* a */ int q; /* b */ [Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_backward_attribute_binds_when_followed_by_a_trailing_block_comment():
    text = (
        "/* a */ int q; /* b */ [Fact] /* c */\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_backward_fallback_uses_the_multiline_leading_blocks_close_line():
    text = (
        "/* a\n"
        "*/ int q; /* b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_backward_fallback_ignores_block_comment_markers_inside_an_attribute_argument_string():
    text = (
        '/* a */ int q; /* b */ [Fact, Trait("k", "/* */")]\n'
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_backward_fallback_does_not_look_past_a_line_comment_for_a_close():
    text = (
        "/* a */ int q; // /* b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_backward_fallback_finds_a_close_past_a_quote_in_a_multiline_comments_tail_line():
    text = (
        "/* a\n"
        'b " */ int q; /* c */ [Fact]\n'
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_backward_fallback_finds_a_close_past_a_url_in_a_multiline_comments_tail_line():
    text = (
        "/* a\n"
        "see http://x */ int q; /* c */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_backward_fallback_binds_every_attribute_after_the_first_matching_close():
    text = (
        "/* a */ int q; /* b */ [Fact] /* c */ [Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_backward_fallback_skips_a_close_whose_attribute_is_followed_by_code():
    text = (
        "/* a */ int q; /* b */ [Obsolete] int r; /* c */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_same_named_documented_test_methods_in_different_classes_are_each_blocked():
    text = (
        "class A\n"
        "{\n"
        "    [Fact]\n"
        "    /// doc\n"
        "    public void T()\n"
        "    {\n"
        "    }\n"
        "}\n"
        "\n"
        "class B\n"
        "{\n"
        "    [Fact]\n"
        "    /// doc\n"
        "    public void T()\n"
        "    {\n"
        "    }\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [
        (_csharp_test_doc_violation("T", 5), (5, 5)),
        (_csharp_test_doc_violation("T", 14), (14, 14)),
    ]


def test_trailing_triple_slash_on_method_line_does_not_duplicate_or_suppress_the_doc_violation():
    text = (
        "[Fact]\n"
        "/// doc\n"
        "public void X() /// trailing\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_bare_triple_slash_at_end_of_file_is_a_doc_comment_span():
    assert guard._csharp_comment_spans("///") == [("doc", 0, 0, "", None)]




def test_four_slash_comment_with_an_external_id_is_not_blocked():
    text = "//// see JIRA-123\npublic void DoesAThing()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/src/Thing.cs")

    assert violations == []


def test_triple_slash_after_code_with_an_external_id_is_still_blocked():
    text = "int y; /// see JIRA-123\npublic void DoesAThing()\n{\n}\n"

    violations = guard.find_csharp_blocking_violations(text, "/repo/src/Thing.cs")

    assert violations == [(guard._external_id_violation("JIRA-123", "an XML doc comment", 1), (1, 1))]


def test_triple_star_open_is_a_plain_block_comment_not_a_doc_comment():
    assert guard._csharp_comment_spans("/*** x */") == [("block", 0, 0, "** x ", 7)]


def test_attribute_before_a_triple_star_block_comment_does_not_name_the_method():
    text = (
        "[Fact]\n"
        "/*** x */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_attribute_trailing_field_code_and_a_block_comment_on_the_line_above_the_doc_names_the_method():
    text = (
        "int q; /* b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_attribute_after_a_leading_block_comments_close_and_field_code_on_the_line_above_the_doc_names_the_method():
    text = (
        "/* a */ int q; [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_attribute_after_a_multi_line_block_comments_close_on_the_line_above_the_doc_names_the_method():
    text = (
        "/* a */ int q; /* b\n"
        "c */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_doc_before_field_code_with_a_trailing_attribute_documents_the_field_not_a_later_method():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '/* a */ int q; /* b */ [Fact, Trait("k", "/* */")]\n'
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_before_a_field_decorated_with_a_trait_attribute_argument_does_not_name_the_field_trait():
    text = (
        "/// doc\n"
        '[Fact] int q; [Fact, Trait("k", "v")]\n'
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_backward_walk_does_not_treat_an_attribute_still_inside_an_open_block_comment_as_real():
    text = (
        "/* a\n"
        "[Fact]\n"
        "/* a */ /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_attribute_after_two_code_members_on_the_line_above_the_doc_names_the_method():
    text = (
        "[Fact] /* a\n"
        "/* a */ int q; /* b */ [Obsolete] int r; /* c */ [Fact]\n"
        "/// a\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_javadoc_followed_by_a_multi_line_trailing_block_comment_then_the_attribute_names_the_method():
    text = (
        "/** d */ /* x\n"
        " y */ [Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_javadoc_followed_by_a_multi_line_trailing_block_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/** d */ /* x\n"
        " y */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_attribute_before_code_on_the_close_line_with_adjacent_block_comment_does_not_bind_through_a_deeper_attribute_group():
    text = (
        "[Fact] /* a\n"
        "/* a */ int q; /* b */ [Obsolete]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_attribute_before_code_on_the_close_line_does_not_bind_through_a_deeper_attribute_group():
    text = (
        "[Fact] /* a\n"
        "*/ int q; /* b */ [Obsolete]\n"
        "/// a\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_backward_walk_finds_the_real_attribute_when_it_leads_an_open_block_that_closes_on_the_next_mixed_line():
    text = (
        "[Fact] /* a\n"
        "/* a */ int q; /* b */ [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_attribute_and_trailing_doc_comment_on_one_line_names_the_next_method():
    text = (
        "[Fact] /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 2), (2, 2))]


def test_attribute_above_code_that_opens_an_unclosed_block_binds_to_that_code_not_the_method():
    text = (
        "[Fact] // c\n"
        "int y; /* a\n"
        "b */\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_two_adjacent_multi_line_javadoc_blocks_after_the_attribute_are_blocked():
    text = (
        "[Fact]\n"
        "/** d\n"
        " e */\n"
        "/** d\n"
        " e */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 6), (6, 6))]


def test_code_after_a_single_line_javadocs_close_ends_the_member_and_is_not_blocked():
    text = (
        "[Fact]\n"
        "/** d */ int y;\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_attribute_after_a_multi_line_javadocs_close_on_its_own_line_names_the_method():
    text = (
        "/** d\n"
        "*/ [Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_multi_line_javadoc_followed_by_a_longer_triple_slash_line_names_the_method():
    text = (
        "/** d\n"
        " */\n"
        "/// doc\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_javadoc_followed_by_a_longer_triple_slash_line_then_the_attribute_names_the_method():
    text = (
        "/** d */\n"
        "/// a longer doc\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_attribute_before_a_javadoc_followed_by_a_longer_triple_slash_line_names_the_method():
    text = (
        "[Fact]\n"
        "/** d */\n"
        "/// a longer doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_attribute_before_a_javadoc_followed_by_a_trailing_line_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/** d */ // c\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_attribute_before_a_javadoc_followed_by_a_trailing_block_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/** d */ /* b */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_javadoc_followed_by_a_trailing_line_comment_then_the_attribute_names_the_method():
    text = (
        "/** d */ // c\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_multi_line_javadoc_followed_by_a_trailing_line_comment_names_the_method():
    text = (
        "[Fact]\n"
        "/** d\n"
        " e */ // c\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_javadoc_followed_by_another_adjacent_javadoc_on_the_same_line_names_the_method():
    text = (
        "[Fact]\n"
        "/** a */ /** a */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_javadoc_after_an_unrelated_block_comment_with_matching_tail_text_names_the_method():
    text = (
        "[Fact]\n"
        "/* * d */ /** d */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_javadoc_after_an_unrelated_block_comment_and_code_with_matching_tail_text_names_the_method():
    text = (
        "/* * d */ int y; /** d */\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_double_slash_inside_a_string_literal_before_the_attribute_still_names_the_method():
    text = (
        'var s = "//"; [Fact]\n'
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_attribute_inside_a_trailing_block_comment_on_the_line_above_the_doc_is_not_real():
    text = (
        "int q; /* [Fact] /* */\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_indexer_bracket_before_the_attribute_still_names_the_method():
    text = (
        "int q = a[0]; [Fact]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_javadoc_before_a_decorated_field_with_a_trait_attribute_argument_documents_the_field():
    text = (
        '/** d */ [Fact] int q; [Trait("k", "v")]\n'
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_javadoc_before_an_attribute_and_method_all_on_the_javadocs_own_line_names_the_method():
    text = (
        "/** d */ [Fact] public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 1), (1, 1))]


def test_attribute_followed_by_code_before_a_trailing_doc_on_the_same_line_does_not_bind_the_attribute():
    text = (
        "[Fact] int q; /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_multi_line_attribute_group_before_the_doc_is_blocked():
    text = (
        "[Theory,\n"
        "InlineData(1)]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_a_preprocessor_wrapped_attribute_before_the_doc_is_blocked():
    text = (
        "#if DEBUG\n"
        "[Fact]\n"
        "#endif\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


_ORACLE_TEST = {"Fact"}


def _roslyn_oracle_expected(text):
    code = []
    docs = []
    i, line, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if text.startswith("///", i) and not text.startswith("////", i):
            docs.append((len(code), line))
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            if text[i + 2:i + 3] == "*" and text[i + 3:i + 4] not in ("*", "/"):
                docs.append((len(code), line))
            j = text.find("*/", i + 2)
            if j == -1:
                i = n
                continue
            line += text.count("\n", i, j)
            i = j + 2
            code.append((" ", line))
            continue
        if c == '"':
            j = text.find('"', i + 1)
            j = n - 1 if j == -1 else j
            for k in range(i, j + 1):
                code.append((text[k] if text[k] != "\n" else " ", line))
            i = j + 1
            continue
        code.append((c, line))
        i += 1
    s = "".join(ch for ch, _ in code)
    matches = list(re.finditer(r"public void (A|X)\(\)", s))
    if not any(m.group(1) == "X" for m in matches):
        return None
    out = []
    for m in matches:
        found = _roslyn_oracle_one(s, code, docs, m.start(), m.group(1))
        if found and found[0] not in out:
            out.append(found[0])
    return sorted(out)


def _roslyn_oracle_one(s, code, docs, p, name):
    row = code[p][1] + 1
    k = p
    attrs = []
    while True:
        while k > 0 and s[k - 1].isspace():
            k -= 1
        if k > 0 and s[k - 1] == "]":
            depth, j = 0, k - 1
            while j >= 0:
                if s[j] == "]":
                    depth += 1
                elif s[j] == "[":
                    depth -= 1
                if depth == 0:
                    break
                j -= 1
            if j < 0:
                break
            attrs.append(s[j:k])
            k = j
        else:
            break
    start = k
    joined = " ".join(attrs)
    names = re.findall(r"\[\s*([A-Za-z_][\w.]*)", joined) + re.findall(r",\s*([A-Za-z_][\w.]*)", joined)
    is_test = any(attribute_name.split(".")[-1].removesuffix("Attribute") in _ORACLE_TEST for attribute_name in names)
    has_doc = any(start <= code_index <= p for code_index, _ in docs)
    return [(name, row)] if is_test and has_doc else []


_ORACLE_GENERATOR_LINES = [
    "[Fact]", "[Obsolete]", '[Trait("x","y")]', "/* c */", "/* a", "b */", "b */ [Fact]", "/* c */ [Fact]",
    "/* c */ [Obsolete]", "// c", "/// doc", "/// a", "", "int y;", "public void A() { }",
    "[Fact] public void A() { }", "/* c */ int y;", "[Fact] /* a", "/* a */ /* b */", "/* a */ /* b */ [Fact]",
    "/* a */ /* b */ [Obsolete]", "/* a */ /* b */ /* c */", "/* a */ /* b */ /* c */ [Fact]", "/* a */ /* b",
    "[Fact] // c", "[Obsolete] // c", "// c /* x */", "// http://x", "/* a */ // c", "//// c", "[Fact] /// x",
    "[Fact] //// c", "int y; /// x", "/* a */ /// x", "public void A() /// t", "/* a */ int q; /* b */ [Fact]",
    "/* a */ int q; /* b */ [Obsolete]", "/* a */ [Fact] /* b */ int q;", "/* a */ int q; /* b */ [Fact] /* c */",
    "/* a */ int q; // /* b */ [Fact]", "/* a */ int q; /* b */ [Obsolete] [Fact]",
    "/* a */ int q; /* b */ [Fact] // c", '/* a */ int q; /* b */ [Fact, Trait("k", "/* */")]',
    "/* a */ int q; /* b */ [Fact] /* c */ [Obsolete]", "/* a */ int q; /* b */ [Obsolete] int r; /* c */ [Fact]",
    "*/ int q; /* b */ [Fact]", "*/ int q; /* b */ [Obsolete]", "/** d */", "/** d", "*/", "*/ /// x",
    "\t/// doc", "\t[Fact]", "/** d */ // c", "/** d */ /* b */", "/** d */ int y;", "/** d */ [Fact]",
    "/** d */ [Obsolete]", "e */ // c", "e */ [Fact]", "e */ int y;", "/*** x */", "/***",
    '[Fact, Trait("k", "v")]', "int y; /* a", "[Fact] /** d */", "/** d */ [Fact] // c",
    '/** d */ [Trait("k", "[x]")]',
]


def _oracle_generator_cases():
    for k in (1, 2):
        for combo in itertools.product(_ORACLE_GENERATOR_LINES, repeat=k):
            yield list(combo)
    rng = random.Random(66)
    for _ in range(3000):
        yield [rng.choice(_ORACLE_GENERATOR_LINES) for _ in range(rng.randint(4, 7))]


def _is_syntactically_closed(text):
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = len(text) if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                return False
            i = j + 2
            continue
        if text.startswith("*/", i):
            return False
        i += 1
    return True


_ORACLE_KNOWN_INVALID_CODE_GAPS = frozenset({
    (
        '/* a */ /* b */ [Fact]\n/* a\npublic void A() /// t\n*/ /// x\npublic void A() /// t\n'
        '/* a */ /* b */ /* c */ [Fact]\n[Fact, Trait("k", "v")]\npublic void X()\n{\n}\n'
    ),
    (
        '/* a */ /* b */ [Obsolete]\n[Obsolete]\n/* a */ int q; // /* b */ [Fact]\npublic void A() /// t\n/* c */\n'
        '[Fact] //// c\npublic void X()\n{\n}\n'
    ),
    (
        '/* a */ int q; /* b */ [Fact] /* c */\npublic void A() /// t\n/** d */ [Fact]\n/* c */ [Obsolete]\n'
        'public void X()\n{\n}\n'
    ),
    (
        '/* a */ int q; /* b */ [Obsolete] [Fact]\npublic void A() /// t\n/* a */ /* b */\n[Fact] public void A() { }\n'
        '/* c */ [Fact]\n/* a */ /* b */ [Fact]\n/* a */ /* b */ /* c */\npublic void X()\n{\n}\n'
    ),
    (
        '/* a */ int q; /* b */ [Obsolete] [Fact]\npublic void A() /// t\n[Fact] /* a\n/** d */\n/*** x */\n'
        'public void X()\n{\n}\n'
    ),
    (
        '/** d */ // c\n/** d */ [Fact] // c\n/** d */ [Fact] // c\n/* c */ [Fact]\npublic void A() /// t\n'
        '[Trait("x","y")]\n[Fact, Trait("k", "v")]\npublic void X()\n{\n}\n'
    ),
    (
        '/** d */ [Fact] // c\n\t/// doc\n/* a */ int q; /* b */ [Fact]\n/* a */ /* b */ /* c */\npublic void A() /// t\n'
        '/* a */ /* b */\n[Fact] //// c\npublic void X()\n{\n}\n'
    ),
    (
        '// c\n/* a */ int q; // /* b */ [Fact]\n/// a\n\t/// doc\npublic void A() /// t\n[Trait("x","y")]\n'
        '[Fact] public void A() { }\npublic void X()\n{\n}\n'
    ),
    '//// c\npublic void A() /// t\n/* c */ [Fact]\n/** d */ /* b */\npublic void X()\n{\n}\n',
    (
        '[Fact]\nint y; /// x\n/* a */ int q; /* b */ [Fact] // c\n/* a */ int q; /* b */ [Obsolete]\n'
        '/* a */ [Fact] /* b */ int q;\npublic void A() /// t\n\t[Fact]\npublic void X()\n{\n}\n'
    ),
    (
        '[Fact] public void A() { }\n\n[Fact] /* a\n/* a */ int q; /* b */ [Obsolete] [Fact]\npublic void A() /// t\n'
        '/* a */ /* b */ [Fact]\npublic void X()\n{\n}\n'
    ),
    'public void A() /// t\n\t[Fact]\n//// c\n[Fact] // c\npublic void X()\n{\n}\n',
    'public void A() /// t\n\t[Fact]\npublic void X()\n{\n}\n',
    'public void A() /// t\n/* a */ /* b */ /* c */ [Fact]\npublic void X()\n{\n}\n',
    'public void A() /// t\n/* a */ /* b */ [Fact]\npublic void X()\n{\n}\n',
    'public void A() /// t\n/* c */ [Fact]\npublic void X()\n{\n}\n',
    'public void A() /// t\n/** d */ [Fact]\npublic void X()\n{\n}\n',
    'public void A() /// t\n/** d */ [Fact] // c\n/** d\n/** d */ // c\n//// c\npublic void X()\n{\n}\n',
    'public void A() /// t\n/** d */ [Fact] // c\npublic void X()\n{\n}\n',
    'public void A() /// t\n[Fact, Trait("k", "v")]\npublic void X()\n{\n}\n',
    'public void A() /// t\n[Fact]\npublic void X()\n{\n}\n',
    'public void A() /// t\n[Fact] /** d */\npublic void X()\n{\n}\n',
    (
        'public void A() /// t\n[Fact] // c\n/*** x */\n/** d */ /* b */\n//// c\n/* a */ /* b */ [Obsolete]\n'
        'public void X()\n{\n}\n'
    ),
    'public void A() /// t\n[Fact] // c\npublic void X()\n{\n}\n',
    'public void A() /// t\n[Fact] /// x\npublic void X()\n{\n}\n',
    'public void A() /// t\n[Fact] //// c\npublic void X()\n{\n}\n',
    'public void A() /// t\n[Fact] public void A() { }\npublic void X()\n{\n}\n',
    '/** d */ [Fact]\npublic void A() /// t\npublic void X()\n{\n}\n',
    '/** d */ [Fact] // c\npublic void A() /// t\npublic void X()\n{\n}\n',
    '[Fact] /** d */\npublic void A() /// t\npublic void X()\n{\n}\n',
    '[Fact] /// x\npublic void A() /// t\npublic void X()\n{\n}\n',
    (
        '/* a */ int q; /* b */ [Fact] // c\n/// a\n\t[Fact]\n/* a */ /* b */ /* c */ [Fact]\n'
        'public void A() /// t\npublic void X()\n{\n}\n'
    ),
    (
        '//// c\n[Fact] //// c\n/*** x */\n/** d */ [Fact] // c\n/* a */ /* b */ [Fact]\n'
        'public void A() /// t\npublic void X()\n{\n}\n'
    ),
    (
        '[Fact] public void A() { }\n/* a */ int q; /* b */ [Obsolete] [Fact]\n'
        '/* a */ int q; /* b */ [Obsolete] int r; /* c */ [Fact]\n[Fact] /// x\n'
        'public void A() /// t\npublic void X()\n{\n}\n'
    ),
    (
        '[Trait("x","y")]\n/* a */ int q; /* b */ [Fact] /* c */\n// c /* x */\n[Obsolete] // c\n'
        '/** d */ [Trait("k", "[x]")]\npublic void A() /// t\n[Obsolete] // c\npublic void X()\n{\n}\n'
    ),
})


_ORACLE_VIOLATION_NAME = re.compile(r"BLOCKED - '([^']*)'")


def _public_api_violations(text):
    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")
    return sorted((_ORACLE_VIOLATION_NAME.search(message).group(1), span[0]) for message, span in violations)


def test_matches_the_roslyn_oracle_over_the_seeded_generator_corpus():
    checked = 0
    disagreements = []
    for body in _oracle_generator_cases():
        text = "\n".join(body + ["public void X()", "{", "}"]) + "\n"
        if not _is_syntactically_closed(text):
            continue
        oracle_result = _roslyn_oracle_expected(text)
        if oracle_result is None:
            continue
        checked += 1
        actual = _public_api_violations(text)
        if actual != oracle_result:
            disagreements.append(text)

    assert set(disagreements) == _ORACLE_KNOWN_INVALID_CODE_GAPS
    assert checked > 4000


def test_a_method_without_a_body_before_an_attribute_is_a_known_gap_on_invalid_code():
    text = "public void A() /// t\n[Fact]\npublic void X()\n{\n}\n"

    assert guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs") == []


def test_doc_above_code_before_the_method_does_not_bind_the_attribute_above_the_code():
    text = (
        "[Fact]\n"
        "/// doc\n"
        "int q; public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_doc_above_a_mixed_comment_and_code_line_with_a_trait_argument_does_not_bind_forward():
    text = (
        "[Fact]\n"
        "/// doc\n"
        '/* a */ int q; /* b */ [Fact, Trait("k", "/* */")] public void X()\n'
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_method_signature_split_across_two_lines_still_finds_the_declared_name():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "public void\n"
        "X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_javadoc_before_an_attribute_then_code_then_another_attribute_documents_the_field():
    text = (
        '/** d */ [Fact] int q; [Trait("k", "v")] public void X()\n'
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_attribute_inside_an_open_javadoc_does_not_bind_to_the_method_after_the_javadoc_closes():
    text = (
        "/** d\n"
        "[Fact]\n"
        "*/ /// x\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_javadoc_before_code_on_its_own_line_documents_that_code_not_a_later_doc_comment():
    text = (
        "[Fact]\n"
        "/** d */ int y;\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_attribute_then_trailing_javadoc_on_one_line_is_blocked():
    text = (
        "[Fact] /** d */\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 2), (2, 2))]


def test_an_attribute_then_trailing_triple_slash_then_a_leading_triple_slash_line_is_blocked():
    text = (
        "[Fact] /// x\n"
        "/// a\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_a_multi_line_block_comment_then_attribute_then_doc_is_blocked():
    text = (
        "/** d\n"
        "*/ [Fact]\n"
        "/// a\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_a_wrapped_member_data_attribute_argument_names_the_method_after_the_doc():
    text = (
        "[Theory]\n"
        "[MemberData(nameof(Cases),\n"
        "MemberType = typeof(Data))]\n"
        "/// doc\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_preprocessor_lines_between_the_attribute_and_the_signature_are_skipped():
    text = (
        "/// doc\n"
        "[Fact]\n"
        "#pragma warning disable CS1591\n"
        "public void X()\n"
        "{\n"
        "}\n"
        "#pragma warning restore CS1591\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_a_bracket_inside_an_attribute_argument_array_does_not_end_the_attribute_section():
    text = (
        "/// doc\n"
        "[InlineData(new int[] { 1 })]\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_an_obsolete_attribute_string_argument_mentioning_fact_does_not_mark_the_helper_as_a_test():
    text = (
        '/// Use the [Fact] based suite instead.\n'
        '[Obsolete("Use the [Fact] based suite")]\n'
        "public void OldHelper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_attribute_target_specifier_before_the_attribute_name_is_still_recognised():
    text = (
        "/// doc\n"
        "[method: Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


_METAMORPHIC_BASE_PROGRAMS = [
    ["/// <summary>doc</summary>", "[Fact]", "public void X()", "{", "}"],
    ["[Fact]", "/// doc", "public void X()", "{", "}"],
    ["/// doc", "[Theory]", '[InlineData("a")]', "public void X(string a)", "{", "}"],
    ["[Theory]", "/// doc", "[InlineData(1)]", "public void X(int a)", "{", "}"],
    ["/** doc */", "[Test]", "public async Task X()", "{", "}"],
    ["/// doc", "[Fact]", "public void X() => Assert.True(true);"],
    ["/// doc", "public void Helper()", "{", "}", "[Fact]", "public void X()", "{", "}"],
]
_METAMORPHIC_TRIVIA_INSERTS = [
    [""],
    ["// note"],
    ["/* note */"],
    ["//// banner"],
    ["/* multi", "   line */"],
]

_METAMORPHIC_BASE_EXPECTED = [
    [(3, "X")],
    [(3, "X")],
    [(4, "X")],
    [(4, "X")],
    [(3, "X")],
    [(3, "X")],
    [],
]


def _violation_name_rows(text):
    violations = guard.find_csharp_blocking_violations(text, "/repo/T.cs")
    return sorted((row, _ORACLE_VIOLATION_NAME.search(message).group(1)) for message, (row, _end) in violations)


def test_metamorphic_trivia_insertion_shifts_violation_rows_but_does_not_change_them():
    checked = 0
    for base, base_expected in zip(_METAMORPHIC_BASE_PROGRAMS, _METAMORPHIC_BASE_EXPECTED, strict=True):
        assert _violation_name_rows("\n".join(base) + "\n") == base_expected
        for gap in range(1, len(base)):
            for trivia in _METAMORPHIC_TRIVIA_INSERTS:
                lines = base[:gap] + trivia + base[gap:]
                got = _violation_name_rows("\n".join(lines) + "\n")
                expected = [(row + len(trivia), name) if row > gap else (row, name) for row, name in base_expected]
                checked += 1
                assert got == expected, (lines, got, expected)

    assert checked > 100


def test_metamorphic_wrapping_an_attribute_line_in_an_if_directive_does_not_change_the_result():
    base = ["/// doc", "[Theory]", '[InlineData("a", 2)]', "public void X(string a, int b)", "{", "}"]
    base_text = "\n".join(base) + "\n"
    want = [(4, "X")]
    assert _violation_name_rows(base_text) == want
    checked = 0
    for li, line in enumerate(base):
        if not line.startswith("["):
            continue
        lines = base[:li] + ["#if NET8_0", line, "#endif"] + base[li + 1:]
        got = _violation_name_rows("\n".join(lines) + "\n")
        shifted = [(row + 2 if row > li else row, name) for row, name in want]
        checked += 1
        assert got == shifted, lines

    assert checked > 0


def test_metamorphic_line_break_inside_a_wrapped_attribute_argument_does_not_change_the_result():
    base = ["[Theory]", '[MemberData(nameof(Cases), MemberType = typeof(D))]', "/// doc",
            "public void X(int a)", "{", "}"]
    base_text = "\n".join(base) + "\n"
    want = [(4, "X")]
    assert _violation_name_rows(base_text) == want
    checked = 0
    for li, line in enumerate(base):
        if not line.startswith("["):
            continue
        for match in re.finditer(r"[(,]", line):
            k = match.end()
            lines = base[:li] + [line[:k], "    " + line[k:].lstrip()] + base[li + 1:]
            got = _violation_name_rows("\n".join(lines) + "\n")
            shifted = [(row + 1 if row > li else row, name) for row, name in want]
            checked += 1
            assert got == shifted, lines

    assert checked > 0


def test_metamorphic_crlf_line_endings_do_not_change_which_row_is_flagged():
    checked = 0
    for base, expected in zip(_METAMORPHIC_BASE_PROGRAMS, _METAMORPHIC_BASE_EXPECTED, strict=True):
        text = "\r\n".join(base) + "\r\n"
        got = _violation_name_rows(text)
        checked += 1
        assert got == expected, (base, got, expected)

    assert checked == len(_METAMORPHIC_BASE_PROGRAMS)


def test_crlf_before_a_trait_and_fact_still_finds_the_doc_comment():
    text = '/// d\r\n[Trait("a", "b")]\r\n[Fact]\r\npublic void X()\r\n{\r\n}\r\n'

    violations = guard.find_csharp_blocking_violations(text, "/repo/T.cs")

    assert violations == [(_csharp_test_doc_violation("X", 4), (4, 4))]


def test_metamorphic_reindenting_every_line_does_not_change_which_row_is_flagged():
    checked = 0
    for base, expected in zip(_METAMORPHIC_BASE_PROGRAMS, _METAMORPHIC_BASE_EXPECTED, strict=True):
        text = "\n".join("        " + line for line in base) + "\n"
        got = _violation_name_rows(text)
        checked += 1
        assert got == expected, (base, got, expected)

    assert checked == len(_METAMORPHIC_BASE_PROGRAMS)


def test_metamorphic_wrapping_in_a_namespace_and_class_shifts_rows_by_the_wrapper_line_count():
    wrapper_prefix = ["namespace N", "{", "    class C", "    {"]
    wrapper_suffix = ["    }", "}"]
    checked = 0
    for base, expected in zip(_METAMORPHIC_BASE_PROGRAMS, _METAMORPHIC_BASE_EXPECTED, strict=True):
        lines = wrapper_prefix + ["    " + line for line in base] + wrapper_suffix
        got = _violation_name_rows("\n".join(lines) + "\n")
        shifted = [(row + len(wrapper_prefix), name) for row, name in expected]
        checked += 1
        assert got == shifted, (base, got, shifted)

    assert checked == len(_METAMORPHIC_BASE_PROGRAMS)


def test_metamorphic_a_block_comment_prefix_on_every_line_does_not_change_the_result():
    checked = 0
    for base, expected in zip(_METAMORPHIC_BASE_PROGRAMS, _METAMORPHIC_BASE_EXPECTED, strict=True):
        lines = [f"/* c */ {line}" for line in base]
        got = _violation_name_rows("\n".join(lines) + "\n")
        checked += 1
        assert got == expected, (base, got, expected)

    assert checked == len(_METAMORPHIC_BASE_PROGRAMS)


def test_method_name_starting_with_an_underscore_is_recognised():
    text = (
        "/// d\n"
        "[Fact]\n"
        "public void _X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("_X", 3), (3, 3))]


def test_verbatim_method_name_strips_the_at_sign():
    text = (
        "/// d\n"
        "[Fact]\n"
        "public void @X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_a_newline_inside_a_verbatim_string_literal_still_counts_toward_the_row():
    text = (
        'const string S = @"a\n'
        'b";\n'
        "/// d\n"
        "[Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 5), (5, 5))]


def test_an_empty_block_comment_is_not_mistaken_for_a_doc_comment():
    text = (
        "[Fact]\n"
        "/**/\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_attribute_argument_that_looks_like_a_nested_attribute_name_is_not_bound_as_one():
    text = (
        "/// d\n"
        "[InlineData(1, Fact)]\n"
        "public void Helper()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_field_initializer_is_not_mistaken_for_a_method_declaration():
    text = (
        "/// d\n"
        "[Fact]\n"
        "public Func<int> F = Make();\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_an_expression_bodied_property_is_not_mistaken_for_a_method_declaration():
    text = (
        "/// d\n"
        "[Fact]\n"
        "public int P => Compute();\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_property_with_an_accessor_body_is_not_mistaken_for_a_method_declaration():
    text = (
        "/// d\n"
        "[Fact]\n"
        "public int P { get { return Compute(); } }\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_bracket_inside_a_statement_body_does_not_open_an_attribute_section():
    text = (
        "void M()\n"
        "{\n"
        "    var v = map /// d\n"
        "        [Fact].Get(1);\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_a_second_attribute_name_after_a_comma_in_the_same_section_is_recognised():
    text = (
        "/// d\n"
        "[Obsolete, Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_a_verbatim_attribute_name_strips_the_at_sign():
    text = (
        "/// d\n"
        "[@Fact]\n"
        "public void X()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == [(_csharp_test_doc_violation("X", 3), (3, 3))]


def test_a_lone_at_sign_with_nothing_after_it_is_not_a_declared_name():
    text = (
        "/// d\n"
        "[Fact]\n"
        "public void @ ()\n"
        "{\n"
        "}\n"
    )

    violations = guard.find_csharp_blocking_violations(text, "/repo/Tests/ThingTests.cs")

    assert violations == []


def test_thousands_of_unterminated_interpolation_hole_openers_do_not_recurse():
    text = 'x = $@"{\n' * 3000

    spans, tokens, doc_anchors = guard._csharp_lex(text)

    assert spans == []
    assert [t.text for t in tokens] == ["x", "=", '"']
    assert all(t.row == 0 for t in tokens)


def test_thousands_of_unterminated_interpolation_hole_openers_on_directive_lines_do_not_recurse():
    text = '#if x = $@"{\n' * 10_000 + "// tail\n"

    spans, tokens, doc_anchors = guard._csharp_lex(text)

    assert spans == [("line", 10_000, 10_000, " tail", None)]


_CSHARP_SOUP_SEED = 20261005
_CSHARP_SOUP_CASE_COUNT = 20000
_CSHARP_SOUP_ATOMS = (
    "$", "$$", "@", '"', '"""', "{", "}", "{{", "}}", "\\", "'",
    "\n", "\r\n", "//", "/*", "*/", "#", "if", "x", "ab", " ", "1",
)


def _csharp_soup_cases(seed, count):
    rng = random.Random(seed)
    for _ in range(count):
        atom_count = rng.randint(1, 40)
        yield "".join(rng.choice(_CSHARP_SOUP_ATOMS) for _ in range(atom_count))


def _csharp_soup_unescaped_newline_limit(text, start):
    n = len(text)
    i = start
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == "\n":
            return i
        i += 1
    return n


def test_csharp_lex_never_raises_on_seeded_char_soup():
    for index, text in enumerate(_csharp_soup_cases(_CSHARP_SOUP_SEED, _CSHARP_SOUP_CASE_COUNT)):
        try:
            guard._csharp_lex(text)
        except Exception as error:
            pytest.fail(f"seed index {index} raised {error!r} on {text!r}")


def test_csharp_lex_span_rows_and_close_columns_stay_within_the_text():
    for index, text in enumerate(_csharp_soup_cases(_CSHARP_SOUP_SEED, _CSHARP_SOUP_CASE_COUNT)):
        lines = text.split("\n")
        line_count = len(lines)
        spans, _tokens, _doc_anchors = guard._csharp_lex(text)
        for _kind, start_li, end_li, _content, close_col in spans:
            assert 0 <= start_li <= end_li < line_count, f"seed index {index} span rows oob: {text!r}"
            if close_col is not None:
                assert 0 <= close_col <= len(lines[end_li]), f"seed index {index} close_col oob: {text!r}"


def test_csharp_lex_tokens_stay_within_the_text_and_in_non_decreasing_row_order():
    for index, text in enumerate(_csharp_soup_cases(_CSHARP_SOUP_SEED, _CSHARP_SOUP_CASE_COUNT)):
        line_count = text.count("\n") + 1
        _spans, tokens, _doc_anchors = guard._csharp_lex(text)
        last_row = -1
        for token in tokens:
            assert 0 <= token.row < line_count, f"seed index {index} token row oob: {text!r}"
            assert token.row >= last_row, f"seed index {index} token rows went backwards: {text!r}"
            last_row = token.row


def test_csharp_try_skip_literal_end_is_in_bounds_and_within_its_line_for_plain_strings():
    for index, text in enumerate(_csharp_soup_cases(_CSHARP_SOUP_SEED, _CSHARP_SOUP_CASE_COUNT)):
        n = len(text)
        for position in range(n):
            end = guard._csharp_try_skip_literal(text, position)
            if end is None:
                continue
            assert position < end <= n, f"seed index {index} pos {position} literal end oob: {text!r}"
            if text[position] != '"':
                continue
            quote_run = 1
            while position + quote_run < n and text[position + quote_run] == '"':
                quote_run += 1
            if quote_run >= 3:
                continue
            limit = _csharp_soup_unescaped_newline_limit(text, position)
            assert end <= limit, f"seed index {index} pos {position} literal crossed a line: {text!r}"


def test_csharp_lex_is_idempotent_under_crlf_line_endings_outside_quoted_literal_edge_cases():
    checked = 0
    for index, text in enumerate(_csharp_soup_cases(_CSHARP_SOUP_SEED, _CSHARP_SOUP_CASE_COUNT)):
        if "'" in text or "\\\n" in text:
            continue
        checked += 1
        spans, tokens, _doc_anchors = guard._csharp_lex(text)
        crlf_spans, crlf_tokens, _crlf_doc_anchors = guard._csharp_lex(text.replace("\n", "\r\n"))
        rows = [(kind, start_li, end_li, close_col) for kind, start_li, end_li, _content, close_col in spans]
        crlf_rows = [
            (kind, start_li, end_li, close_col) for kind, start_li, end_li, _content, close_col in crlf_spans
        ]
        assert rows == crlf_rows, f"seed index {index} span rows changed under CRLF: {text!r}"
        token_rows = [(token.text, token.row) for token in tokens]
        crlf_token_rows = [(token.text, token.row) for token in crlf_tokens]
        assert token_rows == crlf_token_rows, f"seed index {index} token rows changed under CRLF: {text!r}"

    assert checked > 5000


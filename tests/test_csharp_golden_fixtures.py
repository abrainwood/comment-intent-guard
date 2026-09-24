import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "csharp"


def _load_module():
    spec = importlib.util.spec_from_file_location("comment_intent_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_module()


GOLDEN_ISSUE_REFERENCE_CS = """\
public class Widget
{
    public void Fix()
    {
        // see #482 for the root cause
        DoWork();
    }
}
"""

GOLDEN_EVIDENCE_MARKER_CS = """\
public class Widget
{
    public void Fix()
    {
        // patched on 2026-02-14 after the timeout bumped past 500ms
        DoWork();
    }
}
"""

GOLDEN_EXTERNAL_ID_CS = """\
public class Widget
{
    /// <summary>
    /// Validates the input.
    /// Fixes JIRA-4821 by validating the input before dispatch.
    /// </summary>
    public void Validate()
    {
    }
}
"""

GOLDEN_TEST_DOCSTRING_CS = """\
public class WidgetTests
{
    /// <summary>Checks that the widget validates its input.</summary>
    [Fact]
    public void ChecksInputValidation()
    {
    }
}
"""

GOLDEN_COMMENT_RUN_CS = """\
public class Widget
{
    // step one
    // step two
    // step three
    // step four
    // step five
    public void Fix()
    {
    }
}
"""

GOLDEN_OVERSIZE_DOC_COMMENT_CS = "public class Widget\n{\n    /// <summary>\n" + "".join(
    f"    /// line {i}\n" for i in range(1, guard.DOCSTRING_LINE_THRESHOLD + 1)
) + "    /// </summary>\n    public void Fix()\n    {\n    }\n}\n"


def test_issue_reference_fixture_is_blocked():
    violations = guard.find_csharp_issue_reference_violations(GOLDEN_ISSUE_REFERENCE_CS)

    assert violations == [(
        "BLOCKED - Comment near line 5 contains an issue reference. That's a "
        "pointer that rots - name the behaviour instead; the issue lives in "
        "the commit message or PR, not source.",
        (5, 5),
    )]


def test_evidence_marker_fixture_is_advisory():
    findings = guard.find_csharp_findings(GOLDEN_EVIDENCE_MARKER_CS)

    assert findings == [(
        "Comment near line 5 contains a date, measurement, or SHA. That looks "
        "like a review finding or timing discharged into source - move it to "
        "the issue, PR, or design doc.",
        (5, 5),
    )]


def test_external_id_fixture_is_blocked():
    violations = guard.find_csharp_blocking_violations(GOLDEN_EXTERNAL_ID_CS, "/repo/src/Widget.cs")

    assert violations == [(
        "BLOCKED - external id 'JIRA-4821' in an XML doc comment near line 3. "
        "Nobody reading the code knows what it means. Name the behaviour that "
        "breaks; the id belongs in the commit message so git blame still finds it.",
        (3, 6),
    )]


def test_test_docstring_fixture_is_blocked():
    violations = guard.find_csharp_blocking_violations(GOLDEN_TEST_DOCSTRING_CS, "/repo/Tests/WidgetTests.cs")

    assert violations == [(
        "BLOCKED - 'ChecksInputValidation' near line 5 opens with an XML doc "
        "comment. A test has no caller, so no test XML doc comment is an "
        "external quirk or an algorithm's requirement - every one is an alarm. "
        "Put it in the test name instead.",
        (5, 5),
    )]


def test_comment_run_fixture_is_advisory():
    findings = guard.find_csharp_findings(GOLDEN_COMMENT_RUN_CS)

    assert findings == [(
        "Comment run of 5 '//' lines (over the 4-line threshold) starting near "
        "line 3. Does this belong in the design doc or the issue/PR instead of "
        "source - or could a rename carry the meaning instead?",
        (3, 7),
    )]


def test_oversize_doc_comment_fixture_is_advisory():
    findings = guard.find_csharp_findings(GOLDEN_OVERSIZE_DOC_COMMENT_CS)

    assert findings == [(
        "XML doc comment spans 14 lines (over the 12-line threshold) starting "
        "near line 3. Does this belong in the design doc or the issue/PR "
        "instead of source?",
        (3, 16),
    )]


def test_clean_fixture_exercising_every_literal_form_has_no_findings():
    file_path = _FIXTURES_DIR / "clean.cs"
    text = file_path.read_text()

    blocking, advisory = guard._findings_for_file(str(file_path), text)

    assert blocking == []
    assert advisory == []


def test_clean_fixture_with_markers_inside_string_literals_has_no_findings():
    file_path = _FIXTURES_DIR / "markers_in_strings.cs"
    text = file_path.read_text()

    blocking, advisory = guard._findings_for_file(str(file_path), text)

    assert blocking == []
    assert advisory == []

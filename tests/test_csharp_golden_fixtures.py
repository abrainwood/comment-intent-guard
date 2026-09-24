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


# Violating golden fixtures stay inline, not on-disk .cs files, matching how
# this repo's Python golden fixtures are kept - a real violating file on disk
# would itself trip the guard's own --scan and CI gate.
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
    /// Fixes JIRA-4821 by validating the input before dispatch.
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

    assert any("issue reference" in message for message, _ in violations)


def test_evidence_marker_fixture_is_advisory():
    findings = guard.find_csharp_findings(GOLDEN_EVIDENCE_MARKER_CS)

    assert any("date, measurement, or SHA" in message for message, _ in findings)


def test_external_id_fixture_is_blocked():
    violations = guard.find_csharp_blocking_violations(GOLDEN_EXTERNAL_ID_CS, "/repo/src/Widget.cs")

    assert any("JIRA-4821" in message for message, _ in violations)


def test_test_docstring_fixture_is_blocked():
    violations = guard.find_csharp_blocking_violations(GOLDEN_TEST_DOCSTRING_CS, "/repo/Tests/WidgetTests.cs")

    assert any("no caller" in message for message, _ in violations)


def test_comment_run_fixture_is_advisory():
    findings = guard.find_csharp_findings(GOLDEN_COMMENT_RUN_CS)

    assert any(message.startswith("Comment run of") for message, _ in findings)


def test_oversize_doc_comment_fixture_is_advisory():
    findings = guard.find_csharp_findings(GOLDEN_OVERSIZE_DOC_COMMENT_CS)

    assert any(message.startswith("XML doc comment spans") for message, _ in findings)


def test_clean_fixture_exercising_every_literal_form_has_no_findings():
    file_path = _FIXTURES_DIR / "clean.cs"
    text = file_path.read_text()

    assert guard.find_csharp_findings(text) == []
    assert guard.find_csharp_issue_reference_violations(text) == []
    assert guard.find_csharp_blocking_violations(text, str(file_path)) == []

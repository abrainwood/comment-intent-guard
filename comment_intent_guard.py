#!/usr/bin/env python3
"""PreToolUse hook and CLI: fail-open comment checks for Python and YAML/Jinja source - bright lines deny, heuristics advise."""
import argparse
import io
import json
import os
import posixpath
import re
import subprocess
import sys
import tokenize

DOCSTRING_LINE_THRESHOLD = 12
COMMENT_RUN_LINE_THRESHOLD = 4

_MIN_TOKENIZE_FSTRING_VERSION = (3, 12)
_SCAN_GIT_TIMEOUT_SECONDS = 5


class AnalysisUnavailable(Exception):
    pass


_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:ms|min|KB|MB|GB|TB)\b"
    r"|\b\d+(?:\.\d+)?[smxhd]\b"
    r"|\b\d+(?:\.\d+)?\s?%"
)
_HEX_LETTER_LOOKAHEAD = r"(?=[0-9a-fA-F]*[a-fA-F])"
_HEX_DIGIT_LOOKAHEAD = r"(?=[0-9a-fA-F]*[0-9])"
_SHA_RE = re.compile(
    rf"\b{_HEX_LETTER_LOOKAHEAD}{_HEX_DIGIT_LOOKAHEAD}[0-9a-fA-F]{{7,40}}\b"
)
_ISSUE_REF_RE = re.compile(r"#\d+\b")
_SHEBANG_RE = re.compile(r"^#!")
_ENCODING_RE = re.compile(r"coding[:=]\s*[-\w.]+")


def _has_evidence_marker(text):
    return bool(_DATE_RE.search(text) or _UNIT_RE.search(text) or _SHA_RE.search(text))


def _evidence_finding(kind, start):
    return (
        f"{kind} near line {start + 1} contains a date, measurement, or SHA. "
        "That looks like a review finding or timing discharged into source - "
        "move it to the issue, PR, or design doc."
    )


def _has_inline_issue_reference(text):
    for line in text.split("\n"):
        indent = len(line) - len(line.lstrip())
        if any(m.start() > indent for m in _ISSUE_REF_RE.finditer(line)):
            return True
    return False


def _issue_reference_violation(kind, start):
    return (
        f"BLOCKED - {kind} near line {start + 1} contains an issue reference. "
        "That's a pointer that rots - name the behaviour instead; the issue "
        "lives in the commit message or PR, not source."
    )


def _is_shebang_or_encoding(stripped):
    return bool(_SHEBANG_RE.match(stripped) or _ENCODING_RE.search(stripped))


_STRING_PREFIX_RE = re.compile(r"^[A-Za-z]*")


def _looks_like_triple_quoted(token_string):
    rest = token_string[_STRING_PREFIX_RE.match(token_string).end():]
    return rest.startswith('"""') or rest.startswith("'''")


_MAX_RESYNC_PASSES = 50


def _split_rows(text):
    return text.split("\n")


def _tokenize_chunk(text):
    tokens = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            tokens.append(tok)
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        return tokens, exc
    return tokens, None


def _offset_token(tok, line_offset):
    if line_offset == 0:
        return tok
    return tok._replace(
        start=(tok.start[0] + line_offset, tok.start[1]),
        end=(tok.end[0] + line_offset, tok.end[1]),
    )


def _is_row_number(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _row_from_token_error_args(exc):
    args = getattr(exc, "args", None)
    if not (isinstance(args, tuple) and len(args) >= 2):
        return None
    position = args[1]
    if not (isinstance(position, tuple) and position):
        return None
    return position[0]  # TokenError: row is positional in .args, undocumented


def _reported_row(exc):
    if isinstance(exc, SyntaxError):
        return getattr(exc, "lineno", None)
    return _row_from_token_error_args(exc)


def _trustworthy_row(exc, num_lines):
    row = _reported_row(exc)
    if not _is_row_number(row):
        return None
    return row if 1 <= row <= num_lines else None


def _resync_made_progress(remaining, new_remaining):
    return len(new_remaining) < len(remaining)


def _tokenize_with_resync(text):
    chunks = []
    remaining = text
    line_offset = 0
    passes = 0

    while True:
        chunk_tokens, error = _tokenize_chunk(remaining)
        chunks.append([_offset_token(t, line_offset) for t in chunk_tokens])
        if error is None:
            break

        passes += 1
        if passes > _MAX_RESYNC_PASSES:
            break

        remaining_lines = _split_rows(remaining)
        error_row = _trustworthy_row(error, len(remaining_lines))
        if error_row is None:
            break

        new_remaining = "\n".join(remaining_lines[error_row:])
        if not _resync_made_progress(remaining, new_remaining):
            break

        line_offset += error_row
        remaining = new_remaining

    return chunks


def _fstring_end_index(tokens, open_idx):
    depth = 1
    i = open_idx + 1
    while i < len(tokens):
        ttype = tokens[i].type
        if ttype == tokenize.FSTRING_START:
            depth += 1
        elif ttype == tokenize.FSTRING_END:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    # An unterminated triple-quoted f-string leaks a lone FSTRING_START.
    return None


def _flush_comment_run(findings, blocking, run_start, run_end, run_lines):
    if run_start is not None:
        run_len = len(run_lines)
        span = (run_start + 1, run_end + 1)
        if run_len > COMMENT_RUN_LINE_THRESHOLD:
            findings.append((
                f"Comment run of {run_len} '#' lines (over the "
                f"{COMMENT_RUN_LINE_THRESHOLD}-line threshold) starting near "
                f"line {run_start + 1}. Does this belong in the design doc or "
                "the issue/PR instead of source - or could a rename carry the "
                "meaning instead?",
                span,
            ))
        run_text = "\n".join(run_lines)
        if _has_evidence_marker(run_text):
            findings.append((_evidence_finding("Comment", run_start), span))
        if _has_inline_issue_reference(run_text):
            blocking.append((_issue_reference_violation("Comment", run_start), span))
    return None, None, []


def _docstring_like_finding(findings, blocking, lines, start_li, end_li):
    block_len = end_li - start_li + 1
    span = (start_li + 1, end_li + 1)
    if block_len > DOCSTRING_LINE_THRESHOLD:
        findings.append((
            f"Docstring spans {block_len} lines (over the "
            f"{DOCSTRING_LINE_THRESHOLD}-line threshold) starting "
            f"near line {start_li + 1}. Does this belong in the design "
            "doc or the issue/PR instead of source?",
            span,
        ))
    block_text = "\n".join(lines[start_li:end_li + 1])
    if _has_evidence_marker(block_text):
        findings.append((_evidence_finding("Docstring", start_li), span))
    if _has_inline_issue_reference(block_text):
        blocking.append((_issue_reference_violation("Docstring", start_li), span))


_NON_CONTENT_TOKENS = (
    tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER,
)


def _opens_its_line(lines, tok):
    # A dangling open bracket makes every later newline NL, never NEWLINE.
    li = tok.start[0] - 1
    if not (0 <= li < len(lines)):
        return True
    return lines[li][:tok.start[1]].strip() == ""


_INDEX_LITERALS = frozenset({"0", "1"})
_SUBSCRIPT_OPEN = "["


def _is_magic_literal(chunk, i):
    return (
        chunk[i].type == tokenize.NUMBER
        and chunk[i].string not in _INDEX_LITERALS
        and not (i > 0 and chunk[i - 1].string == _SUBSCRIPT_OPEN)
    )


def _magic_literal_rows(chunk):
    return {chunk[i].start[0] for i in range(len(chunk)) if _is_magic_literal(chunk, i)}


def _magic_literal_finding(row):
    return (
        f"Comment on line {row} sits beside a magic literal. A comment "
        "explaining a literal is the failure mode - the fix is a named constant."
    )


def _scan_python_comments(text):
    lines = _split_rows(text)

    if sys.version_info < _MIN_TOKENIZE_FSTRING_VERSION:
        major, minor = sys.version_info[:2]
        raise AnalysisUnavailable(
            f"running under Python {major}.{minor}, which predates tokenize's "
            "f-string support (3.12+). Skipping analysis rather than risk a "
            "false negative on f-string docstrings - re-run this hook under "
            "a 3.12+ interpreter."
        )

    findings = []
    blocking = []
    run_start = None
    run_end = None
    run_lines = []

    for chunk in _tokenize_with_resync(text):
        literal_rows = _magic_literal_rows(chunk)
        i = 0
        n = len(chunk)
        while i < n:
            tok = chunk[i]
            ttype = tok.type

            if ttype == tokenize.COMMENT:
                if tok.start[0] in literal_rows:
                    findings.append((_magic_literal_finding(tok.start[0]), (tok.start[0], tok.start[0])))
                li = tok.start[0] - 1
                line_text = lines[li] if 0 <= li < len(lines) else tok.string
                stripped = line_text.strip()
                if li < 2 and stripped.startswith("#") and _is_shebang_or_encoding(stripped):
                    i += 1
                    continue
                if stripped.startswith("#"):
                    if run_start is None:
                        run_start = li
                    run_end = li
                    run_lines.append(line_text)
                else:
                    run_start, run_end, run_lines = _flush_comment_run(findings, blocking, run_start, run_end, run_lines)
                    if _has_evidence_marker(tok.string):
                        findings.append((_evidence_finding("Comment", li), (li + 1, li + 1)))
                    if _has_inline_issue_reference(tok.string):
                        blocking.append((_issue_reference_violation("Comment", li), (li + 1, li + 1)))
                i += 1
                continue

            if ttype in _NON_CONTENT_TOKENS:
                i += 1
                continue

            run_start, run_end, run_lines = _flush_comment_run(findings, blocking, run_start, run_end, run_lines)

            if ttype == tokenize.STRING:
                if _opens_its_line(lines, tok) and _looks_like_triple_quoted(tok.string):
                    _docstring_like_finding(findings, blocking, lines, tok.start[0] - 1, tok.end[0] - 1)
                i += 1
                continue

            if ttype == tokenize.FSTRING_START:
                end_idx = _fstring_end_index(chunk, i)
                if end_idx is not None:
                    if _opens_its_line(lines, tok) and _looks_like_triple_quoted(tok.string):
                        _docstring_like_finding(
                            findings, blocking, lines, tok.start[0] - 1, chunk[end_idx].end[0] - 1
                        )
                    i = end_idx + 1
                else:
                    i += 1
                continue

            i += 1

        run_start, run_end, run_lines = _flush_comment_run(findings, blocking, run_start, run_end, run_lines)

    return blocking, findings


def find_misplaced_rationale(text):
    _, findings = _scan_python_comments(text)
    return findings


def find_issue_reference_violations(text):
    blocking, _ = _scan_python_comments(text)
    return blocking


_TEST_FUNCTION_PREFIX = "test_"
_OPENING_BRACKETS = "([{"
_CLOSING_BRACKETS = ")]}"
_BODY_SKIP_TOKENS = (
    tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT,
)


_EXTERNAL_ID_RE = re.compile(r"\b[A-Z]{2,6}-\d{1,4}[a-z]?\b")
_STANDARDS_TOKENS = frozenset({
    "utf8", "utf16", "utf32", "sha1", "sha256", "sha512", "md5",
    "base32", "base64", "ipv4", "ipv6", "aes128", "aes256",
    "http2", "http3", "crc32", "rfc822", "pep8", "win32", "lz4",
})


def _normalised_id(token):
    return token.replace("-", "").replace("_", "").lower()


def _is_standards_token(token):
    return _normalised_id(token) in _STANDARDS_TOKENS


def _external_id_prefix(identifier):
    return identifier.split("-", 1)[0].lower()


def _external_ids_in(text, allowed_prefixes):
    return [
        m for m in _EXTERNAL_ID_RE.findall(text)
        if not _is_standards_token(m) and _external_id_prefix(m) not in allowed_prefixes
    ]


_ID_TOKEN_RE = re.compile(r"^(?P<prefix>[a-z]{2,4})\d{1,3}[a-z]?$")

_REPO_CONFIG_FILENAME = ".comment-intent-guard.json"
_ID_ALLOWLIST_CONFIG_KEY = "id_prefix_allowlist"
_FILENAME_ONLY_ID_ALLOWLIST_CONFIG_KEY = "filename_only_id_prefix_allowlist"
_ID_PREFIX_SHAPE_RE = re.compile(r"^[a-z]{2,6}$")


def _find_repo_config_path(file_path):
    directory = posixpath.dirname(posixpath.abspath(file_path))
    while True:
        candidate = posixpath.join(directory, _REPO_CONFIG_FILENAME)
        if posixpath.isfile(candidate):
            return candidate
        parent = posixpath.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def _malformed_repo_config(config_path, config_key, reason):
    _warn(
        f"malformed repo config at {config_path} ({reason}) - {config_key} "
        "disabled for this repo, bright line stays enforced"
    )
    return frozenset()


def _repo_prefix_allowlist(file_path, config_key):
    config_path = _find_repo_config_path(file_path)
    if config_path is None:
        return frozenset()
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        return _malformed_repo_config(config_path, config_key, f"{type(exc).__name__}: {exc}")
    if not isinstance(config, dict):
        return _malformed_repo_config(config_path, config_key, "top-level JSON value is not an object")
    if config_key not in config:
        return frozenset()
    prefixes = config[config_key]
    if not (isinstance(prefixes, list) and all(
        isinstance(p, str) and _ID_PREFIX_SHAPE_RE.match(p) for p in prefixes
    )):
        return _malformed_repo_config(
            config_path, config_key, f"'{config_key}' must be a list of 2-6 letter lowercase prefixes"
        )
    return frozenset(prefixes)


def _repo_id_prefix_allowlist(file_path):
    return _repo_prefix_allowlist(file_path, _ID_ALLOWLIST_CONFIG_KEY)


def _repo_filename_only_id_prefix_allowlist(file_path):
    return _repo_prefix_allowlist(file_path, _FILENAME_ONLY_ID_ALLOWLIST_CONFIG_KEY)


def _id_tokens_in_identifier(identifier, allowed_prefixes):
    tokens = []
    for part in identifier.split("_"):
        match = _ID_TOKEN_RE.match(part)
        if match is None or _is_standards_token(part):
            continue
        if match.group("prefix") in allowed_prefixes:
            continue
        tokens.append(part)
    return tokens


def _external_id_violation(identifier, where, row):
    return (
        f"BLOCKED - external id '{identifier}' in {where} near line {row}. "
        "Nobody reading the code knows what it means. Name the behaviour that "
        "breaks; the id belongs in the commit message so git blame still finds it."
    )


def _is_test_definition(chunk, i):
    return (
        chunk[i].type == tokenize.NAME
        and chunk[i].string == "def"
        and i + 1 < len(chunk)
        and chunk[i + 1].type == tokenize.NAME
        and chunk[i + 1].string.startswith(_TEST_FUNCTION_PREFIX)
    )


def _signature_end_index(chunk, def_idx):
    depth = 0
    for i in range(def_idx, len(chunk)):
        text = chunk[i].string
        if text in _OPENING_BRACKETS:
            depth += 1
        elif text in _CLOSING_BRACKETS:
            depth -= 1
        elif text == ":" and depth == 0:
            return i
    return None


def _first_body_token(chunk, colon_idx):
    for i in range(colon_idx + 1, len(chunk)):
        if chunk[i].type not in _BODY_SKIP_TOKENS:
            return chunk[i]
    return None


def _opens_a_string(tok):
    return tok.type in (tokenize.STRING, tokenize.FSTRING_START)


def _test_docstring_violation(name, row, noun="a docstring", generic_noun="docstring"):
    return (
        f"BLOCKED - '{name}' near line {row} opens with {noun}. A test has "
        f"no caller, so no test {generic_noun} is an external quirk or an algorithm's "
        "requirement - every one is an alarm. Put it in the test name instead."
    )


def _test_functions_opening_with_a_docstring(text):
    for chunk in _tokenize_with_resync(text):
        for i in range(len(chunk)):
            if not _is_test_definition(chunk, i):
                continue
            colon_idx = _signature_end_index(chunk, i)
            if colon_idx is None:
                continue
            body_start = _first_body_token(chunk, colon_idx)
            if body_start is not None and _opens_a_string(body_start):
                yield chunk[i + 1].string, body_start.start[0]


def count_test_function_docstrings(text):
    return sum(1 for _ in _test_functions_opening_with_a_docstring(text))


def _filename_violations(file_path, allowed_prefixes):
    stem = posixpath.splitext(posixpath.basename(file_path))[0]
    return [
        (_external_id_violation(found, "the filename", 1), (1, 1))
        for found in _id_tokens_in_identifier(stem, allowed_prefixes) + _external_ids_in(stem, allowed_prefixes)
    ]


def find_blocking_violations(text, file_path):
    lines = _split_rows(text)
    allowed_prefixes = _repo_id_prefix_allowlist(file_path)
    filename_allowed_prefixes = allowed_prefixes | _repo_filename_only_id_prefix_allowlist(file_path)
    violations = _filename_violations(file_path, filename_allowed_prefixes)
    for chunk in _tokenize_with_resync(text):
        for i in range(len(chunk)):
            tok = chunk[i]
            if tok.type == tokenize.STRING and _opens_its_line(lines, tok):
                if _looks_like_triple_quoted(tok.string):
                    violations.extend(
                        (_external_id_violation(found, "a docstring", tok.start[0]), (tok.start[0], tok.end[0]))
                        for found in _external_ids_in(tok.string, allowed_prefixes)
                    )
            if not _is_test_definition(chunk, i):
                continue
            test_name = chunk[i + 1].string
            row = chunk[i + 1].start[0]
            violations.extend(
                (_external_id_violation(found, "a test name", row), (row, row))
                for found in _id_tokens_in_identifier(test_name, allowed_prefixes)
            )
    violations.extend(
        (_test_docstring_violation(name, row), (row, row))
        for name, row in _test_functions_opening_with_a_docstring(text)
    )
    return violations


def _csharp_comment_spans(text):
    spans = []
    i, n = 0, len(text)
    line, counted_up_to = 0, 0

    def line_at(pos):
        nonlocal line, counted_up_to
        line += text.count("\n", counted_up_to, pos)
        counted_up_to = pos
        return line

    while i < n:
        ch = text[i]
        literal_end = _csharp_try_skip_literal(text, i)
        if literal_end is not None:
            i = literal_end
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            is_doc = i + 2 < n and text[i + 2] == "/"
            marker_len = 3 if is_doc else 2
            li = line_at(i)
            eol = text.find("\n", i)
            eol = n if eol == -1 else eol
            kind = "doc" if is_doc else "line"
            content = text[i + marker_len:eol]
            if is_doc and spans and spans[-1][0] == "doc" and spans[-1][2] + 1 == li:
                prev_kind, prev_start, _prev_end, prev_content = spans[-1]
                spans[-1] = (prev_kind, prev_start, li, f"{prev_content}\n{content}")
            else:
                spans.append((kind, li, li, content))
            i = eol
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            start_li = line_at(i)
            close = text.find("*/", i + 2)
            end = n if close == -1 else close
            end_li = start_li + text.count("\n", i, end)
            is_javadoc = i + 2 < n and text[i + 2] == "*" and text[i + 2:i + 4] != "*/"
            block_kind = "doc" if is_javadoc else "block"
            spans.append((block_kind, start_li, end_li, text[i + 2:end]))
            i = n if close == -1 else close + 2
            continue
        i += 1
    return spans


def _strip_csharp_bom(text):
    return text[1:] if text.startswith("﻿") else text


def _scan_csharp_comments(text):
    text = _strip_csharp_bom(text)
    return _scan_csharp_comment_spans(_csharp_comment_spans(text), _split_rows(text))


def _scan_csharp_comment_spans(spans, lines):
    findings = []
    blocking = []
    run_start = None
    run_end = None
    run_lines = []

    for kind, start_li, end_li, content in spans:
        if kind == "line" and lines[start_li][:lines[start_li].find("//")].strip() == "":
            if run_start is not None and start_li == run_end + 1:
                run_end = end_li
                run_lines.append(content)
            else:
                run_start, run_end, run_lines = _flush_csharp_comment_run(
                    findings, blocking, run_start, run_end, run_lines
                )
                run_start, run_end, run_lines = start_li, end_li, [content]
            continue

        run_start, run_end, run_lines = _flush_csharp_comment_run(findings, blocking, run_start, run_end, run_lines)

        span = (start_li + 1, end_li + 1)
        block_len = end_li - start_li + 1
        if kind == "doc" and block_len > DOCSTRING_LINE_THRESHOLD:
            findings.append((
                f"XML doc comment spans {block_len} lines (over the "
                f"{DOCSTRING_LINE_THRESHOLD}-line threshold) starting near "
                f"line {start_li + 1}. Does this belong in the design doc or "
                "the issue/PR instead of source?",
                span,
            ))
        if _has_evidence_marker(content):
            findings.append((_evidence_finding("Comment", start_li), span))
        if _has_inline_issue_reference(content):
            blocking.append((_issue_reference_violation("Comment", start_li), span))

    run_start, run_end, run_lines = _flush_csharp_comment_run(findings, blocking, run_start, run_end, run_lines)
    return blocking, findings


_CSHARP_TEST_ATTRIBUTE_NAMES = frozenset({"Fact", "Theory", "Test", "TestCase", "TestMethod"})
_CSHARP_ATTRIBUTE_NAME_RE = re.compile(r"[\[,]\s*([A-Za-z_][A-Za-z0-9_.]*)")
_CSHARP_METHOD_NAME_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]*>)?\s*\(")


def _is_csharp_test_attribute(name):
    name = name.rpartition(".")[2]
    return name in _CSHARP_TEST_ATTRIBUTE_NAMES or name.removesuffix("Attribute") in _CSHARP_TEST_ATTRIBUTE_NAMES


def _csharp_skip_attribute_bracket_group(line, i):
    n = len(line)
    if i >= n or line[i] != "[":
        return None
    k = i + 1
    while k < n:
        literal_end = _csharp_try_skip_literal(line, k)
        if literal_end is not None:
            k = literal_end
            continue
        if line[k] == "]":
            return k + 1
        k += 1
    return None


def _csharp_find_block_comment_close(lines, li):
    li += 1
    while li < len(lines):
        idx = lines[li].find("*/")
        if idx != -1:
            return li, lines[li][idx + 2:]
        li += 1
    return None


def _csharp_find_block_comment_open(lines, li):
    li -= 1
    while li >= 0:
        if "/*" in lines[li]:
            return li
        li -= 1
    return None


def _csharp_skip_comments(lines, li, text):
    rest = text.strip()
    while True:
        if rest.startswith("//"):
            return li, ""
        if not rest.startswith("/*"):
            return li, rest
        close = rest.find("*/", 2)
        if close != -1:
            rest = rest[close + 2:].strip()
            continue
        found = _csharp_find_block_comment_close(lines, li)
        if found is None:
            return li, ""
        li, after = found
        rest = after.strip()


def _csharp_line_attribute_group(lines, li):
    groups = []
    tail = lines[li].lstrip(" \t")
    while True:
        end = _csharp_skip_attribute_bracket_group(tail, 0)
        if end is None:
            break
        groups.append(tail[:end])
        li, tail = _csharp_skip_comments(lines, li, tail[end:])
    if not groups:
        return None
    return (" ".join(groups), li, tail)


def _csharp_consume_attribute_line(lines, li):
    group = _csharp_line_attribute_group(lines, li)
    if group is None:
        return None
    attrs_text, li, rest = group
    names = _CSHARP_ATTRIBUTE_NAME_RE.findall(attrs_text)
    return names, li, rest


def _csharp_walk_past_attribute_lines(lines, start_li):
    li = start_li
    attribute_names = []
    while li < len(lines):
        if not lines[li].strip() or lines[li].strip().startswith("///"):
            li += 1
            continue
        consumed = _csharp_consume_attribute_line(lines, li)
        if consumed is None:
            return li, attribute_names, lines[li]
        names, resolved_li, rest = consumed
        attribute_names.extend(names)
        if rest != "":
            return resolved_li, attribute_names, rest
        li = resolved_li + 1
    return li, attribute_names, None


def _csharp_method_signature_after_attribute_lines(lines, start_li):
    li, attribute_names, rest = _csharp_walk_past_attribute_lines(lines, start_li)
    if rest is None:
        return None, attribute_names
    match = _CSHARP_METHOD_NAME_RE.search(rest)
    return ((match.group(1), li + 1) if match else None), attribute_names


def _csharp_test_method_after_doc_block(lines, end_li):
    found, attribute_names = _csharp_method_signature_after_attribute_lines(lines, end_li + 1)
    saw_test_attribute = any(_is_csharp_test_attribute(n) for n in attribute_names)
    return found if saw_test_attribute else None


def _csharp_test_attribute_before_doc_block(lines, start_li):
    li = start_li - 1
    while li >= 0 and not lines[li].strip():
        li -= 1
    if li < 0:
        return False
    close_li = li
    group = _csharp_line_attribute_group(lines, li)
    if group is None:
        open_li = _csharp_find_block_comment_open(lines, close_li)
        if open_li is None:
            return False
        group = _csharp_line_attribute_group(lines, open_li)
        if group is None or group[1] != close_li:
            return False
    attrs_text, _, remainder = group
    if remainder != "":
        return False
    names = _CSHARP_ATTRIBUTE_NAME_RE.findall(attrs_text)
    return any(_is_csharp_test_attribute(n) for n in names)


def _csharp_test_doc_blocking_violations(spans, lines):
    violations = []
    seen_rows = set()
    for kind, start_li, end_li, _content in spans:
        if kind != "doc":
            continue
        found = _csharp_test_method_after_doc_block(lines, end_li)
        if found is None and _csharp_test_attribute_before_doc_block(lines, start_li):
            found, _attribute_names = _csharp_method_signature_after_attribute_lines(lines, end_li + 1)
        if found is not None and found[1] not in seen_rows:
            seen_rows.add(found[1])
            name, row = found
            violation = _test_docstring_violation(name, row, "an XML doc comment", "XML doc comment")
            violations.append((violation, (row, row)))
    return violations


def _csharp_external_id_blocking_violations(spans, allowed_prefixes):
    violations = []
    for kind, start_li, end_li, content in spans:
        if kind != "doc":
            continue
        violations.extend(
            (_external_id_violation(found, "an XML doc comment", start_li + 1), (start_li + 1, end_li + 1))
            for found in _external_ids_in(content, allowed_prefixes)
        )
    return violations


def _csharp_blocking_violations(spans, lines, allowed_prefixes):
    return (
        _csharp_test_doc_blocking_violations(spans, lines)
        + _csharp_external_id_blocking_violations(spans, allowed_prefixes)
    )


def find_csharp_blocking_violations(text, file_path):
    text = _strip_csharp_bom(text)
    allowed_prefixes = _repo_id_prefix_allowlist(file_path)
    return _csharp_blocking_violations(_csharp_comment_spans(text), _split_rows(text), allowed_prefixes)


def find_csharp_findings(text):
    _, findings = _scan_csharp_comments(text)
    return findings


def find_csharp_issue_reference_violations(text):
    blocking, _ = _scan_csharp_comments(text)
    return blocking


def _flush_csharp_comment_run(findings, blocking, run_start, run_end, run_lines):
    if run_start is not None:
        run_len = len(run_lines)
        span = (run_start + 1, run_end + 1)
        if run_len > COMMENT_RUN_LINE_THRESHOLD:
            findings.append((
                f"Comment run of {run_len} '//' lines (over the "
                f"{COMMENT_RUN_LINE_THRESHOLD}-line threshold) starting near "
                f"line {run_start + 1}. Does this belong in the design doc or "
                "the issue/PR instead of source - or could a rename carry the "
                "meaning instead?",
                span,
            ))
        run_text = "\n".join(run_lines)
        if _has_evidence_marker(run_text):
            findings.append((_evidence_finding("Comment", run_start), span))
        if _has_inline_issue_reference(run_text):
            blocking.append((_issue_reference_violation("Comment", run_start), span))
    return None, None, []


def _csharp_skip_char_literal(text, start):
    i = start + 1
    n = len(text)
    if i < n and text[i] == "\\" and i + 1 < n:
        i += 2
    elif i < n:
        i += 1
    if i < n and text[i] == "'":
        return i + 1
    return start + 1


def _csharp_skip_raw_string(text, start, quote_run):
    i = start + quote_run
    n = len(text)
    while i < n:
        if text[i] == '"':
            close_run = 1
            while i + close_run < n and text[i + close_run] == '"':
                close_run += 1
            if close_run >= quote_run:
                return i + close_run
            i += close_run
            continue
        i += 1
    return i


def _csharp_skip_verbatim_string(text, quote_index):
    i = quote_index + 1
    n = len(text)
    while i < n:
        if text[i] == '"':
            if i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _csharp_skip_string(text, start):
    i = start + 1
    n = len(text)
    while i < n and text[i] != "\n":
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    return i


def _csharp_dollar_run_length(text, i):
    n = len(text)
    run = 0
    while i + run < n and text[i + run] == "$":
        run += 1
    return run


def _csharp_try_skip_literal(text, i):
    n = len(text)
    ch = text[i]
    if ch == "@" and i + 1 < n and text[i + 1] == '"':
        return _csharp_skip_verbatim_string(text, i + 1)
    if ch == "@" and i + 2 < n and text[i + 1] == "$" and text[i + 2] == '"':
        return _csharp_skip_interpolated_string(text, i + 2, verbatim=True)
    if ch == "$":
        dollar_run = _csharp_dollar_run_length(text, i)
        q = i + dollar_run
        if q < n and text[q] == "@" and q + 1 < n and text[q + 1] == '"':
            return _csharp_skip_interpolated_string(text, q + 1, verbatim=True)
        if q < n and text[q] == '"':
            quote_run = 1
            while q + quote_run < n and text[q + quote_run] == '"':
                quote_run += 1
            if quote_run >= 3:
                return _csharp_skip_raw_interpolated_string(text, q, quote_run, dollar_run)
            if dollar_run == 1:
                return _csharp_skip_interpolated_string(text, q, verbatim=False)
        return None
    if ch == '"':
        quote_run = 1
        while i + quote_run < n and text[i + quote_run] == '"':
            quote_run += 1
        if quote_run >= 3:
            return _csharp_skip_raw_string(text, i, quote_run)
        return _csharp_skip_string(text, i)
    if ch == "'":
        return _csharp_skip_char_literal(text, i)
    return None


def _csharp_skip_raw_interpolation_hole(text, start, brace_count):
    i = start
    n = len(text)
    depth = 1
    while i < n:
        literal_end = _csharp_try_skip_literal(text, i)
        if literal_end is not None:
            i = literal_end
            continue
        if text[i] == "{":
            depth += 1
            i += 1
            continue
        if text[i] == "}":
            depth -= 1
            if depth == 0:
                close_run = 1
                while close_run < brace_count and i + close_run < n and text[i + close_run] == "}":
                    close_run += 1
                return i + close_run
            i += 1
            continue
        i += 1
    return i


def _csharp_skip_raw_interpolated_string(text, quote_index, quote_run, dollar_run):
    i = quote_index + quote_run
    n = len(text)
    while i < n:
        if text[i] == "{":
            brace_run = 1
            while i + brace_run < n and text[i + brace_run] == "{":
                brace_run += 1
            if brace_run >= dollar_run:
                i = _csharp_skip_raw_interpolation_hole(text, i + dollar_run, dollar_run)
                continue
            i += brace_run
            continue
        if text[i] == '"':
            close_run = 1
            while i + close_run < n and text[i + close_run] == '"':
                close_run += 1
            if close_run >= quote_run:
                return i + close_run
            i += close_run
            continue
        i += 1
    return i


def _csharp_skip_interpolation_hole(text, start, verbatim):
    i = start + 1
    n = len(text)
    depth = 1
    while i < n:
        if not verbatim and text[i] == "\n":
            return i
        literal_end = _csharp_try_skip_literal(text, i)
        if literal_end is not None:
            i = literal_end
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def _csharp_skip_interpolated_string(text, quote_index, verbatim):
    i = quote_index + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if not verbatim and ch == "\n":
            return i
        if ch == "{" and i + 1 < n and text[i + 1] == "{":
            i += 2
            continue
        if ch == "}" and i + 1 < n and text[i + 1] == "}":
            i += 2
            continue
        if ch == "{":
            i = _csharp_skip_interpolation_hole(text, i, verbatim)
            continue
        if not verbatim and ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == '"':
            if verbatim and i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return i


YAML_COMMENT_RUN_LINE_THRESHOLD = 4


_QUOTE_OPENERS = " \t:,[{"


def _closes_double_quote(line, idx):
    backslashes = 0
    j = idx - 1
    while j >= 0 and line[j] == "\\":
        backslashes += 1
        j -= 1
    return backslashes % 2 == 0


def _yaml_comment_start(line):
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        opener = idx == 0 or line[idx - 1] in _QUOTE_OPENERS
        if ch == "'" and not in_double:
            if in_single:
                in_single = False
            elif opener:
                in_single = True
        elif ch == '"' and not in_single:
            if in_double:
                if _closes_double_quote(line, idx):
                    in_double = False
            elif opener:
                in_double = True
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return idx
    return None


_DEAD_CONFIG_LINE_RE = re.compile(
    r"^\s*-\s+\S"
    r"|^\s*[\w.$-]+:\s*$"
    r"|^\s*[\w.$-]+:\s*['\"]"
    r"|^\s*[\w.$-]+:\s*\S+\s*$"
    r"|\{%.*?%\}"
    r"|\{\{.*?\}\}"
)


def _strip_comment_marker(line):
    rest = line.strip()[1:]
    return rest[1:] if rest.startswith(" ") else rest


def _looks_like_dead_config(run_lines):
    stripped = [_strip_comment_marker(line) for line in run_lines]
    matches = sum(1 for line in stripped if _DEAD_CONFIG_LINE_RE.search(line))
    return matches > len(stripped) / 2


def _dead_config_finding(run_len, run_start):
    return (
        f"Comment run of {run_len} '#' lines (over the "
        f"{YAML_COMMENT_RUN_LINE_THRESHOLD}-line threshold) starting near line "
        f"{run_start + 1} reads as commented-out YAML, not prose - dead "
        "config, delete or restore it rather than leaving it inline."
    )


def _comment_run_finding(run_len, run_start):
    return (
        f"Comment run of {run_len} '#' lines (over the "
        f"{YAML_COMMENT_RUN_LINE_THRESHOLD}-line threshold) starting near "
        f"line {run_start + 1}. Does this belong in the design doc or the "
        "issue/PR instead of source?"
    )


def _flush_yaml_comment_run(findings, blocking, run_start, run_lines):
    if run_start is not None:
        span = (run_start + 1, run_start + len(run_lines))
        is_dead_config = len(run_lines) > YAML_COMMENT_RUN_LINE_THRESHOLD and _looks_like_dead_config(run_lines)
        if len(run_lines) > YAML_COMMENT_RUN_LINE_THRESHOLD:
            if is_dead_config:
                findings.append((_dead_config_finding(len(run_lines), run_start), span))
            else:
                findings.append((_comment_run_finding(len(run_lines), run_start), span))
        run_text = "\n".join(run_lines)
        if not is_dead_config and _has_evidence_marker(run_text):
            findings.append((_evidence_finding("Comment", run_start), span))
        if not is_dead_config and _has_inline_issue_reference(run_text):
            blocking.append((_issue_reference_violation("Comment", run_start), span))
    return None, []


_BLOCK_SCALAR_HEADER_RE = re.compile(
    r"^[ ]*(?:-\s+)?"
    r'(?P<key>"[^"]*"|\'[^\']*\'|[A-Za-z_][\w.-]*)'
    r"\s*:\s*[|>][0-9+-]*\s*(?:#.*)?$"
)


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def _block_scalar_header(line):
    match = _BLOCK_SCALAR_HEADER_RE.match(line)
    if match is None:
        return None
    return match.start("key"), match.group("key").strip("\"'")


def _block_scalar_extent(lines, header_indent, body_start):
    last_content = body_start - 1
    i = body_start
    while i < len(lines):
        if lines[i].strip() == "":
            i += 1
            continue
        if _indent_of(lines[i]) > header_indent:
            last_content = i
            i += 1
            continue
        break
    return last_content, i


JINJA_BLOCK_LINE_THRESHOLD = 8
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)


def _jinja_block_finding(block_len, start_li):
    return (
        f"Jinja '{{# #}}' block spans {block_len} lines (over the "
        f"{JINJA_BLOCK_LINE_THRESHOLD}-line threshold) starting near line "
        f"{start_li + 1}. Does this belong in the design doc or the issue/PR "
        "instead of source?"
    )


def _jinja_comment_findings(text):
    findings = []
    blocking = []
    for match in _JINJA_COMMENT_RE.finditer(text):
        start_li = text[:match.start()].count("\n")
        block_len = match.group().count("\n") + 1
        span = (start_li + 1, start_li + block_len)
        if block_len > JINJA_BLOCK_LINE_THRESHOLD:
            findings.append((_jinja_block_finding(block_len, start_li), span))
        if _has_evidence_marker(match.group()):
            findings.append((_evidence_finding("Jinja comment block", start_li), span))
        if _has_inline_issue_reference(match.group()):
            blocking.append((_issue_reference_violation("Jinja comment block", start_li), span))
    return blocking, findings


YAML_DESCRIPTION_LINE_THRESHOLD = 12
_DESCRIPTION_KEY = "description"


def _description_block_finding(findings, blocking, lines, header_li, block_start, block_end):
    if block_end < block_start:
        return
    block_len = block_end - block_start + 1
    span = (header_li + 1, block_end + 1)
    if block_len > YAML_DESCRIPTION_LINE_THRESHOLD:
        findings.append((
            f"Description block scalar spans {block_len} lines (over the "
            f"{YAML_DESCRIPTION_LINE_THRESHOLD}-line threshold) starting near "
            f"line {header_li + 1}. Does this belong in the design doc or "
            "the issue/PR instead of source?",
            span,
        ))
    block_text = "\n".join(lines[block_start:block_end + 1])
    if _has_evidence_marker(block_text):
        findings.append((_evidence_finding("Description block scalar", block_start), span))
    if _has_inline_issue_reference(block_text):
        blocking.append((_issue_reference_violation("Description block scalar", block_start), span))


def _scan_yaml_comments(text):
    lines = _split_rows(text)
    blocking, findings = _jinja_comment_findings(text)
    run_start = None
    run_lines = []

    li = 0
    while li < len(lines):
        line = lines[li]
        header = _block_scalar_header(line)
        if header is not None:
            run_start, run_lines = _flush_yaml_comment_run(findings, blocking, run_start, run_lines)
            header_indent, key = header
            block_start = li + 1
            last_content, next_li = _block_scalar_extent(lines, header_indent, block_start)
            if key == _DESCRIPTION_KEY:
                _description_block_finding(findings, blocking, lines, li, block_start, last_content)
            li = next_li
            continue

        col = _yaml_comment_start(line)
        if col is not None and line[:col].strip() == "":
            if run_start is None:
                run_start = li
            run_lines.append(line)
            li += 1
            continue

        run_start, run_lines = _flush_yaml_comment_run(findings, blocking, run_start, run_lines)
        if col is not None:
            comment_text = line[col:]
            if _has_evidence_marker(comment_text):
                findings.append((_evidence_finding("Comment", li), (li + 1, li + 1)))
            if _has_inline_issue_reference(comment_text):
                blocking.append((_issue_reference_violation("Comment", li), (li + 1, li + 1)))
        li += 1

    run_start, run_lines = _flush_yaml_comment_run(findings, blocking, run_start, run_lines)
    return blocking, findings


def find_yaml_findings(text):
    _, findings = _scan_yaml_comments(text)
    return findings


def find_yaml_issue_reference_violations(text):
    blocking, _ = _scan_yaml_comments(text)
    return blocking


def find_jinja_findings(text):
    _, findings = _jinja_comment_findings(text)
    return findings


def find_jinja_issue_reference_violations(text):
    blocking, _ = _jinja_comment_findings(text)
    return blocking


_STATE_COMMENT_KEY = "comment_lines"
_STATE_CODE_KEY = "code_lines"


def _warn(message, prefix="comment_intent_guard"):
    print(f"{prefix}: {message}", file=sys.stderr)


def _load_state(state_path, prefix="comment_intent_guard"):
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        _warn(f"unreadable state at {state_path} ({type(exc).__name__}) - starting fresh", prefix=prefix)
        return {}
    if not isinstance(state, dict):
        _warn(f"unexpected state shape at {state_path} - starting fresh", prefix=prefix)
        return {}
    return state


def _save_state(state_path, state):
    try:
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError as exc:
        _warn(f"could not persist state to {state_path} ({type(exc).__name__})")


def _session_totals(state, session_id):
    entry = state.get(session_id)
    if not isinstance(entry, dict):
        return 0, 0
    comment_lines = entry.get(_STATE_COMMENT_KEY)
    code_lines = entry.get(_STATE_CODE_KEY)
    if not (isinstance(comment_lines, int) and isinstance(code_lines, int)):
        return 0, 0
    return comment_lines, code_lines


MAX_TRACKED_SESSIONS = 50


def _evict_oldest_sessions(state):
    for stale in list(state)[:-MAX_TRACKED_SESSIONS]:
        del state[stale]


def record_edit(state_path, session_id, comment_lines, code_lines):
    state = _load_state(state_path)
    seen_comments, seen_code = _session_totals(state, session_id)
    totals = (seen_comments + comment_lines, seen_code + code_lines)
    state.pop(session_id, None)
    state[session_id] = {_STATE_COMMENT_KEY: totals[0], _STATE_CODE_KEY: totals[1]}
    _evict_oldest_sessions(state)
    _save_state(state_path, state)
    return totals


PEER_COMMENT_DENSITY = 0.181
MIN_CODE_LINES_FOR_DENSITY = 40


def aggregate_density_finding(comment_lines, code_lines):
    if code_lines < MIN_CODE_LINES_FOR_DENSITY:
        return None
    density = comment_lines / code_lines
    if density <= PEER_COMMENT_DENSITY:
        return None
    return (
        f"Aggregate comment density across this session's Python edits is "
        f"{density:.1%} over {code_lines} code lines, above the "
        f"{PEER_COMMENT_DENSITY:.1%} peer baseline. Per-file each edit looked "
        "fine; the slice as a whole is drifting."
    )


def count_comment_and_code_lines(text):
    comment_rows = set()
    code_rows = set()
    for chunk in _tokenize_with_resync(text):
        for tok in chunk:
            if tok.type == tokenize.COMMENT:
                comment_rows.add(tok.start[0])
            elif tok.type not in _NON_CONTENT_TOKENS:
                code_rows.add(tok.start[0])
    return len(comment_rows), len(code_rows)


def _extract_added_text(tool_name, tool_input):
    if tool_name == "Write":
        content = tool_input.get("content")
    elif tool_name == "Edit":
        content = tool_input.get("new_string")
    else:
        content = None
    return content if isinstance(content, str) else None


_STATE_PATH_ENV = "COMMENT_INTENT_GUARD_STATE"


def _state_path():
    override = os.environ.get(_STATE_PATH_ENV)
    if override:
        return override
    return os.path.expanduser("~/.claude/comment-intent-guard/state.json")


def _density_findings(session_id, text):
    if not session_id:
        return []
    comment_lines, code_lines = count_comment_and_code_lines(text)
    totals = record_edit(_state_path(), session_id, comment_lines, code_lines)
    finding = aggregate_density_finding(*totals)
    return [finding] if finding else []


def _deny_payload(violations):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "COMMENT INTENT - bright line violated:\n\n"
                + "\n\n".join(violations)
                + "\n\nSee /comment-intent-guard:self-documenting-code for how to fix this."
            ),
        }
    }


def _findings_for_file(file_path, text):
    if file_path.endswith(".py"):
        blocking = find_blocking_violations(text, file_path)
        try:
            issue_blocking, advisory = _scan_python_comments(text)
        except AnalysisUnavailable as exc:
            exc.blocking = blocking
            raise
        return blocking + issue_blocking, advisory
    if file_path.endswith((".yaml", ".yml")):
        return find_yaml_issue_reference_violations(text), find_yaml_findings(text)
    if file_path.endswith((".jinja", ".j2")):
        return find_jinja_issue_reference_violations(text), find_jinja_findings(text)
    if file_path.endswith(".cs"):
        text = _strip_csharp_bom(text)
        spans = _csharp_comment_spans(text)
        lines = _split_rows(text)
        allowed_prefixes = _repo_id_prefix_allowlist(file_path)
        issue_blocking, findings = _scan_csharp_comment_spans(spans, lines)
        blocking = _csharp_blocking_violations(spans, lines, allowed_prefixes) + issue_blocking
        return blocking, findings
    return [], []


_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

_C_QUOTE_SIMPLE_ESCAPES = {
    '"': b'"', "\\": b"\\", "n": b"\n", "t": b"\t",
    "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r", "v": b"\v",
}


def _c_unquote_body(body):
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        char = body[i]
        if char != "\\" or i + 1 >= n:
            out += char.encode("utf-8")
            i += 1
            continue
        escaped = body[i + 1]
        simple = _C_QUOTE_SIMPLE_ESCAPES.get(escaped)
        if simple is not None:
            out += simple
            i += 2
            continue
        if "0" <= escaped <= "7":
            j = i + 1
            end = min(j + 3, n)
            while j < end and "0" <= body[j] <= "7":
                j += 1
            out.append(int(body[i + 1:j], 8) & 0xFF)
            i = j
            continue
        out += body[i:i + 2].encode("utf-8")
        i += 2
    return out


def _unquote_git_header_path(raw):
    # A path with a space gets a trailing tab (git's own disambiguation);
    # a path with control characters gets wrapped in C-quotes instead.
    raw = raw.removesuffix("\t")
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return _c_unquote_body(raw[1:-1]).decode("utf-8")
        except UnicodeDecodeError:
            pass
    return raw


def _parse_diff_added_lines(diff_output, known_relpaths):
    added_by_relpath = {}
    current_relpath = None
    in_hunks = False
    for line in diff_output.splitlines():
        if line.startswith("diff --git "):
            in_hunks = False
            current_relpath = None
            continue
        if not in_hunks and line.startswith("+++ "):
            path_part = _unquote_git_header_path(line[len("+++ "):])
            current_relpath = None if path_part == "/dev/null" else path_part.removeprefix("b/")
            if current_relpath in known_relpaths:
                added_by_relpath.setdefault(current_relpath, set())
            else:
                current_relpath = None
            in_hunks = True
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match is not None and current_relpath is not None:
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            added_by_relpath[current_relpath].update(range(start, start + count))
    return added_by_relpath


_PATHSPEC_CHUNK_SIZE = 1000


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _joined_for_message(paths, limit=5):
    paths = list(paths)
    joined = ", ".join(paths[:limit])
    remaining = len(paths) - limit
    if remaining > 0:
        joined += f" and {remaining} more"
    return joined


def _parse_porcelain_untracked(porcelain_output, relpaths):
    relpaths = set(relpaths)
    return {
        entry[3:] for entry in porcelain_output.split("\0")
        if entry.startswith("??") and entry[3:] in relpaths
    }


def _git_toplevel(repo_dir):
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=_SCAN_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _warn(
            f"git rev-parse --show-toplevel timed out after {_SCAN_GIT_TIMEOUT_SECONDS}s for {repo_dir} - "
            "not filtering findings for its files"
        )
        return None
    except OSError as exc:
        _warn(
            f"could not run git rev-parse for {repo_dir} ({type(exc).__name__}) - "
            "not filtering findings for its files"
        )
        return None
    if result.returncode != 0:
        _warn(
            f"git rev-parse --show-toplevel failed for {repo_dir} (exit {result.returncode}): "
            f"{result.stderr.strip()} - not filtering findings for its files"
        )
        return None
    return result.stdout.strip()


def _resolved_path(path):
    resolved_dir = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    return os.path.join(resolved_dir, os.path.basename(path))


def _run_chunked_git_command(relpaths, relpath_to_paths, build_command, label):
    outputs = []
    failed_relpaths = set()
    for chunk in _chunked(relpaths, _PATHSPEC_CHUNK_SIZE):
        joined = _joined_for_message(path for relpath in chunk for path in relpath_to_paths[relpath])
        try:
            result = subprocess.run(
                build_command(chunk),
                capture_output=True, text=True, timeout=_SCAN_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            _warn(
                f"git {label} timed out after {_SCAN_GIT_TIMEOUT_SECONDS}s for {joined} - "
                "not filtering findings for these files"
            )
            failed_relpaths.update(chunk)
            continue
        except OSError as exc:
            _warn(
                f"could not run git {label} for {joined} ({type(exc).__name__}) - "
                "not filtering findings for these files"
            )
            failed_relpaths.update(chunk)
            continue
        if result.returncode != 0:
            _warn(
                f"git {label} failed for {joined} (exit {result.returncode}): "
                f"{result.stderr.strip()} - not filtering findings for these files"
            )
            failed_relpaths.update(chunk)
            continue
        outputs.append((chunk, result.stdout))
    return outputs, failed_relpaths


def _added_line_numbers_for_toplevel(base_ref, toplevel, group_file_paths, files_are_tracked=False):
    relpath_to_paths = {}
    for path in group_file_paths:
        relpath_to_paths.setdefault(os.path.relpath(_resolved_path(path), toplevel), []).append(path)
    relpaths = list(relpath_to_paths)

    untracked = set()
    status_failed_relpaths = set()
    if not files_are_tracked:
        status_outputs, status_failed_relpaths = _run_chunked_git_command(
            relpaths, relpath_to_paths,
            build_command=lambda chunk: [
                "git", "--literal-pathspecs", "-C", toplevel, "status", "--porcelain", "-z", "--", *chunk
            ],
            label="status",
        )
        for chunk, stdout in status_outputs:
            untracked.update(_parse_porcelain_untracked(stdout, chunk))

    result = {
        path: None for relpath in untracked | status_failed_relpaths for path in relpath_to_paths[relpath]
    }
    tracked_relpaths = [
        relpath for relpath in relpaths if relpath not in untracked and relpath not in status_failed_relpaths
    ]
    if not tracked_relpaths:
        return result

    added_by_relpath = {}
    diff_outputs, failed_relpaths = _run_chunked_git_command(
        tracked_relpaths, relpath_to_paths,
        build_command=lambda chunk: [
            "git", "--literal-pathspecs", "-C", toplevel, "-c", "core.quotePath=false", "diff", "-U0",
            "--no-color", base_ref, "--", *chunk
        ],
        label=f"diff against {base_ref}",
    )
    for chunk, stdout in diff_outputs:
        added_by_relpath.update(_parse_diff_added_lines(stdout, set(chunk)))

    for relpath in tracked_relpaths:
        value = None if relpath in failed_relpaths else added_by_relpath.get(relpath, set())
        for path in relpath_to_paths[relpath]:
            result[path] = value
    return result


def _added_line_numbers_map(base_ref, file_paths, repo_root=None, files_are_tracked=False):
    if repo_root is not None:
        return _added_line_numbers_for_toplevel(base_ref, repo_root, file_paths, files_are_tracked=files_are_tracked)

    toplevel_by_dir = {}
    groups = {}
    for file_path in file_paths:
        repo_dir = os.path.realpath(os.path.dirname(os.path.abspath(file_path)))
        if repo_dir not in toplevel_by_dir:
            toplevel_by_dir[repo_dir] = _git_toplevel(repo_dir)
        groups.setdefault(toplevel_by_dir[repo_dir], []).append(file_path)

    result = {}
    for toplevel, group_file_paths in groups.items():
        if toplevel is None:
            result.update({path: None for path in group_file_paths})
            continue
        result.update(
            _added_line_numbers_for_toplevel(base_ref, toplevel, group_file_paths, files_are_tracked=files_are_tracked)
        )
    return result


def _added_line_numbers(base_ref, file_path):
    return _added_line_numbers_map(base_ref, [file_path])[file_path]


def _touches_added_lines(span, added):
    start, end = span
    return any(line in added for line in range(start, end + 1))


def _restrict_to_added_lines(findings, added):
    return [finding for finding in findings if _touches_added_lines(finding[1], added)]


_EXIT_CLEAN = 0
_EXIT_ADVISORY = 1
# 2 is argparse's own usage-error exit code, reserved by not defining it here.
_EXIT_BRIGHT_LINE = 3
_EXIT_INTERNAL_ERROR = 4


def _check_files(files, base=None, repo_root=None, files_are_tracked=False):
    try:
        any_error = False
        any_blocking = False
        any_advisory = False
        added_by_path = (
            _added_line_numbers_map(base, files, repo_root=repo_root, files_are_tracked=files_are_tracked)
            if base else {}
        )
        for file_path in files:
            try:
                with open(file_path, encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError) as exc:
                _warn(f"could not read {file_path} ({type(exc).__name__}) - skipping")
                any_error = True
                continue

            try:
                blocking, advisory = _findings_for_file(file_path, text)
            except AnalysisUnavailable as exc:
                for message, _ in getattr(exc, "blocking", []):
                    any_blocking = True
                    print(f"{file_path}: {message}")
                _warn(f"could not analyze {file_path} ({exc}) - skipping advisory checks")
                any_error = True
                continue

            if base:
                added = added_by_path.get(file_path)
                if added is not None:
                    advisory = _restrict_to_added_lines(advisory, added)

            for message, _ in blocking:
                any_blocking = True
                print(f"{file_path}: {message}")
            for message, _ in advisory:
                any_advisory = True
                print(f"{file_path}: {message}")
    except Exception as exc:
        _warn(f"internal error: {type(exc).__name__}: {exc}")
        return _EXIT_INTERNAL_ERROR

    if any_error:
        return _EXIT_INTERNAL_ERROR
    if any_blocking:
        return _EXIT_BRIGHT_LINE
    if any_advisory:
        return _EXIT_ADVISORY
    return _EXIT_CLEAN


def _cli_main(argv):
    prog = os.environ.get("COMMENT_INTENT_GUARD_PROG", "comment_intent_guard")
    parser = argparse.ArgumentParser(prog=prog)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--base")
    mode.add_argument("--all", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    return _check_files(args.files, base=args.base)


_SCAN_PATHSPECS = ("*.py", "*.yaml", "*.yml", "*.jinja", "*.j2", "*.cs")


class _ScanGitError(Exception):
    pass


def _run_scan_git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, timeout=_SCAN_GIT_TIMEOUT_SECONDS,
    )


def _run_scan_git_checked(args, cwd):
    joined = " ".join(args)
    try:
        result = _run_scan_git(args, cwd=cwd)
    except subprocess.TimeoutExpired:
        _warn(f"git {joined} timed out after {_SCAN_GIT_TIMEOUT_SECONDS}s - aborting scan")
        raise _ScanGitError from None
    except OSError as exc:
        _warn(f"could not run git {joined} ({type(exc).__name__}) - aborting scan")
        raise _ScanGitError from None
    return result


def _decode_nul_separated(raw_bytes):
    return [
        entry.decode("utf-8", errors="surrogateescape")
        for entry in raw_bytes.split(b"\0")
        if entry
    ]


def _scan_git_toplevel():
    result = _run_scan_git_checked(["rev-parse", "--show-toplevel"], cwd=None)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="surrogateescape").strip("\n")


def _scan_head_sha(repo_root):
    result = _run_scan_git_checked(["rev-parse", "-q", "--verify", "HEAD"], cwd=repo_root)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="surrogateescape").strip()


def _scan_list_tracked(repo_root, head_sha):
    if head_sha:
        args = ["diff", "--name-only", "-z", "--diff-filter=d", "HEAD", "--", *_SCAN_PATHSPECS]
    else:
        args = ["diff", "--cached", "--name-only", "-z", "--diff-filter=d", "--", *_SCAN_PATHSPECS]
    result = _run_scan_git_checked(args, cwd=repo_root)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="surrogateescape").strip()
        _warn(f"git {' '.join(args)} failed (exit {result.returncode}): {stderr} - aborting scan")
        raise _ScanGitError
    return _decode_nul_separated(result.stdout)


def _scan_list_untracked(repo_root):
    args = ["ls-files", "--others", "--exclude-standard", "-z", "--", *_SCAN_PATHSPECS]
    result = _run_scan_git_checked(args, cwd=repo_root)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="surrogateescape").strip()
        _warn(f"git {' '.join(args)} failed (exit {result.returncode}): {stderr} - aborting scan")
        raise _ScanGitError
    return _decode_nul_separated(result.stdout)


def _drop_staged_but_deleted(relpaths):
    return [rp for rp in relpaths if os.path.lexists(rp)]


def _scan_main():
    try:
        repo_root = _scan_git_toplevel()
    except _ScanGitError:
        return _EXIT_INTERNAL_ERROR
    if repo_root is None:
        print("comment-intent-guard scan: not inside a git repository", file=sys.stderr)
        return 2

    try:
        os.chdir(repo_root)
    except OSError as exc:
        _warn(f"could not switch to repo root {repo_root} ({type(exc).__name__}) - aborting scan")
        return _EXIT_INTERNAL_ERROR

    try:
        head_sha = _scan_head_sha(repo_root)
        tracked = _drop_staged_but_deleted(_scan_list_tracked(repo_root, head_sha))
        untracked = _drop_staged_but_deleted(_scan_list_untracked(repo_root))
    except _ScanGitError:
        return _EXIT_INTERNAL_ERROR

    if not tracked and not untracked:
        print("nothing uncommitted to scan")
        return _EXIT_CLEAN

    overall = _EXIT_CLEAN
    if tracked:
        base = "HEAD" if head_sha else None
        overall = max(overall, _check_files(tracked, base=base, repo_root=repo_root, files_are_tracked=True))
    if untracked:
        overall = max(overall, _check_files(untracked))
    return overall


def _hook_main():
    try:
        payload = json.load(sys.stdin)
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return

        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str):
            return
        is_python = file_path.endswith(".py")
        is_yaml = file_path.endswith((".yaml", ".yml"))
        is_jinja = file_path.endswith((".jinja", ".j2"))
        is_csharp = file_path.endswith(".cs")
        if not (is_python or is_yaml or is_jinja or is_csharp):
            return

        text = _extract_added_text(tool_name, tool_input)
        if not text:
            return

        if is_jinja:
            violations = [message for message, _ in find_jinja_issue_reference_violations(text)]
            if violations:
                print(json.dumps(_deny_payload(violations)))
                return

            findings = [message for message, _ in find_jinja_findings(text)]
        elif is_csharp:
            issue_blocking, advisory_pairs = _findings_for_file(file_path, text)
            violations = [message for message, _ in issue_blocking]
            if violations:
                print(json.dumps(_deny_payload(violations)))
                return

            findings = [message for message, _ in advisory_pairs]
        elif is_python:
            violations = [message for message, _ in find_blocking_violations(text, file_path)]
            if violations:
                print(json.dumps(_deny_payload(violations)))
                return

            issue_blocking, advisory_pairs = _scan_python_comments(text)
            violations = [message for message, _ in issue_blocking]
            if violations:
                print(json.dumps(_deny_payload(violations)))
                return

            findings = [message for message, _ in advisory_pairs]
            findings.extend(_density_findings(payload.get("session_id"), text))
        else:
            violations = [message for message, _ in find_yaml_issue_reference_violations(text)]
            if violations:
                print(json.dumps(_deny_payload(violations)))
                return

            findings = [message for message, _ in find_yaml_findings(text)]

        if not findings:
            return

        message = "COMMENT INTENT CHECK:\n\n" + "\n\n".join(findings)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": message,
            }
        }))
    except Exception as exc:
        print(f"comment_intent_guard: {type(exc).__name__}: {exc}", file=sys.stderr)
        return


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--scan":
        if len(argv) > 1:
            print("usage: comment_intent_guard --scan", file=sys.stderr)
            sys.exit(2)
        sys.exit(_scan_main())
    if argv:
        sys.exit(_cli_main(argv))
    _hook_main()


if __name__ == "__main__":
    main()

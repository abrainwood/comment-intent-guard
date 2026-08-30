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


def _flush_comment_run(findings, run_start, run_end, run_lines):
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
        if _has_evidence_marker("\n".join(run_lines)):
            findings.append((_evidence_finding("Comment", run_start), span))
    return None, None, []


def _docstring_like_finding(findings, lines, start_li, end_li):
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


def find_misplaced_rationale(text):
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
                    run_start, run_end, run_lines = _flush_comment_run(findings, run_start, run_end, run_lines)
                    if _has_evidence_marker(tok.string):
                        findings.append((_evidence_finding("Comment", li), (li + 1, li + 1)))
                i += 1
                continue

            if ttype in _NON_CONTENT_TOKENS:
                i += 1
                continue

            run_start, run_end, run_lines = _flush_comment_run(findings, run_start, run_end, run_lines)

            if ttype == tokenize.STRING:
                if _opens_its_line(lines, tok) and _looks_like_triple_quoted(tok.string):
                    _docstring_like_finding(findings, lines, tok.start[0] - 1, tok.end[0] - 1)
                i += 1
                continue

            if ttype == tokenize.FSTRING_START:
                end_idx = _fstring_end_index(chunk, i)
                if end_idx is not None:
                    if _opens_its_line(lines, tok) and _looks_like_triple_quoted(tok.string):
                        _docstring_like_finding(
                            findings, lines, tok.start[0] - 1, chunk[end_idx].end[0] - 1
                        )
                    i = end_idx + 1
                else:
                    i += 1
                continue

            i += 1

        run_start, run_end, run_lines = _flush_comment_run(findings, run_start, run_end, run_lines)

    return findings


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


def _malformed_repo_config(config_path, reason):
    _warn(
        f"malformed repo config at {config_path} ({reason}) - id allowlist "
        "disabled for this repo, bright line stays enforced"
    )
    return frozenset()


def _repo_id_prefix_allowlist(file_path):
    config_path = _find_repo_config_path(file_path)
    if config_path is None:
        return frozenset()
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        return _malformed_repo_config(config_path, f"{type(exc).__name__}: {exc}")
    if not isinstance(config, dict):
        return _malformed_repo_config(config_path, "top-level JSON value is not an object")
    if _ID_ALLOWLIST_CONFIG_KEY not in config:
        return frozenset()
    prefixes = config[_ID_ALLOWLIST_CONFIG_KEY]
    if not (isinstance(prefixes, list) and all(
        isinstance(p, str) and _ID_PREFIX_SHAPE_RE.match(p) for p in prefixes
    )):
        return _malformed_repo_config(
            config_path, f"'{_ID_ALLOWLIST_CONFIG_KEY}' must be a list of 2-6 letter lowercase prefixes"
        )
    return frozenset(prefixes)


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


def _test_docstring_violation(name, row):
    return (
        f"BLOCKED - '{name}' near line {row} opens with a docstring. A test has "
        "no caller, so no test docstring is an external quirk or an algorithm's "
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
    violations = _filename_violations(file_path, allowed_prefixes)
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


def _flush_yaml_comment_run(findings, run_start, run_lines):
    if run_start is not None:
        span = (run_start + 1, run_start + len(run_lines))
        is_dead_config = len(run_lines) > YAML_COMMENT_RUN_LINE_THRESHOLD and _looks_like_dead_config(run_lines)
        if len(run_lines) > YAML_COMMENT_RUN_LINE_THRESHOLD:
            if is_dead_config:
                findings.append((_dead_config_finding(len(run_lines), run_start), span))
            else:
                findings.append((_comment_run_finding(len(run_lines), run_start), span))
        if not is_dead_config and _has_evidence_marker("\n".join(run_lines)):
            findings.append((_evidence_finding("Comment", run_start), span))
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
    for match in _JINJA_COMMENT_RE.finditer(text):
        start_li = text[:match.start()].count("\n")
        block_len = match.group().count("\n") + 1
        span = (start_li + 1, start_li + block_len)
        if block_len > JINJA_BLOCK_LINE_THRESHOLD:
            findings.append((_jinja_block_finding(block_len, start_li), span))
        if _has_evidence_marker(match.group()):
            findings.append((_evidence_finding("Jinja comment block", start_li), span))
    return findings


YAML_DESCRIPTION_LINE_THRESHOLD = 12
_DESCRIPTION_KEY = "description"


def _description_block_finding(findings, lines, header_li, block_start, block_end):
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


def find_yaml_findings(text):
    lines = _split_rows(text)
    findings = list(_jinja_comment_findings(text))
    run_start = None
    run_lines = []

    li = 0
    while li < len(lines):
        line = lines[li]
        header = _block_scalar_header(line)
        if header is not None:
            run_start, run_lines = _flush_yaml_comment_run(findings, run_start, run_lines)
            header_indent, key = header
            block_start = li + 1
            last_content, next_li = _block_scalar_extent(lines, header_indent, block_start)
            if key == _DESCRIPTION_KEY:
                _description_block_finding(findings, lines, li, block_start, last_content)
            li = next_li
            continue

        col = _yaml_comment_start(line)
        if col is not None and line[:col].strip() == "":
            if run_start is None:
                run_start = li
            run_lines.append(line)
            li += 1
            continue

        run_start, run_lines = _flush_yaml_comment_run(findings, run_start, run_lines)
        if col is not None and _has_evidence_marker(line[col:]):
            findings.append((_evidence_finding("Comment", li), (li + 1, li + 1)))
        li += 1

    run_start, run_lines = _flush_yaml_comment_run(findings, run_start, run_lines)
    return findings


_STATE_COMMENT_KEY = "comment_lines"
_STATE_CODE_KEY = "code_lines"


def _warn(message):
    print(f"comment_intent_guard: {message}", file=sys.stderr)


def _load_state(state_path):
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        _warn(f"unreadable state at {state_path} ({type(exc).__name__}) - starting fresh")
        return {}
    if not isinstance(state, dict):
        _warn(f"unexpected state shape at {state_path} - starting fresh")
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
_DEFAULT_STATE_PATH = os.path.expanduser("~/.claude/hooks/state/comment_guard.json")


def _state_path():
    return os.environ.get(_STATE_PATH_ENV) or _DEFAULT_STATE_PATH


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
                "COMMENT INTENT - bright line violated:\n\n" + "\n\n".join(violations)
            ),
        }
    }


def _findings_for_file(file_path, text):
    if file_path.endswith(".py"):
        blocking = find_blocking_violations(text, file_path)
        try:
            advisory = find_misplaced_rationale(text)
        except AnalysisUnavailable as exc:
            exc.blocking = blocking
            raise
        return blocking, advisory
    if file_path.endswith((".yaml", ".yml")):
        return [], find_yaml_findings(text)
    return [], []


_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _added_line_numbers(base_ref, file_path):
    repo_dir = os.path.dirname(file_path) or "."
    rel_path = os.path.basename(file_path)
    try:
        status = subprocess.run(
            ["git", "-C", repo_dir, "status", "--porcelain", "--", rel_path],
            capture_output=True, text=True,
        )
        if status.returncode == 0 and status.stdout.startswith("??"):
            return None  # untracked - every line in the file is new
        result = subprocess.run(
            ["git", "-C", repo_dir, "diff", "--unified=0", base_ref, "--", rel_path],
            capture_output=True, text=True,
        )
    except OSError as exc:
        _warn(
            f"could not run git diff for {file_path} ({type(exc).__name__}) - "
            "not filtering findings for this file"
        )
        return None
    if result.returncode != 0:
        _warn(
            f"git diff against {base_ref} failed for {file_path} "
            f"(exit {result.returncode}) - not filtering findings for this file"
        )
        return None
    added = set()
    for line in result.stdout.splitlines():
        match = _HUNK_HEADER_RE.match(line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        added.update(range(start, start + count))
    return added


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


def _cli_main(argv):
    parser = argparse.ArgumentParser(prog="comment_intent_guard")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--base")
    mode.add_argument("--all", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    try:
        any_error = False
        any_blocking = False
        any_advisory = False
        for file_path in args.files:
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

            if args.base:
                added = _added_line_numbers(args.base, file_path)
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
        if not (is_python or is_yaml):
            return

        text = _extract_added_text(tool_name, tool_input)
        if not text:
            return

        if is_python:
            violations = [message for message, _ in find_blocking_violations(text, file_path)]
            if violations:
                print(json.dumps(_deny_payload(violations)))
                return

            findings = [message for message, _ in find_misplaced_rationale(text)]
            findings.extend(_density_findings(payload.get("session_id"), text))
        else:
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
    if len(sys.argv) > 1:
        sys.exit(_cli_main(sys.argv[1:]))
    _hook_main()


if __name__ == "__main__":
    main()

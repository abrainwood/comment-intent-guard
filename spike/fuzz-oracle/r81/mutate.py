import shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = (ROOT / "comment_intent_guard.py").read_text()
TESTS = ["test_csharp_lex_never_raises_on_seeded_char_soup",
         "test_csharp_lex_span_rows_and_close_columns_stay_within_the_text",
         "test_csharp_lex_tokens_stay_within_the_text_and_in_non_decreasing_row_order",
         "test_csharp_try_skip_literal_end_is_in_bounds_and_within_its_line_for_plain_strings",
         "test_csharp_lex_is_idempotent_under_crlf_line_endings_outside_quoted_literal_edge_cases"]
SHORT = ["raises", "spans", "tokens", "skip_end", "crlf"]

MUTANTS = {
 "raise_on_hash_midline": ('        line_start = False\n\n        literal_end', '        line_start = False\n        if ch == "#":\n            raise ValueError("boom")\n\n        literal_end'),
 "literal_row_overshoot": ('            row += text.count("\\n", i, literal_end)\n', '            row += text.count("\\n", i, literal_end) + (1 if literal_end >= n else 0)\n'),
 "block_end_li_plus1": ('            end_li = start_li + text.count("\\n", i, close)\n', '            end_li = start_li + text.count("\\n", i, close) + 1\n'),
 "literal_count_includes_next_char": ('            row += text.count("\\n", i, literal_end)\n', '            row += text.count("\\n", i, literal_end + 1)\n'),
 "block_row_end_minus1": ('            row = end_li\n            i = close + 2\n', '            row = end_li - 1\n            i = close + 2\n'),
 "close_col_plus1": ('            close_col = close - (text.rfind("\\n", 0, close) + 1)\n', '            close_col = close - text.rfind("\\n", 0, close)\n'),
 "close_col_plus2": ('            close_col = close - (text.rfind("\\n", 0, close) + 1)\n', '            close_col = close - text.rfind("\\n", 0, close) + 1\n'),
 "close_col_is_end": ('            close_col = close - (text.rfind("\\n", 0, close) + 1)\n', '            close_col = close + 2 - (text.rfind("\\n", 0, close) + 1)\n'),
 "block_row_reset_start": ('            row = end_li\n            i = close + 2\n', '            row = start_li\n            i = close + 2\n'),
 "string_ignores_newline": ('    while i < n and text[i] != "\\n":\n        if text[i] == "\\\\" and i + 1 < n:', '    while i < n:\n        if text[i] == "\\\\" and i + 1 < n:'),
 "string_end_past_n": ('            return i + 1\n        i += 1\n    return i\n\n\ndef _csharp_dollar', '            return i + 1\n        i += 1\n    return i + 1\n\n\ndef _csharp_dollar'),
 "verbatim_eof_past_n": ('            return i + 1\n        i += 1\n    return i\n\n\ndef _csharp_skip_string', '            return i + 1\n        i += 1\n    return i + 1\n\n\ndef _csharp_skip_string'),
 "S_nonverbatim_ignores_newline": ('            if not verbatim and ch == "\\n":\n                stack.pop()\n                continue\n            if ch == "{" and i + 1 < n and text[i + 1] == "{":', '            if ch == "{" and i + 1 < n and text[i + 1] == "{":'),
 "H_nonverbatim_ignores_newline": ('            if not verbatim and text[i] == "\\n":\n                stack.pop()\n                continue\n', ''),
 "cr_counts_as_newline": ('        if ch == "\\n":\n            row += 1', '        if ch in "\\r\\n":\n            row += 1'),
 "raw_eof_past_n": ('            i += close_run\n            continue\n        i += 1\n    return i\n\n\ndef _csharp_skip_verbatim', '            i += close_run\n            continue\n        i += 1\n    return i + 1\n\n\ndef _csharp_skip_verbatim'),
 "stack_eof_overshoot": ('        if i >= n:\n            stack.pop()\n            continue\n', '        if i >= n:\n            stack.pop()\n            i += 1\n            continue\n'),
 "char_literal_newline": ('    if i < n and text[i] == "\\\\" and i + 1 < n:\n        i += 2\n    elif i < n:\n        i += 1\n    if i < n and text[i] == "\'":', '    while i < n and text[i] != "\'":\n        i += 1\n    if i < n and text[i] == "\'":'),
 "directive_row_drift": ('                spans.append(("line", row, row, directive[comment_at + 2:], None))', '                spans.append(("line", row, row + 1, directive[comment_at + 2:], None))'),
 "doc_merge_end_plus1": ('                spans[-1] = (prev_kind, prev_start, li, f"{prev_content}\\n{content}", None)', '                spans[-1] = (prev_kind, prev_start, li + 1, f"{prev_content}\\n{content}", None)'),
 "unterminated_block_eats_rest": ('                eol = text.find("\\n", i)\n                end = n if eol == -1 else eol\n                spans.append((block_kind, start_li, start_li, text[i + 2:end], None))', '                end = n\n                spans.append((block_kind, start_li, start_li, text[i + 2:end], None))'),
}

only = sys.argv[1:]
for name, (old, new) in MUTANTS.items():
    if only and name not in only:
        continue
    if SRC.count(old) != 1:
        print(f"{name}: PATTERN COUNT {SRC.count(old)}"); continue
    d = Path(tempfile.mkdtemp(prefix="r81-"))
    (d / "comment_intent_guard.py").write_text(SRC.replace(old, new))
    shutil.copytree(ROOT / "tests", d / "tests")
    shutil.copy(ROOT / "pytest.ini", d / "pytest.ini")
    res = []
    msgs = []
    for t, s in zip(TESTS, SHORT):
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", f"tests/test_csharp_analyser.py::{t}"], cwd=d, capture_output=True, text=True)
        if p.returncode:
            res.append(s.upper())
            line = next((l for l in p.stdout.splitlines() if l.startswith("E ") and "seed index" in l), None) or next((l for l in p.stdout.splitlines() if l.startswith("E ")), "")
            msgs.append(f"   {s}: {line[:200]}")
        else:
            res.append(s)
    print(f"{name}: {' '.join(res)}")
    print("\n".join(msgs))
    shutil.rmtree(d)

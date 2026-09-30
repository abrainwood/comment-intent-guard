import subprocess, sys, shutil
S=sys.argv[1]; P=f"{S}/mut/comment_intent_guard.py"; orig=open(f"{S}/guard_head.py").read()
M = {
"M1 strip_trailing: ignore // comments": ('            out.append(text[last:i])\n            return li, "".join(out)\n        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":', '            pass\n        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":'),
"M2 strip_trailing: no literal skip": ('''def _csharp_strip_trailing_comments(lines, li, text):
    out = []
    last = 0
    i, n = 0, len(text)
    while i < n:
        literal_end = _csharp_try_skip_literal(text, i)''','''def _csharp_strip_trailing_comments(lines, li, text):
    out = []
    last = 0
    i, n = 0, len(text)
    while i < n:
        literal_end = None'''),
"M3 strip_trailing: don't follow multi-line close": ('''            found = _csharp_find_block_comment_close(lines, li)
            if found is None:
                out.append(text[last:i])
                return li, "".join(out)
            li, text = found''','''            found = None
            if found is None:
                out.append(text[last:i])
                return li, "".join(out)
            li, text = found'''),
"M4 strip_trailing: keep closed comment text": ('                last = close + 2\n                i = close + 2', '                i = close + 2'),
"M5 trailing_group: accept non-empty remainder": ('        if candidate is not None and candidate[2] == "":\n            return candidate\n    return None\n\n\ndef _csharp_skip_comments', '        if candidate is not None:\n            return candidate\n    return None\n\n\ndef _csharp_skip_comments'),
"M6 trailing_group: only first [": ('            return candidate\n    return None\n\n\ndef _csharp_skip_comments', '            return candidate\n        break\n    return None\n\n\ndef _csharp_skip_comments'),
"M8 strip_brackets: no literal skip": ('''def _csharp_strip_attribute_bracket_groups(text):
    out = []
    last = 0
    i, n = 0, len(text)
    while i < n:
        literal_end = _csharp_try_skip_literal(text, i)''','''def _csharp_strip_attribute_bracket_groups(text):
    out = []
    last = 0
    i, n = 0, len(text)
    while i < n:
        literal_end = None'''),
"M9 strip_brackets: identity (both call sites)": ('def _csharp_strip_attribute_bracket_groups(text):\n', 'def _csharp_strip_attribute_bracket_groups(text):\n    return text\n'),
"M9a strip_brackets removed only in after_attribute_lines": ('    match = _CSHARP_METHOD_NAME_RE.search(_csharp_strip_attribute_bracket_groups(rest))\n    return ((match.group(1), li + 1)', '    match = _CSHARP_METHOD_NAME_RE.search(rest)\n    return ((match.group(1), li + 1)'),
"M9b strip_brackets removed only in after_doc_close": ('        match = _CSHARP_METHOD_NAME_RE.search(_csharp_strip_attribute_bracket_groups(rest))\n        return ((match.group(1), resolved_li + 1)', '        match = _CSHARP_METHOD_NAME_RE.search(rest)\n        return ((match.group(1), resolved_li + 1)'),
"M10 doc_trailing: always empty": ('    last_content_line = content.rsplit("\\n", 1)[-1]\n', '    return ""\n'),
"M11 doc_trailing: off-by-one +1": ('    return lines[end_li][close_idx + len(last_content_line) + 2:]', '    return lines[end_li][close_idx + len(last_content_line) + 1:]'),
"M11b doc_trailing: -1 -> whole line": ('    if close_idx == -1:\n        return ""', '    if close_idx == -1:\n        return lines[end_li]'),
"M12 after_doc_close: drop leading attr names": ('    return found, attribute_names + more_names', '    return found, more_names'),
"M12b after_doc_close: row off by one": ('        return ((match.group(1), resolved_li + 1) if match', '        return ((match.group(1), resolved_li + 2) if match'),
"M13 after_doc_close: non-attr trailing falls back to next line": ('    if group is None:\n        return None, []\n    attrs_text, resolved_li, rest = group', '    if group is None:\n        return _csharp_method_signature_after_attribute_lines(spans, lines, end_li + 1)\n    attrs_text, resolved_li, rest = group'),
"M14 own_line: accept non-empty remainder": ('        if own_group is None or own_group[2] != "":', '        if own_group is None:'),
"M15 own_line: drop single-line check": ('        if kind == "doc" and span_li == start_li and end_li == start_li:', '        if kind == "doc" and span_li == start_li:'),
"M16 li<0 returns False": ('    if li < 0:\n        return any(_is_csharp_test_attribute(n) for n in attribute_names)', '    if li < 0:\n        return False'),
"M17 enclosing check back after line group": ('''        block_span = _csharp_enclosing_block_span(spans, li)
        if block_span is not None:
            li = block_span[1]
            continue
        group = _csharp_line_attribute_group(lines, li, close_li)
        if group is not None:
            break
''','''        group = _csharp_line_attribute_group(lines, li, close_li)
        if group is not None:
            break
        block_span = _csharp_enclosing_block_span(spans, li)
        if block_span is not None:
            li = block_span[1]
            continue
'''),
"M18 leading_block: block only": ('    if not any(s[0] in ("block", "doc") and s[1] == li for s in spans):', '    if not any(s[0] == "block" and s[1] == li for s in spans):'),
"M19 remove mixed-line else branch": ('''        else:
            mixed_line_group = _csharp_trailing_attribute_group(lines, li, lines[li], close_li)
            if mixed_line_group is not None:''','''        else:
            mixed_line_group = None
            if mixed_line_group is not None:'''),
"M20 remove leading deep_group": ('''                deep_group = _csharp_trailing_attribute_group(lines, end_li, tail, close_li)
                if deep_group is not None:
                    group = deep_group''','''                deep_group = None
                if deep_group is not None:
                    group = deep_group'''),
"M21 remove remainder deep_group": ('''    if remainder != "":
        deep_group = _csharp_trailing_attribute_group(lines, remainder_li, remainder, close_li)''','''    if False:
        deep_group = _csharp_trailing_attribute_group(lines, remainder_li, remainder, close_li)'''),
"M22 remainder deep_group ends_walk False": ('deep_li, deep_remainder, True)', 'deep_li, deep_remainder, False)'),
"M23 is_javadoc revert to main": ('not (i + 3 < n and text[i + 3] in ("*", "/"))', 'text[i + 2:i + 4] != "*/"'),
"M24 is_javadoc drop / check": ('not (i + 3 < n and text[i + 3] in ("*", "/"))', 'not (i + 3 < n and text[i + 3] in ("*",))'),
"M25 second after-close call reverted": ('            found, _attribute_names = _csharp_method_signature_after_doc_close(spans, lines, end_li, content)', '            found, _attribute_names = _csharp_method_signature_after_attribute_lines(spans, lines, end_li + 1)'),
"M26 own_line: prefix uses rstrip? no - offset -2": ('            prefix_len = len(lines[start_li]) - len(content) - 3', '            prefix_len = len(lines[start_li]) - len(content) - 2'),
}

M.pop("M6 trailing_group: only first [")
M.pop("M10 doc_trailing: always empty"); M.pop("M11 doc_trailing: off-by-one +1"); M.pop("M11b doc_trailing: -1 -> whole line")
M.update({
"M6 trailing_group: only first [": ('        start = projected.find("[", start + 1)', '        start = -1'),
"M10 doc_trailing: always empty": ('    if close_col is None:\n        return ""\n    return lines[end_li][close_col + 2:]', '    return ""'),
"M11 doc_trailing: +2 -> +1": ('    return lines[end_li][close_col + 2:]', '    return lines[end_li][close_col + 1:]'),
"N1 close_col relative to start line": ('close_col = close - (text.rfind("\\n", 0, close) + 1)', 'close_col = close - (text.rfind("\\n", 0, i) + 1)'),
"N3 drop round-2 comment skip": ('    skip_li, rest_after_comments = _csharp_skip_comments(lines, end_li, trailing)\n    if rest_after_comments == "":', '    skip_li, rest_after_comments = end_li, trailing\n    if rest_after_comments == "":'),
"N4 skip_li+1 -> end_li+1": ('        return _csharp_method_signature_after_attribute_lines(spans, lines, skip_li + 1)', '        return _csharp_method_signature_after_attribute_lines(spans, lines, end_li + 1)'),
"N5 keep end_li after skip": ('    end_li, trailing = skip_li, rest_after_comments', '    trailing = rest_after_comments'),
"N6 merged doc span close_col -> None": ('f"{prev_content}\\n{content}", prev_close_col)', 'f"{prev_content}\\n{content}", None)'),
"N7 drop [Fact] from backward merge": ('_CSharpBackwardAttributeGroup(f"{attrs_text} {deep_attrs}", deep_li', '_CSharpBackwardAttributeGroup(deep_attrs, deep_li'),
"N8 close_col always None": ('            close_col = None\n            if close != -1:', '            close_col = None\n            if False:'),
})
only=sys.argv[2:] 
for name,(a,b) in M.items():
    if only and not any(name.startswith(o+" ") for o in only): continue
    c=orig.count(a)
    if c!=1: print(name,"BAD PATTERN count",c); continue
    open(P,"w").write(orig.replace(a,b))
    r=subprocess.run([sys.executable,"-m","pytest","-q","-x","--timeout=30","-p","no:cacheprovider","-n","0","tests/test_csharp_analyser.py"],cwd=f"{S}/mut",capture_output=True,text=True)
    tail=[l for l in r.stdout.splitlines() if l.startswith("FAILED") or "passed" in l or "failed" in l]
    print(("KILLED  " if r.returncode else "SURVIVED"), name, "|", tail[0][:150] if tail else r.stdout[-200:])
open(P,"w").write(orig)

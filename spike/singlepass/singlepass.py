_CSHARP_STOP_BEFORE_NAME = frozenset({";", "{", "}", "=", "=>"})
_CSHARP_MEMBER_BOUNDARY = frozenset({";", "{", "}", "]"})


class _CSharpToken(NamedTuple):
    text: str
    row: int


def _csharp_is_doc_opener(text, i):
    if text.startswith("///", i):
        return not text.startswith("////", i)
    return text.startswith("/**", i) and text[i + 3:i + 4] not in ("*", "/")


def _csharp_code_tokens(text):
    tokens, doc_anchors = [], []
    i, n, row, line_start = 0, len(text), 0, True
    while i < n:
        ch = text[i]
        if ch == "\n":
            row, line_start, i = row + 1, True, i + 1
            continue
        if ch in " \t\r\f\v":
            i += 1
            continue
        if ch == "#" and line_start:
            eol = text.find("\n", i)
            i = n if eol == -1 else eol
            continue
        line_start = False
        if text.startswith("//", i) or text.startswith("/*", i):
            if _csharp_is_doc_opener(text, i):
                doc_anchors.append(len(tokens))
            if text[i + 1] == "/":
                eol = text.find("\n", i)
                i = n if eol == -1 else eol
                continue
            close = text.find("*/", i + 2)
            end = n if close == -1 else close + 2
            row += text.count("\n", i, end)
            i = end
            continue
        literal_end = _csharp_try_skip_literal(text, i)
        if literal_end is not None:
            tokens.append(_CSharpToken('"', row))
            row += text.count("\n", i, literal_end)
            i = literal_end
            continue
        if ch.isalnum() or ch in "_@":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(_CSharpToken(text[i:j], row))
            i = j
            continue
        width = 2 if text.startswith("=>", i) else 1
        tokens.append(_CSharpToken(text[i:i + width], row))
        i += width
    return tokens, doc_anchors


def _csharp_matching_bracket(tokens, k, step):
    opener, closer = ("[", "]") if step > 0 else ("]", "[")
    depth = 0
    while 0 <= k < len(tokens):
        if tokens[k].text == opener:
            depth += 1
        elif tokens[k].text == closer:
            depth -= 1
            if depth == 0:
                return k
        k += step
    return None


def _csharp_opens_attribute_section(tokens, k):
    return tokens[k].text == "[" and (k == 0 or tokens[k - 1].text in _CSHARP_MEMBER_BOUNDARY)


def _csharp_attribute_sections_before(tokens, k):
    sections = []
    while k > 0 and tokens[k - 1].text == "]":
        open_k = _csharp_matching_bracket(tokens, k - 1, -1)
        if open_k is None or not _csharp_opens_attribute_section(tokens, open_k):
            break
        sections.append((open_k, k))
        k = open_k
    return sections


def _csharp_attribute_sections_after(tokens, k):
    sections = []
    while k < len(tokens) and _csharp_opens_attribute_section(tokens, k):
        close_k = _csharp_matching_bracket(tokens, k, 1)
        if close_k is None:
            break
        sections.append((k, close_k + 1))
        k = close_k + 1
    return sections, k


def _csharp_attribute_names(tokens, sections):
    names = []
    for start, end in sections:
        depth = 0
        for k in range(start, end):
            text = tokens[k].text
            depth += text in "([" and 1 or 0
            depth -= text in ")]" and 1 or 0
            if depth == 1 and tokens[k - 1].text in "[,:" and (text[0].isalpha() or text[0] == "_"):
                dotted = k
                while dotted + 2 < end and tokens[dotted + 1].text == "." :
                    dotted += 2
                names.append(tokens[dotted].text)
    return names


def _csharp_declared_method_name(tokens, k):
    while k < len(tokens) and tokens[k].text not in _CSHARP_STOP_BEFORE_NAME:
        if tokens[k].text == "(":
            name_k = k - 1
            if tokens[name_k].text == ">":
                depth = 0
                while name_k >= 0:
                    depth += {">": 1, "<": -1}.get(tokens[name_k].text, 0)
                    if depth == 0:
                        break
                    name_k -= 1
                name_k -= 1
            return tokens[name_k] if name_k >= 0 and tokens[name_k].text[0].isalpha() else None
        k += 1
    return None


def _csharp_test_doc_blocking_violations(text):
    tokens, doc_anchors = _csharp_code_tokens(text)
    violations, seen_rows = [], set()
    for anchor in doc_anchors:
        before = _csharp_attribute_sections_before(tokens, anchor)
        after, declaration_k = _csharp_attribute_sections_after(tokens, anchor)
        names = _csharp_attribute_names(tokens, before + after)
        if not any(_is_csharp_test_attribute(n) for n in names):
            continue
        name = _csharp_declared_method_name(tokens, declaration_k)
        if name is None or name.row in seen_rows:
            continue
        seen_rows.add(name.row)
        row = name.row + 1
        violation = _test_docstring_violation(name.text, row, "an XML doc comment", "XML doc comment")
        violations.append((violation, (row, row)))
    return violations

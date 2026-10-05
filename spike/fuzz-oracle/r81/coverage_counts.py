import collections, importlib.util, re, sys, statistics
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t", ROOT / "tests/test_csharp_analyser.py"); t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
g = t.guard
cases = list(t._csharp_soup_cases(t._CSHARP_SOUP_SEED, t._CSHARP_SOUP_CASE_COUNT))
lens = [len(c) for c in cases]
print("cases", len(cases), "chars min/median/max", min(lens), statistics.median(lens), max(lens))
feat = collections.Counter()
frames = collections.Counter()
orig = g._csharp_push_literal
def push(opened, stack):
    frames[opened[0] if opened[0] != "S" else ("S-verbatim" if opened[1] else "S-plain")] += 1
    if opened[0] == "R": frames[f"R dollars={opened[2]}"] += 1
    return orig(opened, stack)
g._csharp_push_literal = push
for c in cases:
    for name, pat in {"$$\"\"\"": '$$"""', "{{": "{{", "#": "#", "\\r\\n": "\r\n", "$@\"": '$@"', "@$\"": '@$"', "///": "///", "/**(doc)": None}.items():
        if pat and pat in c: feat[name] += 1
    if re.search(r'(^|\n)[ \r]*#', c): feat["# at line start (directive)"] += 1
    if re.search(r'(^|\n)[ \r]*#[^\n]*//', c): feat["directive with //"] += 1
    if g._csharp_is_doc_opener(c, c.find("/**")) if "/**" in c else False: feat["/** doc opener"] += 1
    spans, toks, anchors = g._csharp_lex(c)
    if any(s[0] == "doc" and s[2] > s[1] for s in spans): feat["merged/multiline doc span"] += 1
    if any(s[0] == "block" and s[4] is not None and s[2] > s[1] for s in spans): feat["multiline closed block"] += 1
    if any(s[4] is None and s[0] == "block" for s in spans): feat["unterminated /*"] += 1
    for i in range(len(c)):
        e = g._csharp_try_skip_literal(c, i)
        if e == len(c) and not c.endswith('"'):
            feat["literal unterminated at EOF"] += 1; break
    for i in range(len(c)):
        if c[i] == '"' and not c.startswith('""', i) and (i == 0 or c[i-1] not in '$@"'):
            e = g._csharp_try_skip_literal(c, i)
            if "\\\n" in c[i:e]: feat["plain string end crosses via \\\\+LF"] += 1; break
    for i in range(len(c)):
        if c.startswith('$"', i) and (i == 0 or c[i-1] not in "$@") and not c.startswith('$"""', i):
            e = g._csharp_try_skip_literal(c, i)
            if "\n" in c[i:e-1]: feat["$\" literal spans a newline"] += 1; break
    if "'" not in c and "\\\n" not in c: feat["CRLF-test eligible"] += 1
    if not re.search(r"'\\?\n|\\\n", c): feat["CRLF-eligible under narrow exclusion"] += 1
for k, v in sorted(feat.items()): print(f"{k:45s} {v:6d}  {100*v/len(cases):5.1f}%")
for k, v in sorted(frames.items(), key=str): print(f"frame {k:39s} {v:6d}")

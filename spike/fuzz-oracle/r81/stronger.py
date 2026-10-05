import importlib.util, sys
from pathlib import Path
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3]
TROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("g", ROOT / "comment_intent_guard.py"); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
spec = importlib.util.spec_from_file_location("t", TROOT / "tests/test_csharp_analyser.py"); t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
cases = list(t._csharp_soup_cases(t._CSHARP_SOUP_SEED, t._CSHARP_SOUP_CASE_COUNT))
hits = {}
def bad(name, i, s):
    hits.setdefault(name, (i, s))
for i, s in enumerate(cases):
    lines = s.split("\n")
    try: spans, toks, _ = g._csharp_lex(s)
    except Exception: bad("raise", i, s); continue
    for kind, a, b, content, cc in spans:
        parts = content.split("\n")
        if not (0 <= a <= b < len(lines)): bad("rows", i, s); continue
        if cc is not None:
            if not lines[b].startswith("*/", cc): bad("close_col_marks_*/", i, s)
            if not lines[b][:cc].endswith(parts[-1]) or (len(parts) > 1 and not lines[a].endswith(parts[0])): bad("closed_block_content_located", i, s)
        else:
            if len(parts) != b - a + 1 or any(not lines[a + k].endswith(p) for k, p in enumerate(parts)):
                bad("open_span_content_located", i, s)
    for p in range(len(s)):
        e = g._csharp_try_skip_literal(s, p)
        if e is None: continue
        if s[p] == "'" and e - p not in (1, 3, 4): bad("char_literal_width", i, s)
        if s.startswith('$"', p) and not s.startswith('$"""', p) and (p == 0 or s[p-1] not in "$@"):
            lim = t._csharp_soup_first_newline_limit(s, p)
            seg = s[p:lim]
            if "@" not in seg and "'" not in seg and '"""' not in seg and e > lim: bad("interp_string_within_line", i, s)
print(ROOT.name, {k: (v[0], v[1][:60]) for k, v in hits.items()} or "clean")

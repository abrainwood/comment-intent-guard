import importlib.util, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("t", ROOT / "tests/test_csharp_analyser.py"); t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
g = t.guard
def rows(text):
    spans, tokens, _ = g._csharp_lex(text)
    return [(k, a, b, c) for k, a, b, _x, c in spans], [(x.text, x.row) for x in tokens]
EXCL = {
  "pr": lambda s: "'" in s or "\\\n" in s,
  "narrow_char_quote+bs_nl": lambda s: re.search(r"'\\?\n'", s) or "\\\n" in s,
  "narrow_char_only": lambda s: re.search(r"'\\?\n'", s),
  "narrow_bs_only": lambda s: "\\\n" in s,
}
for seed, count in [(t._CSHARP_SOUP_SEED, 20000), (1, 200000)]:
    cases = list(t._csharp_soup_cases(seed, count))
    for name, ex in EXCL.items():
        checked = fails = 0; first = None
        for i, s in enumerate(cases):
            if ex(s): continue
            checked += 1
            if rows(s) != rows(s.replace("\n", "\r\n")):
                fails += 1; first = first or (i, s)
        print(f"seed={seed} n={count} {name:26s} checked={checked:6d} fails={fails} first={first!r}"[:260])

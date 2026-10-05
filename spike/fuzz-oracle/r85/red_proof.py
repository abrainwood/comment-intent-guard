import sys
sys.path.insert(0, "tests")
import test_csharp_analyser as t

guard = t.guard


def old_oracle(text):
    lines = text.split("\n")
    spans, _, _ = guard._csharp_lex(text)
    for _k, s, e, content, cc in spans:
        assert 0 <= s <= e < len(lines)
        parts = content.split("\n")
        if cc is not None:
            assert 0 <= cc <= len(lines[e])
            assert lines[e].startswith("*/", cc)
            assert lines[e][:cc].endswith(parts[-1])
            if len(parts) > 1:
                assert lines[s].endswith(parts[0])
        else:
            assert len(parts) == e - s + 1
            assert all(lines[s + k].endswith(p) for k, p in enumerate(parts))


direct = ["/** a */\n///x\n", "/** a */ junk\n///x\n", "/** d\n */\n/// doc\n"]
for d in direct:
    try:
        old_oracle(d)
        print("OLD PASSES (no RED):", repr(d))
    except AssertionError:
        print("OLD FAILS (RED ok):", repr(d))

n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
for seed in (t._CSHARP_SOUP_SEED, 1):
    fails = []
    for i, text in enumerate(t._csharp_soup_cases(seed, n)):
        try:
            old_oracle(text)
        except AssertionError:
            fails.append((i, text))
    print(f"seed {seed} n={n}: old-oracle failures={len(fails)}", fails[:3])

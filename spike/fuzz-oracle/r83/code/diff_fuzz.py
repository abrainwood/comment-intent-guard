import random, re, sys, importlib.util
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
M = load("m", "main_guard.py"); B = load("b", "branch_guard.py")
ALPHA = ['"', "'", '$"', '@"', '$@"', '\\', '\\', '\n', '{', '}', '// c', 'x', ' ', '"""', '$$"', '/*', '*/', 'a']
def gen(r, bare_cr=False):
    alpha = ALPHA + (['\r'] if bare_cr else [])
    return "".join(r.choice(alpha) for _ in range(r.randint(1, 14)))
def rows(mod, t):
    spans, toks, _ = mod._csharp_lex(t)
    return [(s[0], s[1], s[2]) for s in spans], [(k.text, k.row) for k in toks]
def full(mod, t):
    spans, toks, _ = mod._csharp_lex(t)
    return [tuple(s) for s in spans], [(k.text, k.row) for k in toks]
ISSUE = re.compile(r"\\\n|'\n")
def run(n, seed, bare_cr):
    r = random.Random(seed); stats = dict(cases=0, parity_fail=0, lf_div=0, lf_div_nonissue=0, crlf_div=0, crlf_div_nonissue=0, main_parity_fail=0)
    ex = {}
    for _ in range(n):
        t = gen(r, bare_cr); c = t.replace("\n", "\r\n"); stats["cases"] += 1
        if rows(B, t) != rows(B, c): stats["parity_fail"] += 1; ex.setdefault("parity_fail", t)
        if rows(M, t) != rows(M, c): stats["main_parity_fail"] += 1
        for tag, x in (("lf", t), ("crlf", c)):
            if full(M, x) != full(B, x):
                stats[tag + "_div"] += 1
                if not ISSUE.search(t):
                    stats[tag + "_div_nonissue"] += 1; ex.setdefault(tag + "_nonissue", [])
                    if len(ex[tag + "_nonissue"]) < 6: ex[tag + "_nonissue"].append(x)
    print(f"seed={seed} bare_cr={bare_cr}", stats)
    for k, v in ex.items(): print("  ", k, repr(v))
if __name__ == "__main__":
    run(int(sys.argv[1]), 83, False)
    run(int(sys.argv[1]), 84, True)

import importlib.util, sys
def load(p):
    s = importlib.util.spec_from_file_location("m", p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
cases = ["char c = '\n// c\n", "char c = '\\\n// c\n", "char c = '\n'\"'// c\n", "char c = '\\\n'\"'// c\n"]
for p in sys.argv[1:]:
    g = load(p)
    for t in cases:
        lf = [(k, a, b) for k, a, b, _c, _x in g._csharp_lex(t)[0]]
        cr = [(k, a, b) for k, a, b, _c, _x in g._csharp_lex(t.replace("\n", "\r\n"))[0]]
        ok = lf == cr == [("line", 1, 1)]
        print(f"{p.split('/')[-1]:32} {t!r:28} {'pass' if ok else 'FAIL'} lf={lf} crlf={cr}")

import importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
def load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
head = load("head", os.path.join(HERE, "..", "..", "..", "comment_intent_guard.py"))
W = {
    "RH_code_brace_no_depth_inc": '$$"""{{ new { a } + """q""" }}"""',
    "S_no_open_escape": '$"{{ x"',
    "R_open_needs_more_braces": '$$"""{{ """a""" }}"""',
}
for name, t in W.items():
    m = load(name, os.path.join(HERE, "mut2", name, "comment_intent_guard.py"))
    print(f"{name:28s} {t!r:40s} head={head._csharp_try_skip_literal(t,0)} mutant={m._csharp_try_skip_literal(t,0)} len={len(t)}")
t = 'var s = $"{{"; // c\n'
m = load("S_no_open_escape2", os.path.join(HERE, "mut2", "S_no_open_escape", "comment_intent_guard.py"))
print("S_no_open_escape spans", list(head._csharp_comment_spans(t)), list(m._csharp_comment_spans(t)))

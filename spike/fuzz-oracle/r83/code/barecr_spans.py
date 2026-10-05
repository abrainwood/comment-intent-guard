import random
from diff_fuzz import M, B, gen, ISSUE
r = random.Random(7); n = d = 0; ex = []
for _ in range(50000):
    t = gen(r, True)
    if "\r" not in t or ISSUE.search(t): continue
    n += 1
    if M._csharp_lex(t)[0] != B._csharp_lex(t)[0]:
        d += 1; ex.append(t) if len(ex) < 5 else None
print("bare-CR cases", n, "span divergences", d); [print(repr(e)) for e in ex]

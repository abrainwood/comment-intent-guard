import sys, re, random, itertools, collections, importlib.util
sys.path.insert(0,"."); import oracle3 as o; o.ROSLYN=True; o.JAVADOC=True
src=open("fuzz8.py").read(); V=eval(re.search(r"V=(\[.*?\])\ndef run",src,re.S).group(1))
exec(re.search(r"(def valid\(t\):.*?return True\n)",src,re.S).group(1))
def load(n):
    s=importlib.util.spec_from_file_location(n,n+".py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
mods={n:load(n) for n in sys.argv[1:]}
def run(m,t): return sorted(v[1] for v in m.find_csharp_blocking_violations(t,"/r/T.cs"))
rng=random.Random(66)
def cases():
    for k in range(1,4):
        for c in itertools.product(V,repeat=k): yield list(c)
    for _ in range(3000): yield [rng.choice(V) for _ in range(rng.randint(4,7))]
invalid="public void A() /// t"
cnt=collections.Counter(); ex={}
for body in cases():
    t="\n".join(body+["public void X()","{","}"])+"\n"
    if not valid(t): continue
    e=o.expected(t)
    if e is None: continue
    for n,m in mods.items():
        if run(m,t)!=e:
            k=(n, "invalid_bodyless_A" if invalid in body else "valid")
            cnt[k]+=1
            if k not in ex or len(t)<len(ex[k]): ex[k]=t
for k in sorted(cnt): print(k,cnt[k],repr(ex[k]))

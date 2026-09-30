import importlib.util, sys, random, signal, collections, itertools
S=sys.argv[1]; sys.path.insert(0,S); import oracle3 as oracle; oracle.ROSLYN = sys.argv[2]=='roslyn'; oracle.JAVADOC = True; from oracle3 import expected
N=int(sys.argv[3]); names=sys.argv[4:]
class Hang(Exception): pass
signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(Hang()))
def load(n):
    spec=importlib.util.spec_from_file_location(n,f"{S}/{n}.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
mods={n:load(n) for n in names}
V=["[Fact]","[Obsolete]",'[Trait("x","y")]',"/* c */","/* a","b */","b */ [Fact]","/* c */ [Fact]","/* c */ [Obsolete]",
   "// c","/// doc","/// a","","int y;","public void A() { }","[Fact] public void A() { }","/* c */ int y;","[Fact] /* a",
   "/* a */ /* b */","/* a */ /* b */ [Fact]","/* a */ /* b */ [Obsolete]","/* a */ /* b */ /* c */","/* a */ /* b */ /* c */ [Fact]",
   "/* a */ /* b","[Fact] // c","[Obsolete] // c","// c /* x */","// http://x","/* a */ // c",
   "//// c","[Fact] /// x","[Fact] //// c","int y; /// x","/* a */ /// x","public void A() /// t",
   "/* a */ int q; /* b */ [Fact]","/* a */ int q; /* b */ [Obsolete]","/* a */ [Fact] /* b */ int q;",
   "/* a */ int q; /* b */ [Fact] /* c */","/* a */ int q; // /* b */ [Fact]","/* a */ int q; /* b */ [Obsolete] [Fact]",
   "/* a */ int q; /* b */ [Fact] // c",'/* a */ int q; /* b */ [Fact, Trait("k", "/* */")]',"/* a */ int q; /* b */ [Fact] /* c */ [Obsolete]","/* a */ int q; /* b */ [Obsolete] int r; /* c */ [Fact]","*/ int q; /* b */ [Fact]","*/ int q; /* b */ [Obsolete]","/** d */","/** d","*/","*/ /// x","\t/// doc","\t[Fact]"]
def run(m,t):
    signal.setitimer(signal.ITIMER_REAL,0.5)
    try: return sorted(v[1] for v in m.find_csharp_blocking_violations(t,"/repo/Tests/ThingTests.cs"))
    except Hang: return "HANG"
    finally: signal.setitimer(signal.ITIMER_REAL,0)
def valid(t):
    i=0
    while i<len(t):
        if t.startswith("//",i):
            j=t.find("\n",i); i=len(t) if j==-1 else j; continue
        if t.startswith("/*",i):
            j=t.find("*/",i+2)
            if j==-1: return False
            i=j+2; continue
        if t.startswith("*/",i): return False
        i+=1
    return True
def cases():
    for k in range(1,4):
        for combo in itertools.product(V,repeat=k): yield list(combo)
    rng=random.Random(66)
    for _ in range(N): yield [rng.choice(V) for _ in range(rng.randint(4,7))]
cnt=collections.Counter(); ex={}; diff=collections.Counter(); dex={}; total=0
for body in cases():
    t="\n".join(body+["public void X()","{","}"])+"\n"
    if not valid(t): continue
    e=expected(t)
    if e is None: continue
    total+=1; res={}
    for n,m in mods.items():
        r=run(m,t); res[n]=r
        kind="ok" if r==e else "HANG" if r=="HANG" else "FP" if len(r)>len(e) else "FN" if len(r)<len(e) else "ROW"
        cnt[(n,kind)]+=1
        if kind!="ok" and ((n,kind) not in ex or len(t)<len(ex[(n,kind)])): ex[(n,kind)]=t
    for n in names[1:]:
        if res[n]!=res[names[0]]:
            k=(n,"head_right" if res[names[0]]==e else "mut_right" if res[n]==e else "both_wrong"); diff[k]+=1
            if k not in dex or len(t)<len(dex[k]): dex[k]=t
print("cases",total)
for k in sorted(cnt): print(k,cnt[k],repr(ex.get(k,""))[:200])
print("-- diffs vs",names[0])
for k in sorted(diff): print(k,diff[k],repr(dex[k])[:200])

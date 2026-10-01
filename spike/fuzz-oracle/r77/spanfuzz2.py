import importlib.util,sys,random,collections,re
S=sys.argv[1]
def load(n,p):
    s=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
M=load("m",f"{S}/main/comment_intent_guard.py"); H=load("h",f"{S}/head/comment_intent_guard.py")
F=['int x;','"a // b"','@"q ""/*"" r"','@"multi\nline // x"','$"a{x}b /* c"','$@"{y}\n//z"','"""raw // """','$$"""{{x}} /* """',"'\\''","'/'",
   '// c','/// d','//// e','/* b */','/**/','/*** x */','/** j */','/* m\n l */','x = #1;','"#if /*"','[Fact]','void A(){}','\t','  ',
   '// TODO ABC-123','/// Fixes JIRA-4821','// fixed on 2026-01-05','/// /* nested','// /* nested','int y; /// t','/*a*//*b*/']
import cv; cvalid=cv.make(H)
def valid(t):
    if re.search(r'(^|\n)[ \t\f\v\r]*#',t): return False
    sp=H._csharp_lex(t)[0]
    return all(not (k in("block","doc") and c is None and '/*' in t) or True for k,a,b,_,c in sp)
def unterminated(t):
    for k,a,b,content,cc in M._csharp_comment_spans(t):
        if k in("block","doc") and cc is None and True:
            pass
    return None
rng=random.Random(77); diffs=collections.Counter(); ex={}; tot=0
for _ in range(int(sys.argv[2])):
    lines=[" ".join(rng.choice(F) for _ in range(rng.randint(1,3))) for _ in range(rng.randint(1,5))]
    t=rng.choice(["\n","\r\n"]).join(lines)+"\n"
    if re.search(r'(^|\n)[ \t\f\v\r]*#',t): continue
    ms=M._csharp_comment_spans(t)
    if any(k in("block","doc") and cc is None and not c_ends(t) for k,a,b,c,cc in []): pass
    tot+=1
    hs=H._csharp_comment_spans(t)
    if ms!=hs:
        unterm = not cvalid(t)
        key="unterminated_in_main" if unterm else "OTHER"
        diffs[key]+=1
        if key not in ex or len(t)<len(ex[key][0]): ex[key]=(t,ms,hs)
    mb=M._findings_for_file("/r/Tests/T.cs",t); hb=H._findings_for_file("/r/Tests/T.cs",t)
    if mb!=hb and cvalid(t):
        diffs["findings_OTHER"]+=1
        if "findings_OTHER" not in ex or len(t)<len(ex["findings_OTHER"][0]): ex["findings_OTHER"]=(t,mb,hb)
print("cases",tot,dict(diffs))
for k,v in ex.items(): print(k,repr(v[0]),"\n  main",v[1],"\n  head",v[2])

import sys, re, itertools, importlib.util, collections
def load(n):
    s=importlib.util.spec_from_file_location(n,n+".py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
BASES=[
 ["/// doc","[Theory]",'[InlineData("a", 2)]',"public void X(string a, int b)","{","}"],
 ["[Theory]",'[MemberData(nameof(Cases), MemberType = typeof(D))]',"/// doc","public void X(int a)","{","}"],
 ["/// doc","[Fact(Skip = \"x\")]","public void X()","{","}"],
 ["[Fact, Trait(\"k\", \"v\")]","/// doc","public void X()","{","}"],
]
def run(m,t):
    return sorted((v[0].split("'")[1], v[1][0]) for v in m.find_csharp_blocking_violations(t,"/r/T.cs") if v[0].startswith("BLOCKED - '"))
PAIRS=[("// a","// b"),("/* a */","// b"),("","/* a */"),("// a",""),("/* a */","/* b */")]
for name in sys.argv[1:]:
    m=load(name); n=0; bad=collections.Counter(); ex={}
    for bi,base in enumerate(BASES):
        want=run(m,"\n".join(base)+"\n"); wn=[w[0] for w in want]
        # newline invariance inside attribute lines: break after ',' or '('
        for li,line in enumerate(base):
            if not line.startswith("["): continue
            for mt in re.finditer(r"[(,]",line):
                k=mt.end(); lines=base[:li]+[line[:k],"    "+line[k:].lstrip()]+base[li+1:]
                got=run(m,"\n".join(lines)+"\n"); n+=1
                if [g[0] for g in got]!=wn: bad[("newline",bi)]+=1; ex.setdefault(("newline",bi),("\n".join(lines),got,want))
        for gap in range(1,len(base)):
            for a,b in PAIRS:
                lines=base[:gap]+[x for x in (a,b)]+base[gap:]
                got=run(m,"\n".join(lines)+"\n"); n+=1
                if [g[0] for g in got]!=wn: bad[("pair",bi)]+=1; ex.setdefault(("pair",bi),("\n".join(lines),got,want))
        for li,line in enumerate(base):
            if line.startswith("["):
                lines=base[:li]+["#if NET8_0",line,"#endif"]+base[li+1:]
                got=run(m,"\n".join(lines)+"\n"); n+=1
                if [g[0] for g in got]!=wn: bad[("pp",bi)]+=1; ex.setdefault(("pp",bi),("\n".join(lines),got,want))
    print(name,"cases",n,"violations",sum(bad.values()),dict(bad))
    for k,(t,g,w) in list(ex.items())[:5]: print("   ",k,repr(t),"got",g,"want",w)

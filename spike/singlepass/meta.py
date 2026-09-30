import sys, time, random, itertools, importlib.util, collections
def load(n):
    s=importlib.util.spec_from_file_location(n,n+".py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
BASES=[
 ["/// <summary>doc</summary>","[Fact]","public void X()","{","}"],
 ["[Fact]","/// doc","public void X()","{","}"],
 ["/// doc","[Theory]",'[InlineData("a")]',"public void X(string a)","{","}"],
 ["[Theory]","/// doc",'[InlineData(1)]',"public void X(int a)","{","}"],
 ["/** doc */","[Test]","public async Task X()","{","}"],
 ["/// doc","[Fact]","public void X() => Assert.True(true);"],
 ["[Fact]","public void A()","{","}","/// doc","private static int H() => 1;"],
 ["/// doc","public void Helper()","{","}","[Fact]","public void X()","{","}"],
]
TRIVIA=["","// note","/* note */","/* multi","   line */","//// banner"]
def run(m,t): return sorted(v[1][0] for v in m.find_csharp_blocking_violations(t,"/r/T.cs"))
for name in sys.argv[1:]:
    m=load(name); t0=time.time(); n=0; bad=collections.Counter(); ex={}
    for bi,base in enumerate(BASES):
        want=run(m,"\n".join(base)+"\n")
        for gap in range(1,len(base)):
            for triv in [[x] for x in TRIVIA if x not in ("/* multi","   line */")]+[["/* multi","   line */"],["// a","/* b */"]]:
                lines=base[:gap]+triv+base[gap:]
                got=run(m,"\n".join(lines)+"\n"); n+=1
                shifted=[r+len(triv) if r>gap else r for r in want]
                if got!=shifted:
                    bad[bi]+=1; ex.setdefault(bi,"\n".join(lines))
            for pre in ["/* c */ ","/* a */ /* b */ "]:
                lines=base[:gap]+[pre+base[gap]]+base[gap+1:]
                got=run(m,"\n".join(lines)+"\n"); n+=1
                if got!=want: bad[("pre",bi)]+=1; ex.setdefault(("pre",bi),"\n".join(lines))
    print(name,"cases",n,"violations",sum(bad.values()),f"{time.time()-t0:.2f}s")
    for k in list(ex)[:6]: print("   ",k,repr(ex[k]))

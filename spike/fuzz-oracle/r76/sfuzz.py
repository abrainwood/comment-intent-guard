import random, collections
exec(open("tfuzz.py").read().split("T=[")[0])
A=["Fact","Foo","Theory","Foo<int>","Foo<Fact>","Foo<int, Fact>","Foo<Bar<int,Fact>>","Foo(1 < 2)","Foo(1 > 2)","Foo(1 << 2)","Foo(a <= b)","Foo(\"<\")","Foo('<')","Foo(typeof(List<int>))","Xunit.Fact","method: Fact","Foo(", "Foo<","Foo(new int[] {1})","SkippableFact","UIFact","Artifact"]
S=["public void X()","public (int, int) X()","public (int a, (int, int) b) X()","public Task<(int,int)> X()","public void X((int,int) p)","public static (int,int) X<T>()","public (int,int)[] X()","public void X() {(var a, var b) = G();}","public void X(","public (int, int) X","public void X<T>() where T : struct"]
rng=random.Random(7); cnt=collections.Counter(); ex=collections.defaultdict(list)
for i in range(200000):
    attrs=", ".join(rng.choice(A) for _ in range(rng.randint(1,3)))
    t=f"/// d\n[{attrs}]\n{rng.choice(S)}\n{{\n}}\n" if rng.random()<.9 else f"/// d\n[{attrs}]\n{rng.choice(S)}"
    h=run(H,t); m=run(M,t)
    k="HANG" if h=="HANG" else "EXC" if isinstance(h,str) else "same" if h==m else "diff"
    cnt[k]+=1
    if k!="same" and len(ex[k])<0 or (k!="same" and t not in [e[0] for e in ex[k]] and len(ex[k])<400): ex[k].append((t,[x.split("'")[1] for x in h] if isinstance(h,list) else h,[x.split("'")[1] for x in m] if isinstance(m,list) else m))
print(cnt)
# group diffs by (main,head) result and attr triggering
g=collections.Counter()
for t,h,m in ex["diff"]:
    sig=t.split("\n")[2]; attr=t.split("\n")[1]
    g[(str(m),str(h), "angle-in-args" if any(s in attr for s in ["(1 <","<<","<=","(\"<","('<"]) else "generic-arg" if "<" in attr.split("(")[0] else "vocab" if not any(x in attr for x in ["Fact,","Fact]","Theory"]) or "Skippable" in attr or "UIFact" in attr else "sig")]+=1
for k,v in sorted(g.items(), key=lambda x:-x[1]): print(v,k)
for k in ("HANG","EXC"): print(k, ex[k][:3])
for t,h,m in ex["diff"]:
    a=t.split("\n")[1]
    if m==['X'] and h==[] and not any(s in a for s in ["<"]): print(repr(t))

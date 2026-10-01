import random, signal, time, collections, guard_head as H, guard_main as M
class Hang(Exception): pass
signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(Hang()))
P="/repo/Tests/T.cs"
def run(m,t):
    signal.setitimer(signal.ITIMER_REAL,0.5)
    try: return sorted(v[0] for v in m.find_csharp_blocking_violations(t,P))
    except Hang: return "HANG"
    except Exception as e: return "EXC "+type(e).__name__
    finally: signal.setitimer(signal.ITIMER_REAL,0)
T=["<",">","<<",">>","<=",">=","(",")","[","]","{","}",",","Fact","Foo","int","X","public","void","Task","=","=>",";","\"<\"","\">\"","'<'","1","a","(int, int)","static","where","T",":","/** d */","/// d\n","?","*","@Fact"]
rng=random.Random(76); cnt=collections.Counter(); ex={}
for i in range(300000):
    t=" ".join(rng.choice(T) for _ in range(rng.randint(1,14)))
    if rng.random()<0.5: t="/// d\n"+t
    h=run(H,t); m=run(M,t)
    k=("HANG" if h=="HANG" else "EXC" if isinstance(h,str) and h.startswith("EXC") else "same" if h==m else "diff")
    cnt[k]+=1
    if k!="same" and (k not in ex or len(t)<len(ex[k])): ex[k]=(t,h,m)
print(cnt); [print(k,repr(v)) for k,v in ex.items()]
body="".join(f"/// <summary>m{i}</summary>\n[Fact, Trait(\"k\", \"v\")]\npublic (int, int) M{i}((int, int) p)\n{{\n    var x = new List<int>();\n}}\n\n" for i in range(1500))
for m in (M,H,M,H):
    t0=time.perf_counter(); n=len(m.find_csharp_blocking_violations(body,P)); print(m.__name__, n, f"{(time.perf_counter()-t0)*1000:.0f} ms")
body2="".join(f"/// <summary>m{i}</summary>\n[Fact]\npublic void M{i}()\n{{\n}}\n\n" for i in range(1500))
for m in (M,H,M,H):
    t0=time.perf_counter(); n=len(m.find_csharp_blocking_violations(body2,P)); print("plain",m.__name__, n, f"{(time.perf_counter()-t0)*1000:.0f} ms")

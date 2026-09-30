import sys, collections
sys.argv=[sys.argv[0],sys.argv[1],'roslyn','0','guard_head','guard_main']+sys.argv[2:]
src=open('fuzz8.py').read().split("cnt=collections.Counter()")[0]
exec(src)
reg=[]; fnh=[]; fph=[]
for body in cases():
    t="\n".join(body+["public void X()","{","}"])+"\n"
    if not valid(t): continue
    e=expected(t)
    if e is None: continue
    h=run(mods['guard_head'],t); m=run(mods['guard_main'],t)
    if h!=e and m==e: reg.append((len(t),t,h,e))
    elif h!=e: (fph if len(h)>len(e) else fnh).append((len(t),t,h,e))
for name,l in (("REGRESSIONS",reg),("HEAD FP",fph),("HEAD FN",fnh)):
    l.sort(); print("=====",name,len(l))
    seen=set()
    for _,t,h,e in l:
        key=t.split("\n")[:-4]
        print(repr(t), "head",h,"exp",e)
        if len(seen)>25: break
        seen.add(t)

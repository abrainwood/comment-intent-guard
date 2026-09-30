import sys,collections
sys.argv=[sys.argv[0],sys.argv[1],'roslyn','60000','guard_head','guard_main']
exec(open('fuzz9.py').read().split("cnt=collections.Counter()")[0])
import re
def sig(t):
    if re.search(r"\*/ (//|/\*)",t): return "doc-close then comment"
    return "other"
c=collections.Counter(); ex={}
for body in cases():
    t="\n".join(body+["public void X()","{","}"])+"\n"
    if not valid(t): continue
    e=expected(t)
    if e is None: continue
    h=run(mods['guard_head'],t); m=run(mods['guard_main'],t)
    if h!=e and m==e:
        k=sig(t); c[k]+=1
        if k=="other" and (k not in ex or len(t)<len(ex[k][0])) : ex[k]=(t,h,e)
        if k=="other" and c[k]<=15: print(repr(t),h,e)
print(c, ex)

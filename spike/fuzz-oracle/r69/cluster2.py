import sys,collections,re
sys.argv=[sys.argv[0],sys.argv[1],'roslyn','60000','guard_head','guard_main']
exec(open('fuzz9.py').read().split("cnt=collections.Counter()")[0])
c=collections.Counter(); ex={}
for body in cases():
    t="\n".join(body+["public void X()","{","}"])+"\n"
    if not valid(t): continue
    e=expected(t)
    if e is None: continue
    h=run(mods['guard_head'],t); m=run(mods['guard_main'],t)
    if h!=e and m==e:
        k = "doc*/ then ///" if re.search(r"\*/ ///",t) and not re.search(r"\*/ (//[^/]|/\*|// )",t) else "doc*/ then //c or /*" if re.search(r"\*/ (//|/\*)",t) else "other"
        c[k]+=1
        if k not in ex or len(t)<len(ex[k]): ex[k]=t
print(c); [print(k,repr(v)) for k,v in ex.items()]

import sys,collections,re
fz=sys.argv[2]; N=sys.argv[3]
sys.argv=[sys.argv[0],sys.argv[1],'roslyn',N,'guard_head','guard_main','guard_r1']
exec(open(fz).read().split("cnt=collections.Counter()")[0])
def shape(t,kind):
    if kind=="FN":
        if re.search(r"\] */\*\*[^*/]",t): return "71a attr+javadoc same line"
        if re.search(r"\] *///(?!/)[^\n]*\n[ \t]*///(?!/)",t): return "71b attr+/// multi-line"
        if re.search(r"\*/ *\[[^\n]*\n(\s*\n)*[ \t]*///(?!/)",t): return "71c */ [attr] then ///"
    else:
        if re.search(r"/\*\*[^*/][^\n]*\n",t) and not re.search(r"/\*\*[^*/][^\n]*\*/[^\n]*\n",t.split("\n")[0]+"\n") : pass
        # attr inside open javadoc
        if re.search(r"/\*\*[^*/](?:(?!\*/).)*\n(?:(?!\*/).)*\[",t,re.S): return "70b attr inside open javadoc"
        if re.search(r"(///(?!/)[^\n]*|\*/)[^\n]*\n",t) and re.search(r"/\*\* d \*/ int y;",t): return "70a doc then code same line"
    return "OTHER"
miss=collections.Counter(); ex={}; reg=collections.Counter(); rex={}; r1reg=[]
for body in cases():
    t="\n".join(body+["public void X()","{","}"])+"\n"
    if not valid(t): continue
    e=expected(t)
    if e is None: continue
    h=run(mods['guard_head'],t)
    if h==e: continue
    kind="FP" if len(h)>len(e) else "FN" if len(h)<len(e) else "ROW"
    s=shape(t,kind); miss[(kind,s)]+=1
    if (kind,s) not in ex or len(t)<len(ex[(kind,s)]): ex[(kind,s)]=t
    m=run(mods['guard_main'],t); r=run(mods['guard_r1'],t)
    if m==e:
        reg[(kind,s)]+=1
        if (kind,s) not in rex or len(t)<len(rex[(kind,s)]): rex[(kind,s)]=t
    if r==e: r1reg.append(t)
print("HEAD misses", sum(miss.values()))
for k,v in sorted(miss.items()): print(" ",k,v,repr(ex[k])[:160])
print("main-right/HEAD-wrong", sum(reg.values()))
for k,v in sorted(reg.items()): print(" ",k,v,repr(rex[k])[:220])
print("r1-right/HEAD-wrong",len(r1reg))
for t in sorted(r1reg,key=len)[:5]: print("  ",repr(t))

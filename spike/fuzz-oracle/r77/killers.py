import importlib.util,sys,os
sys.argv=[None,"."]; exec(open("lexmut.py").read().split("sel=")[0])
os.makedirs("km",exist_ok=True)
def load(n,src):
    p=f"km/{n}.py"; open(p,"w").write(src); s=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
H=load("kh",orig); Mn=load("kmain",open("main/comment_intent_guard.py").read())
K={
"L01 # anywhere":"x = #1; // fixed on 2026-01-05\n",
"L02 line_start never cleared":"x = #1; // fixed on 2026-01-05\n",
"L07 literal no token":'/// d\n[Trait("a", "b")]\n[Fact]\npublic void X()\n{\n}\n',
"L08 literal not code":'/// a\n"x" /// b\n',
"L12 multiline block keeps line_has_code":"/// a\n/* x\n */ /// b\n",
"L13 ident not code":"/// a\nx /// b\n",
"L14 punct not code":"/// a\n} /// b\n",
"L18 always leading":"/// a\nint y; /// b\n",
"L20 unterminated spans lines":"/* a\nb\n",
"L25 ident stops at digit":"/// d\n[Fact]\npublic void Method1()\n{\n}\n",
"L27 merge allows non-leading":"/// a\nint y; /// b\n",
}
for name,t in K.items():
    a,b=M[name]; m=load("k"+name.split()[0],orig.replace(a,b))
    f=lambda g:(g._csharp_comment_spans(t), g._findings_for_file("/r/Tests/T.cs",t))
    h,mm,mn=f(H),f(m),f(Mn)
    print(("KILLS " if h!=mm else "no-diff ")+name, "| main==head" if mn==h else "| MAIN DIFFERS", repr(t))
    if h!=mm: print("   head",h[0],[x[1] for x in h[1][0]],"\n   mut ",mm[0],[x[1] for x in mm[1][0]])

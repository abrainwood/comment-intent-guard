import sys,importlib.util
sys.path.insert(0,sys.argv[1]); from mutants import M
S=sys.argv[1]; orig=open(f"{S}/head/comment_intent_guard.py").read()
def load(name,src):
    p=f"{S}/kmods/{name}.py"; open(p,"w").write(src)
    s=importlib.util.spec_from_file_location(name,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
import os; os.makedirs(f"{S}/kmods",exist_ok=True)
head=load("khead",orig)
K={
 "M05 literal rows not counted": 'const string S = @"a\nb";\n/// d\n[Fact]\npublic void X()\n{\n}\n',
 "M09 /**/ is doc": "[Fact]\n/**/\npublic void X()\n{\n}\n",
 "M16 any [ opens section": "void M()\n{\n    var v = map /// d\n        [Fact].Get(1);\n}\n",
 "M34 before not opener-checked": "public int this[Fact f] /// d\n    => Get(f);\n",
 "M19 names any depth": "/// d\n[InlineData(1, Fact)]\npublic void Helper()\n{\n}\n",
 "M20 parens not depth-tracked": "/// d\n[InlineData(1, Fact)]\npublic void Helper()\n{\n}\n",
 "M23 stop drop =": "/// d\n[Fact]\npublic Func<int> F = Make();\n",
 "M24 stop drop =>": "/// d\n[Fact]\npublic int P => Compute();\n",
 "M26 stop drop {": "/// d\n[Fact]\npublic int P { get { return Compute(); } }\n",
 "M37 \\r not whitespace": '/// d\r\n[Trait("a", "b")]\r\n[Fact]\r\npublic void X()\r\n{\r\n}\r\n',
 "M39 name any first char": "/// d\n[Fact]\npublic void _X()\n{\n}\n",
 "M41 @ not ident start": "/// d\n[Fact]\npublic void @X()\n{\n}\n",
 "M06 literal emits no token": None, "M01 # anywhere is preprocessor": None, "M02 line_start never cleared": None,
 "M15 boundary add )": "public void A() /// t\n[Fact]\npublic void X()\n{\n}\n",
 "M27 stop drop }": None, "M31 => width 1": None, "M42 name excludes _": "/// d\n[_Fact]\npublic void X()\n{\n}\n",
}
f=lambda m,t:[(v[1],v[0].split("'")[1] if "'" in v[0] else v[0][:40]) for v in m.find_csharp_blocking_violations(t,"/r/T.cs")]
for name,t in K.items():
    if t is None: print(name,"-> no valid-C# kill input found (equivalent)"); continue
    a,b=M[name]; mut=load("km"+name.split()[0],orig.replace(a,b))
    h,mm=f(head,t),f(mut,t)
    print(("KILLS " if h!=mm else "no-diff ")+name,"| head",h,"| mutant",mm)

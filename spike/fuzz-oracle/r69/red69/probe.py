import sys, importlib.util
cases = {
 "field_trait": '[Fact]\n/// doc\n/* a */ int q; /* b */ [Fact, Trait("k", "/* */")]\npublic void X()\n{\n}\n',
 "trait_sameline_method": '/// doc\n[Fact, Trait("k", "v")] public void X()\n{\n}\n',
 "doc_close_then_trait_attr_method": '/** d\n*/ [Fact, Trait("k", "v")] public void X()\n{\n}\n',
 "doc_close_then_trait_attr_nextline": '/** d\n*/ [Fact, Trait("k", "v")]\npublic void X()\n{\n}\n',
 "fact_doc_trait_attr_method_sameline": '[Fact]\n/// doc\n[Trait("k", "v")] public void X()\n{\n}\n',
 "trait_only_attr_notest": '/// doc\n[Trait("k", "v")]\npublic void X()\n{\n}\n',
 "attr_doc_sameline_trait": '[Fact, Trait("k","v")] /// x\npublic void X()\n{\n}\n',
 "fact_doc_code_then_method": '[Fact]\n/// doc\nint q; public void X()\n{\n}\n',
}
for d in sys.argv[1:]:
    spec = importlib.util.spec_from_file_location("g"+d.replace("/","_"), d+"/comment_intent_guard.py"); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    print("==", d.rsplit("/",1)[-1])
    for k,t in cases.items():
        v = g.find_csharp_blocking_violations(t, "/repo/Tests/ThingTests.cs")
        print(f"  {k:40} {[ (x[0][9:30], x[1]) for x in v]}")

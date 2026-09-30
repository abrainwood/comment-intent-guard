import sys, importlib.util
cases = {
 "field_trait_then_method_sameline": '[Fact]\n/// doc\n/* a */ int q; /* b */ [Fact, Trait("k", "/* */")] public void X()\n{\n}\n',
 "doc_close_field_trait": '/** d */ [Fact] int q; [Fact, Trait("k", "v")]\npublic void X()\n{\n}\n',
 "doc_close_ml_field_trait": '/** d\n*/ [Fact] int q; [Fact, Trait("k", "v")]\npublic void X()\n{\n}\n',
 "doc_close_attr_trait_method": '/** d */ [Fact] [Trait("k", "v")] void X()\n{\n}\n',
 "doc_close_attr_trait_in_rest": '/** d\n*/ [Fact] static [Trait("k","v")] void X()\n{\n}\n',
 "doc_then_attr_code_trait": '/// doc\n[Fact] int q; [Fact, Trait("k", "v")]\npublic void X()\n{\n}\n',
}
for d in sys.argv[1:]:
    spec = importlib.util.spec_from_file_location("g"+d.replace("/","_"), d+"/comment_intent_guard.py"); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    print("==", d.rsplit("/",1)[-1])
    for k,t in cases.items():
        v = g.find_csharp_blocking_violations(t, "/repo/Tests/ThingTests.cs")
        print(f"  {k:36} {[ (x[0][9:30], x[1]) for x in v]}")

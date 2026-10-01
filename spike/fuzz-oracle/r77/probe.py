import importlib.util,sys
def load(d):
    spec=importlib.util.spec_from_file_location("g_"+d,f"{sys.argv[1]}/{d}/comment_intent_guard.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
M,H=load("main"),load("head")
cases={
 "region_block_then_id": "#region a /* b\n// TODO ABC-123 fix\nclass C{}\n",
 "endif_trailing_id": "#if DEBUG\nint x;\n#endif // JIRA-456 remove\n",
 "if_trailing_date": "#if DEBUG // fixed on 2026-01-05\n#endif\n",
 "hash_in_string": 'var s = "#x /* y"; // ABC-789\n',
 "hash_nonstart": "x = #1 /* q\n// ABC-111\n",
 "unterminated_eof": "/* open\n// ABC-222 later\nint y;\n",
 "indented_hash": "  #pragma warning disable /* z\n// ABC-333\n",
 "verbatim_hash": 'var s = @"\n#region /* \n"; // ABC-444\n',
 "ff_before_doc": "\f/// <summary>x</summary>\n[Fact]\npublic void T(){}\n",
 "doc_after_ifdirective": "#if X\n/// <summary>Doc</summary>\n[Fact]\npublic void T(){}\n#endif\n",
}
for k,t in cases.items():
    for name,g in (("main",M),("head",H)):
        b,a=g._findings_for_file("/repo/Tests/ThingTests.cs",t)
        print(f"{k:24}{name}: spans={g._csharp_comment_spans(t)}\n{'':30}blocking={b} adv={[x[1] for x in a]}")

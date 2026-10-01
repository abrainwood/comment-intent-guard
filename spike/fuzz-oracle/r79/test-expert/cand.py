import importlib.util,pathlib
def load(p,n):
    spec=importlib.util.spec_from_file_location(n,p); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g); return g
head=load('../../../comment_intent_guard.py','head')
C={
 'S_no_open_escape':'x = $"{{ "; // c\n',
 'R_open_needs_more_braces':'x = $$"""{{ """a""" }}"""; // c\n',
 'RH_code_brace_no_depth_inc':'x = $$"""{{ new { a = 1 }.A + """b""" }}"""; // c\n',
 'H_only_nested_verbatim_flip':'x = $"{ $@"a\\" } // c\n',
 'S_hole_verbatim_forced_false':'x = $@"{\n a } // not\n"; // c\n',
 'H_no_eol_stop':'x = $"{ a\n// c\n',
 'S_no_eol_stop':'x = $"a\n// c\n',
 'H_eol_stop_even_verbatim':'x = $@"{ a\n } // not\n"; // c\n',
 'S_no_backslash_escape':'x = $"a\\" // not"; // c\n',
 'CLS_atdollar_order_none':'x = @$"{a} // not"; // c\n',
}
for m,t in C.items():
    mut=load(f'mut2/{m}/comment_intent_guard.py',m)
    a=list(head._csharp_comment_spans(t)); b=list(mut._csharp_comment_spans(t))
    print(f'{m:30s} {"KILLS" if a!=b else "same "} head={a} mut={b}')

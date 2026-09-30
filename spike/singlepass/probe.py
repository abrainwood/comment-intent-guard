import importlib.util, sys
s=importlib.util.spec_from_file_location("g", sys.argv[1]); g=importlib.util.module_from_spec(s); s.loader.exec_module(g)
P="/repo/Tests/ThingTests.cs"
def v(t): return [r[1][0] for r in g.find_csharp_blocking_violations(t,P) if "XML doc comment" in r[0] and "test" in r[0].lower()]
W=lambda body: "namespace N;\n\npublic class ThingTests\n{\n" + "".join("    "+l+"\n" if l else "\n" for l in body.split("\n")) + "}\n"
cases = {
 # name: (text, expected rows)
 "baseline_indented": (W("/// <summary>doc</summary>\n[Fact]\npublic void X()\n{\n}"), [7]),
 "crlf_baseline": (W("/// <summary>doc</summary>\n[Fact]\npublic void X()\n{\n}").replace("\n","\r\n"), [7]),
 "crlf_attr_above_doc": (W("[Fact]\n/// doc\npublic void X()\n{\n}").replace("\n","\r\n"), [7]),
 "multiline_inlinedata_args": (W('/// doc\n[Theory]\n[InlineData(\n    "a",\n    "b")]\npublic void X(string a, string b)\n{\n}'), [10]),
 "multiline_attribute_list": (W('/// doc\n[Theory,\n InlineData(1)]\npublic void X(int a)\n{\n}'), [8]),
 "attr_above_doc_multiline_args": (W('[Theory]\n[InlineData(\n    1)]\n/// doc\npublic void X(int a)\n{\n}'), [9]),
 "nested_brackets_in_attr_arg": (W('/// doc\n[Theory]\n[InlineData(new int[] { 1 })]\npublic void X(int[] a)\n{\n}'), [8]),
 "nested_brackets_backward": (W('[Theory]\n[InlineData(new int[] { 1 })]\n/// doc\npublic void X(int[] a)\n{\n}'), [8]),
 "if_endif_around_attr": (W('/// doc\n#if NET8_0_OR_GREATER\n[Fact]\n#endif\npublic void X()\n{\n}'), [9]),
 "pragma_between": (W('/// doc\n[Fact]\n#pragma warning disable CS0618\npublic void X()\n{\n}'), [8]),
 "region_above_attr_doc_above": (W('/// doc\n#region Slow\n[Fact]\npublic void X()\n{\n}'), [8]),
 "generic_attr": (W('/// doc\n[Theory]\n[ClassData<MyData>]\npublic void X(int a)\n{\n}'), [8]),
 "async_task": (W('/// doc\n[Fact]\npublic async Task<int> X()\n{\n}'), [7]),
 "expr_bodied": (W('/// doc\n[Fact]\npublic void X() => Assert.True(Foo());'), [7]),
 "signature_split_lines": (W('/// doc\n[Fact]\npublic void\nX()\n{\n}'), [8]),
 "datatestmethod_mstest": (W('/// doc\n[DataTestMethod]\n[DataRow(1)]\npublic void X(int a)\n{\n}'), [8]),
 "custom_fact_subclass": (W('/// doc\n[SkippableFact]\npublic void X()\n{\n}'), [7]),
 "testcasesource_nunit": (W('/// doc\n[TestCaseSource(nameof(Cases))]\npublic void X(int a)\n{\n}'), [7]),
 "raw_string_embedded_source": (W('[Fact]\npublic void Outer()\n{\n    var src = """\n        /// doc\n        [Fact]\n        public void Inner() {}\n        """;\n}'), []),
 "verbatim_embedded_source": (W('[Fact]\npublic void Outer()\n{\n    var src = @"\n/// doc\n[Fact]\npublic void Inner() {}\n";\n}'), []),
 "doc_on_nontest_then_test": (W('/// doc\npublic void Helper()\n{\n}\n\n[Fact]\npublic void X()\n{\n}'), []),
 "attr_arg_string_with_bracket": (W('/// doc\n[Theory]\n[InlineData("]")]\npublic void X(string a)\n{\n}'), [8]),
 "doc_then_attr_with_trailing_comment_and_url": (W('/// doc\n[Fact] // see http://x\npublic void X()\n{\n}'), [7]),
 "doc_on_class_then_first_test": (W('[Fact]\npublic void A()\n{\n}\n/// doc for helper\nprivate static int H() => 1;'), []),
 "attr_on_prop_above_doc_nontest": (W('[Fact]\npublic void A() { }\n/// doc\npublic int P { get; }'), []),
 "local_function_in_test": (W('[Fact]\npublic void A()\n{\n    /// doc\n    void Local() { }\n}'), []),
 "attribute_target_specifier": (W('/// doc\n[method: Fact]\npublic void X()\n{\n}'), [7]),
 "fqn_attr": (W('/// doc\n[Xunit.Fact]\npublic void X()\n{\n}'), [7]),
 "fact_with_named_arg_multiline": (W('/// doc\n[Fact(\n    Skip = "flaky")]\npublic void X()\n{\n}'), [8]),
 "tab_indent": (("namespace N;\npublic class T\n{\n\t/// doc\n\t[Fact]\n\tpublic void X()\n\t{\n\t}\n}\n"), [6]),
 "bom_crlf": ("﻿" + W("/// doc\n[Fact]\npublic void X()\n{\n}").replace("\n","\r\n"), [7]),
 "javadoc_style": (W('/** doc */\n[Fact]\npublic void X()\n{\n}'), [7]),
 "doc_attr_same_line_after": (W('[Fact] /// doc\npublic void X()\n{\n}'), [6]),
 "doc_between_two_attrs": (W('[Theory]\n/// doc\n[InlineData(1)]\npublic void X(int a)\n{\n}'), [8]),
 "comment_line_with_brackets_between": (W('[Fact]\n// [Obsolete]\n/// doc\npublic void X()\n{\n}'), [8]),
 "attr_after_blank_line_backward": (W('[Fact]\n\n/// doc\npublic void X()\n{\n}'), [8]),
 "prev_method_trailing_attr_like_indexer": (W('public int this[int i] => i;\n/// doc\npublic void X()\n{\n}'), []),
 "array_expression_line_above_doc": (W('private static readonly int[] Xs = new[] { 1 };\n[Fact]\npublic void A() { }\n\nint[] ys = { };\n/// doc\npublic void X() { }'), []),
 "collection_expression_line_above": (W('[Fact]\npublic void A()\n{\n    int[] a =\n    [1, 2];\n    /// doc\n    void L() { }\n}'), []),
 "list_pattern_statement": (W('[Fact]\npublic void A()\n{\n    if (x is\n    [1, 2])\n    /// doc\n    Foo();\n}'), []),
}
bad=0
for k,(t,e) in cases.items():
    try: r=v(t)
    except Exception as ex: r=f"EXC {ex!r}"
    ok = r==e
    bad += not ok
    print(("ok  " if ok else "BAD ")+f"{k:45} got={r} want={e}")
print("bad",bad,"of",len(cases))

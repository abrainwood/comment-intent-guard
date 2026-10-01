import subprocess,sys,pathlib,shutil,re
ROOT=pathlib.Path('../../..').resolve(); SRC=(ROOT/'comment_intent_guard.py').read_text()
hseg_start=SRC.index('if kind == "H":'); rseg=SRC.index('if kind == "R":')
call='                i = _csharp_push_literal(opened, stack)\n'
def nested_only(extra):
    seg=SRC[hseg_start:rseg]; assert seg.count(call)==1
    return SRC[:hseg_start]+seg.replace(call,call+extra)+SRC[rseg:]
NEW={'H_only_nested_verbatim_flip':nested_only('                if opened[0] == "S":\n                    stack[-1][1] = not stack[-1][1]\n'),
     'H_only_nested_R_dollar_1':nested_only('                if opened[0] == "R":\n                    stack[-1][2] = 1\n')}
for k,v in NEW.items():
    w=pathlib.Path('mut2')/k
    if w.exists(): shutil.rmtree(w)
    shutil.copytree(ROOT,w,ignore=shutil.ignore_patterns('spike','.git','__pycache__','.pytest_cache')); (w/'comment_intent_guard.py').write_text(v)
TESTS=['test_a_hole_with_one_level_of_nested_braces_requires_both_closes_to_end_the_hole',
'test_a_hole_with_two_levels_of_nested_braces_requires_all_three_closes_to_end_the_hole',
'test_doubled_quote_in_a_verbatim_interpolated_string_is_a_literal_quote_not_the_closer',
'test_a_verbatim_interpolated_string_nested_in_a_hole_keeps_its_own_verbatim_flag',
'test_a_raw_interpolated_string_nested_in_a_hole_keeps_its_own_dollar_count']
src=(ROOT/'tests/test_csharp_analyser.py').read_text()
raw=[m for m in re.findall(r'def (test_\w+)\(',src) if 'raw' in m and ('hole' in m or 'brace' in m)]
TESTS+= [t for t in raw if t not in TESTS]
sel=['tests/test_csharp_analyser.py::'+t for t in TESTS]
dirs=sorted(pathlib.Path('mut2').iterdir())
for i,t in enumerate(TESTS): print(f'T{i}',t)
print(f'{"mutant":30s}',' '.join(f'T{i}' for i in range(len(TESTS))))
for d in dirs:
    r=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider','-rf',*sel],cwd=d,capture_output=True,text=True)
    failed={l.split('::')[1].split(' ')[0] for l in r.stdout.splitlines() if l.startswith('FAILED')}
    print(f'{d.name:30s}',' '.join(f'{"X" if t in failed else ".":>2s}' for t in TESTS))

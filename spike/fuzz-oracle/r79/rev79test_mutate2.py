import re,shutil,subprocess,sys,pathlib
ROOT=pathlib.Path('../../..').resolve(); SRC=(ROOT/'comment_intent_guard.py').read_text()
start=SRC.index('def _csharp_push_literal'); end=SRC.index('def _csharp_try_skip_literal(text, i):')
body=SRC[start:end]
pstart=body.index('def _csharp_skip_interpolation_stack'); hstart=body.index('if kind == "H":'); rstart=body.index('if kind == "R":'); rhstart=body.index('if kind == "RH":')
sec={'P':(0,pstart),'S':(pstart,hstart),'H':(hstart,rstart),'R':(rstart,rhstart),'RH':(rhstart,len(body))}
M=[
 ('H_code_brace_no_depth_inc','H','frame[2] += 1','frame[2] += 0'),
 ('RH_code_brace_no_depth_inc','RH','frame[1] += 1','frame[1] += 0'),
 ('H_close_ignores_depth','H','if frame[2] == 0:','if True:'),
 ('H_no_eol_stop','H','if not verbatim and text[i] == "\\n":','if False:'),
 ('S_no_eol_stop','S','if not verbatim and ch == "\\n":','if False:'),
 ('H_eol_stop_even_verbatim','H','if not verbatim and text[i] == "\\n":','if text[i] == "\\n":'),
 ('S_no_open_escape','S','if ch == "{" and i + 1 < n and text[i + 1] == "{":','if False:'),
 ('S_no_close_escape','S','if ch == "}" and i + 1 < n and text[i + 1] == "}":','if False:'),
 ('S_no_backslash_escape','S','if not verbatim and ch == "\\\\" and i + 1 < n:','if False:'),
 ('S_no_doubled_quote','S','if verbatim and i + 1 < n and text[i + 1] == \'"\':','if False:'),
 ('S_hole_verbatim_forced_false','S','stack.append(["H", verbatim, 1])','stack.append(["H", False, 1])'),
 ('R_open_needs_more_braces','R','if brace_run >= dollar_run:','if brace_run > dollar_run:'),
 ('R_close_run_gt','R','if close_run >= quote_run:','if close_run > quote_run:'),
 ('RH_close_run_le','RH','while close_run < brace_count','while close_run <= brace_count'),
 ('RH_close_single','RH','i += close_run\n                    stack.pop()','i += 1\n                    stack.pop()'),
 ('P_nested_S_verbatim_flip','P','stack.append(["S", opened[1]])','stack.append(["S", not opened[1]])'),
 ('P_plain_ignored','P','return opened[1]\n    if opened[0] == "S"','return opened[1] - 1\n    if opened[0] == "S"'),
 ('P_R_wrong_dollar','P','stack.append(["R", opened[1], opened[2]])','stack.append(["R", opened[1], 1])'),
]
CLS=[('CLS_atdollar_order_none',"""    if ch == "@" and i + 2 < n and text[i + 1] == "$" and text[i + 2] == '"':
        return ("S", True, i + 3)""","""    if ch == "@" and i + 2 < n and text[i + 1] == "$" and text[i + 2] == '"':
        return None""")]
DIFF='tests/test_csharp_analyser.py::test_iterative_csharp_lexer_matches_the_old_recursive_lexer_over_a_seeded_interpolation_corpus'
def run(work,sel):
    r=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider','-x','-n','8',*sel],cwd=work,capture_output=True,text=True)
    return 'KILLED' if r.returncode in (1,2) else ('SURVIVED' if r.returncode==0 else f'ERR{r.returncode}')
def build(name,new_src):
    work=pathlib.Path('mut2')/name
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(ROOT,work,ignore=shutil.ignore_patterns('spike','.git','__pycache__','.pytest_cache'))
    (work/'comment_intent_guard.py').write_text(new_src); return work
print('mutant / whole suite')
for name,s,old,new in M:
    a,b=sec[s]; seg=body[a:b]
    if seg.count(old)!=1: print(f'{name:34s} INAPPLICABLE',flush=True); continue
    nb=body[:a]+seg.replace(old,new)+body[b:]
    work=build(name,SRC[:start]+nb+SRC[end:])
    print(f'{name:34s} {run(work,["tests"])}',flush=True)
for name,old,new in CLS:
    assert SRC.count(old)==1; work=build(name,SRC.replace(old,new))
    print(f'{name:34s} {run(work,["tests"])}',flush=True)

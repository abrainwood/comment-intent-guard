import os, sys, pathlib, re
sys.argv += []
root = pathlib.Path(os.environ.get("R83_ROOT") or pathlib.Path(__file__).resolve().parents[3])
os.chdir(root / "tests"); sys.path.insert(0, str(root / "tests"))
import test_csharp_analyser as t
seed, count = int(sys.argv[1]), int(sys.argv[2])
t._CSHARP_SOUP_SEED, t._CSHARP_SOUP_CASE_COUNT = seed, count
names = ["test_csharp_lex_never_raises_on_seeded_char_soup",
         "test_csharp_lex_span_rows_and_close_columns_stay_within_the_text",
         "test_csharp_lex_tokens_stay_within_the_text_and_in_non_decreasing_row_order",
         "test_csharp_try_skip_literal_end_is_in_bounds_and_within_its_line_for_plain_strings",
         "test_csharp_lex_is_idempotent_under_crlf_line_endings"]
fails = 0
for n in names:
    try:
        getattr(t, n)(); print("PASS", n)
    except BaseException as e:
        fails += 1; print("FAIL", n, str(e)[:300])
print("failures", fails)

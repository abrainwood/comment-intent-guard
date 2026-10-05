#!/bin/sh
# usage: run_variant.sh <variant_name> <module_file>  -> runs PR test file against that module
set -e
R=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$R/../../.." && pwd)
V="$R/variants/$1"
rm -rf "$V"; mkdir -p "$V/tests"
cp "$2" "$V/comment_intent_guard.py"
cp "$ROOT/tests/test_csharp_analyser.py" "$ROOT/tests/conftest.py" "$V/tests/"
cd "$V" && python -m pytest -q -p no:cacheprovider -o addopts= --timeout=300 tests/test_csharp_analyser.py \
  -k "backslash_before or unterminated_char_literal_followed or line_bound_literal_edge or soup or csharp_lex_never or span_rows or tokens_stay or try_skip_literal_end or idempotent_under_crlf" 2>&1 | grep -E "^(FAILED|ERROR)|passed|failed" || true

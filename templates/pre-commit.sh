#!/usr/bin/env bash
# comment-intent-guard pre-commit
set -euo pipefail

_find_guard_script() {
  if [ -n "${COMMENT_INTENT_GUARD:-}" ]; then
    printf '%s\n' "$COMMENT_INTENT_GUARD"
    return 0
  fi
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "${CLAUDE_PLUGIN_ROOT}/comment_intent_guard.py" ]; then
    printf '%s\n' "${CLAUDE_PLUGIN_ROOT}/comment_intent_guard.py"
    return 0
  fi
  local newest
  # python's getmtime is portable across the BSD and GNU `stat` flag split.
  newest="$(find "${HOME}/.claude/plugins" -path '*/comment-intent-guard/comment_intent_guard.py' -print0 2>/dev/null \
    | xargs -0 -I{} python3 -c 'import os, sys; print(os.path.getmtime(sys.argv[1]), sys.argv[1])' {} 2>/dev/null \
    | sort -rn | head -n1 | cut -d' ' -f2-)"
  if [ -n "$newest" ]; then
    printf '%s\n' "$newest"
    return 0
  fi
  return 1
}

guard_script="$(_find_guard_script)" || {
  echo "comment-intent-guard: could not locate comment_intent_guard.py (set COMMENT_INTENT_GUARD)" >&2
  exit 1
}

staged=()
while IFS= read -r file; do
  staged+=("$file")
done < <(git diff --cached --name-only --diff-filter=ACMR -- '*.py' '*.yaml' '*.yml' '*.jinja' '*.j2')
if [ "${#staged[@]}" -eq 0 ]; then
  exit 0
fi

set +e
output="$(python3 "$guard_script" --all "${staged[@]}")"
code=$?
set -e

case "$code" in
  0) exit 0 ;;
  1)
    printf '%s\n' "$output"
    exit 0
    ;;
  *)
    printf '%s\n' "$output" >&2
    echo "comment-intent-guard: blocking findings - commit aborted" >&2
    exit 1
    ;;
esac

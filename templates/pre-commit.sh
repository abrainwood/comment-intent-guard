#!/usr/bin/env bash
# comment-intent-guard pre-commit
set -euo pipefail

_resolve_from_installed_plugins() {
  local installed_json="${HOME}/.claude/plugins/installed_plugins.json"
  [ -f "$installed_json" ] || return 1
  local install_dir
  install_dir="$(python3 - "$installed_json" <<'PY'
import json
import sys


def warn_and_skip(reason):
    print(
        f"comment-intent-guard: WARNING - {sys.argv[1]} ({reason}) - falling through",
        file=sys.stderr,
    )
    sys.exit(1)


try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    warn_and_skip(f"{type(exc).__name__}: {exc}")

if not isinstance(data, dict) or not isinstance(data.get("plugins"), dict):
    warn_and_skip("not shaped like installed_plugins.json")

candidates = []
for key, entries in data["plugins"].items():
    if not key.startswith("comment-intent-guard@") or not isinstance(entries, list):
        continue
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        install_path = entry.get("installPath")
        if not isinstance(install_path, str):
            continue
        last_updated = entry.get("lastUpdated")
        if not isinstance(last_updated, str):
            last_updated = ""
        candidates.append((last_updated, install_path))

if not candidates:
    sys.exit(1)
print(max(candidates)[1])
PY
)" || return 1
  [ -n "$install_dir" ] && [ -f "${install_dir}/comment_intent_guard.py" ] || return 1
  printf '%s\n' "${install_dir}/comment_intent_guard.py"
}

_newest_by_mtime() {
  python3 -c 'import os, sys; print(max(sys.argv[1:], key=os.path.getmtime))' "$@"
}

_find_guard_script() {
  if [ -n "${COMMENT_INTENT_GUARD:-}" ]; then
    printf '%s\n' "$COMMENT_INTENT_GUARD"
    return 0
  fi
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "${CLAUDE_PLUGIN_ROOT}/comment_intent_guard.py" ]; then
    printf '%s\n' "${CLAUDE_PLUGIN_ROOT}/comment_intent_guard.py"
    return 0
  fi
  if _resolve_from_installed_plugins; then
    return 0
  fi
  local candidates=()
  while IFS= read -r -d '' candidate; do
    candidates+=("$candidate")
  done < <(find "${HOME}/.claude/plugins/cache" -path '*/comment-intent-guard/*/comment_intent_guard.py' -print0 2>/dev/null)
  if [ "${#candidates[@]}" -gt 0 ]; then
    _newest_by_mtime "${candidates[@]}"
    return 0
  fi
  return 1
}

_warn_and_pass() {
  echo "comment-intent-guard: WARNING - $1 - not blocking this commit" >&2
  exit 0
}

if ! guard_script="$(_find_guard_script)"; then
  _warn_and_pass "could not locate comment_intent_guard.py (set COMMENT_INTENT_GUARD)"
fi

staged=()
while IFS= read -r -d '' file; do
  staged+=("$file")
done < <(git diff --cached -z --name-only --diff-filter=ACMR -- '*.py' '*.yaml' '*.yml' '*.jinja' '*.j2')
if [ "${#staged[@]}" -eq 0 ]; then
  exit 0
fi

config_files=()
while IFS= read -r -d '' file; do
  config_files+=("$file")
done < <(git ls-files -z -- ':(glob)**/.comment-intent-guard.json')

check_staged_index_content() {
  local snapshot_dir
  snapshot_dir="$(mktemp -d)"
  trap 'rm -rf "$snapshot_dir"' RETURN
  git checkout-index --prefix="${snapshot_dir}/" -- "${staged[@]}"
  if [ "${#config_files[@]}" -gt 0 ]; then
    git checkout-index --prefix="${snapshot_dir}/" -- "${config_files[@]}"
  fi
  (cd "$snapshot_dir" && python3 "$guard_script" --all "${staged[@]}")
}

set +e
output="$(check_staged_index_content)"
code=$?
set -e

case "$code" in
  0) exit 0 ;;
  1)
    printf '%s\n' "$output"
    exit 0
    ;;
  3)
    printf '%s\n' "$output" >&2
    echo "comment-intent-guard: blocking findings - commit aborted" >&2
    exit 1
    ;;
  *)
    interpreter_version="$(python3 --version 2>&1)"
    printf '%s\n' "$output" >&2
    _warn_and_pass "$guard_script exited $code under $interpreter_version"
    ;;
esac

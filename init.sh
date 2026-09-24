#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
CLAUDE_MD_MARKER="<!-- comment-intent-guard:comment-guard-init -->"

FORCE=0
for arg in "$@"; do
  if [ "$arg" = "--force" ]; then
    FORCE=1
  fi
done

JSON_DEST="$REPO_ROOT/.comment-intent-guard.json"
JSON_SRC="$SCRIPT_DIR/templates/comment-intent-guard.json"
PRE_COMMIT_DEST="$REPO_ROOT/.githooks/pre-commit"
PRE_COMMIT_SRC="$SCRIPT_DIR/templates/pre-commit.sh"
WORKFLOW_DEST="$REPO_ROOT/.github/workflows/comment-guard.yml"
CLAUDE_MD="$REPO_ROOT/CLAUDE.md"

# The template carries an instructional comment for whoever browses the repo
# of templates; strip it before it lands in a consumer's own workflow file.
WORKFLOW_EFFECTIVE="$(mktemp)"
trap 'rm -f "$WORKFLOW_EFFECTIVE"' EXIT
tail -n +2 "$SCRIPT_DIR/templates/comment-guard.yml" > "$WORKFLOW_EFFECTIVE"

refuse() {
  echo "init.sh: $1" >&2
  exit 1
}

existing_hooks_path="$(git -C "$REPO_ROOT" config core.hooksPath || true)"
if [ -n "$existing_hooks_path" ] && [ "$existing_hooks_path" != ".githooks" ]; then
  refuse "refusing to change core.hooksPath - it already points at $existing_hooks_path"
fi

git_common_dir_absolute() {
  local raw
  if raw="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    printf '%s\n' "$raw"
    return 0
  fi
  raw="$(git -C "$REPO_ROOT" rev-parse --git-common-dir)"
  case "$raw" in
    /*) printf '%s\n' "$raw" ;;
    *) (cd "$REPO_ROOT" && cd "$raw" && pwd -P) ;;
  esac
}

native_hook="$(git_common_dir_absolute)/hooks/pre-commit"
if [ -e "$native_hook" ]; then
  refuse "refusing to install - a native pre-commit hook already exists at $native_hook"
fi

write_report_line() {
  local dest="$1" verb="$2"
  echo "$verb ${dest#"$REPO_ROOT"/}"
}

# Per-file sync: absent -> write; present+identical -> skip silently as
# unchanged; present+different -> left alone unless --force AND forceable.
sync_target() {
  local dest="$1" src="$2" forceable="$3" merge_hint="${4:-}"
  if [ ! -e "$dest" ]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    write_report_line "$dest" "created"
    return 0
  fi
  if cmp -s "$dest" "$src"; then
    write_report_line "$dest" "unchanged"
    return 0
  fi
  if [ "$FORCE" -eq 1 ] && [ "$forceable" -eq 1 ]; then
    cp "$src" "$dest"
    write_report_line "$dest" "overwritten"
    return 0
  fi
  local suffix=""
  [ -n "$merge_hint" ] && suffix=" - $merge_hint"
  write_report_line "$dest" "left alone (differs from template)$suffix"
}

sync_target "$JSON_DEST" "$JSON_SRC" 0 "merge the two by hand, this file is never overwritten"

sync_target "$PRE_COMMIT_DEST" "$PRE_COMMIT_SRC" 1
if [ -e "$PRE_COMMIT_DEST" ] && cmp -s "$PRE_COMMIT_DEST" "$PRE_COMMIT_SRC"; then
  chmod +x "$PRE_COMMIT_DEST"
fi
git -C "$REPO_ROOT" config core.hooksPath .githooks
echo "core.hooksPath set to .githooks"

sync_target "$WORKFLOW_DEST" "$WORKFLOW_EFFECTIVE" 1

if [ ! -f "$CLAUDE_MD" ] || ! grep -qF "$CLAUDE_MD_MARKER" "$CLAUDE_MD"; then
  claude_md_existed=0
  [ -f "$CLAUDE_MD" ] && claude_md_existed=1
  if [ -s "$CLAUDE_MD" ] && [ "$(tail -c1 "$CLAUDE_MD")" != "" ]; then
    echo "" >> "$CLAUDE_MD"
  fi
  {
    echo ""
    echo "$CLAUDE_MD_MARKER"
    echo "Self-documenting code is enforced here by the comment-intent-guard plugin. Run /comment-intent-guard:comment-guard-init in Claude Code, or comment-intent-guard init on the command line, if these files are missing."
  } >> "$CLAUDE_MD"
  if [ "$claude_md_existed" -eq 1 ]; then
    write_report_line "$CLAUDE_MD" "appended"
  else
    write_report_line "$CLAUDE_MD" "created"
  fi
else
  write_report_line "$CLAUDE_MD" "unchanged"
fi

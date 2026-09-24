#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
PRE_COMMIT_MARKER="# comment-intent-guard pre-commit"
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
WORKFLOW_SRC="$SCRIPT_DIR/templates/comment-guard.yml"
CLAUDE_MD="$REPO_ROOT/CLAUDE.md"

refuse() {
  echo "init.sh: $1" >&2
  exit 1
}

# A destination not owned by us (no marker, or --force absent while it
# differs from the template) is left alone - refuse rather than guess.
check_template_owned() {
  local dest="$1" src="$2" marker="$3"
  [ -e "$dest" ] || return 0
  if [ -n "$marker" ] && ! grep -qF "$marker" "$dest"; then
    refuse "refusing to overwrite foreign file at $dest"
  fi
  if [ "$FORCE" -eq 0 ] && ! cmp -s "$dest" "$src"; then
    refuse "refusing to overwrite $dest - it differs from the template (use --force)"
  fi
}

existing_hooks_path="$(git -C "$REPO_ROOT" config core.hooksPath || true)"
if [ -n "$existing_hooks_path" ] && [ "$existing_hooks_path" != ".githooks" ]; then
  refuse "refusing to change core.hooksPath - it already points at $existing_hooks_path"
fi

native_hook="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/hooks/pre-commit"
if [ -e "$native_hook" ]; then
  refuse "refusing to install - a native pre-commit hook already exists at $native_hook"
fi

check_template_owned "$JSON_DEST" "$JSON_SRC" ""
check_template_owned "$PRE_COMMIT_DEST" "$PRE_COMMIT_SRC" "$PRE_COMMIT_MARKER"
check_template_owned "$WORKFLOW_DEST" "$WORKFLOW_SRC" ""

write_report_line() {
  local dest="$1" verb="$2"
  echo "$verb ${dest#"$REPO_ROOT"/}"
}

write_template() {
  local dest="$1" src="$2"
  if [ -e "$dest" ]; then
    if [ "$FORCE" -eq 1 ] && ! cmp -s "$dest" "$src"; then
      cp "$src" "$dest"
      write_report_line "$dest" "overwritten"
      return 0
    fi
    write_report_line "$dest" "unchanged"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  write_report_line "$dest" "created"
}

write_template "$JSON_DEST" "$JSON_SRC"

if [ ! -e "$PRE_COMMIT_DEST" ]; then
  mkdir -p "$REPO_ROOT/.githooks"
  cp "$PRE_COMMIT_SRC" "$PRE_COMMIT_DEST"
  chmod +x "$PRE_COMMIT_DEST"
  write_report_line "$PRE_COMMIT_DEST" "created"
elif ! cmp -s "$PRE_COMMIT_DEST" "$PRE_COMMIT_SRC"; then
  cp "$PRE_COMMIT_SRC" "$PRE_COMMIT_DEST"
  chmod +x "$PRE_COMMIT_DEST"
  write_report_line "$PRE_COMMIT_DEST" "overwritten"
else
  write_report_line "$PRE_COMMIT_DEST" "unchanged"
fi
git -C "$REPO_ROOT" config core.hooksPath .githooks
echo "core.hooksPath set to .githooks"

write_template "$WORKFLOW_DEST" "$WORKFLOW_SRC"

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

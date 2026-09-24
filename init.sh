#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
CLAUDE_MD_MARKER="<!-- comment-intent-guard:comment-guard-init -->"

usage() {
  echo "usage: comment-intent-guard init [--force]"
}

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --help|-h)
      usage
      exit 0
      ;;
    --force)
      FORCE=1
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

JSON_DEST="$REPO_ROOT/.comment-intent-guard.json"
JSON_SRC="$SCRIPT_DIR/templates/comment-intent-guard.json"
PRE_COMMIT_DEST="$REPO_ROOT/.githooks/pre-commit"
PRE_COMMIT_SRC="$SCRIPT_DIR/templates/pre-commit.sh"
WORKFLOW_DEST="$REPO_ROOT/.github/workflows/comment-guard.yml"
CLAUDE_MD="$REPO_ROOT/CLAUDE.md"

WORKFLOW_COPY_INSTRUCTIONS="# Copy into .github/workflows/ to enforce the guard on every PR."

strip_template_instructions() {
  grep -vFx "$WORKFLOW_COPY_INSTRUCTIONS" "$1" || [ "$?" -eq 1 ]
}

TMP_FILES=()
trap 'rm -f "${TMP_FILES[@]:-}"' EXIT

WORKFLOW_EFFECTIVE="$(mktemp)"
TMP_FILES+=("$WORKFLOW_EFFECTIVE")
strip_template_instructions "$SCRIPT_DIR/templates/comment-guard.yml" > "$WORKFLOW_EFFECTIVE"

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

PRE_COMMIT_MARKER="# comment-intent-guard pre-commit"

has_pre_commit_marker() {
  grep -qF "$PRE_COMMIT_MARKER" "$1"
}

write_report_line() {
  local dest="$1" verb="$2"
  echo "${dest#"$REPO_ROOT"/} $verb"
}

sync_target() {
  local dest="$1" src="$2" forceable="$3" merge_hint="${4:-}" upgrade_fn="${5:-}" force_guard_fn="${6:-}"
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
  if [ -n "$upgrade_fn" ]; then
    local stripped
    stripped="$(mktemp)"
    TMP_FILES+=("$stripped")
    "$upgrade_fn" "$dest" > "$stripped"
    if cmp -s "$stripped" "$src"; then
      cp "$src" "$dest"
      write_report_line "$dest" "updated (dropped stale template instructions)"
      return 0
    fi
  fi
  local allow_force="$forceable" force_denied_reason=""
  if [ -n "$force_guard_fn" ] && ! "$force_guard_fn" "$dest"; then
    allow_force=0
    force_denied_reason=" - foreign file (no comment-intent-guard marker), --force will not overwrite it"
  fi
  if [ "$FORCE" -eq 1 ] && [ "$allow_force" -eq 1 ]; then
    cp "$src" "$dest"
    write_report_line "$dest" "overwritten"
    return 0
  fi
  local suffix="$force_denied_reason"
  [ -z "$suffix" ] && [ -n "$merge_hint" ] && suffix=" - $merge_hint"
  write_report_line "$dest" "left alone (differs from template)$suffix"
}

sync_target "$JSON_DEST" "$JSON_SRC" 0 "merge the two by hand, this file is never overwritten"

sync_target "$PRE_COMMIT_DEST" "$PRE_COMMIT_SRC" 1 "" "" has_pre_commit_marker
if [ -e "$PRE_COMMIT_DEST" ] && cmp -s "$PRE_COMMIT_DEST" "$PRE_COMMIT_SRC"; then
  chmod +x "$PRE_COMMIT_DEST"
fi
git -C "$REPO_ROOT" config core.hooksPath .githooks
echo "core.hooksPath set to .githooks"

sync_target "$WORKFLOW_DEST" "$WORKFLOW_EFFECTIVE" 1 "" strip_template_instructions

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

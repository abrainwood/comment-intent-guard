#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
PRE_COMMIT_MARKER="# comment-intent-guard pre-commit"
CLAUDE_MD_MARKER="<!-- comment-intent-guard:comment-guard-init -->"

write_matching_template() {
  local dest="$1" src="$2"
  if [ -e "$dest" ]; then
    if ! cmp -s "$dest" "$src"; then
      echo "init.sh: refusing to overwrite $dest - it differs from the template" >&2
      exit 1
    fi
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

pre_commit_dest="$REPO_ROOT/.githooks/pre-commit"
if [ -e "$pre_commit_dest" ] && ! grep -qF "$PRE_COMMIT_MARKER" "$pre_commit_dest"; then
  echo "init.sh: refusing to overwrite foreign pre-commit hook at $pre_commit_dest" >&2
  exit 1
fi

write_matching_template "$REPO_ROOT/.comment-intent-guard.json" "$SCRIPT_DIR/templates/comment-intent-guard.json"

if [ ! -e "$pre_commit_dest" ]; then
  mkdir -p "$REPO_ROOT/.githooks"
  cp "$SCRIPT_DIR/templates/pre-commit.sh" "$pre_commit_dest"
  chmod +x "$pre_commit_dest"
fi
git -C "$REPO_ROOT" config core.hooksPath .githooks

write_matching_template "$REPO_ROOT/.github/workflows/comment-guard.yml" "$SCRIPT_DIR/templates/comment-guard.yml"

claude_md="$REPO_ROOT/CLAUDE.md"
if [ ! -f "$claude_md" ] || ! grep -qF "$CLAUDE_MD_MARKER" "$claude_md"; then
  {
    echo ""
    echo "$CLAUDE_MD_MARKER"
    echo "Self-documenting code is enforced here by the comment-intent-guard plugin. Run /comment-guard-init if these files are missing."
  } >> "$claude_md"
fi

echo "comment-intent-guard: initialized $REPO_ROOT"

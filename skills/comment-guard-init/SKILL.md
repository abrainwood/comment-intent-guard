---
name: comment-guard-init
description: Wire the comment-intent guard into the current repo (pre-commit hook, CI gate, config, CLAUDE.md stanza). Use when the user asks to set up, install, or init the comment-intent guard in this repo, or invokes /comment-intent-guard:comment-guard-init.
---

Run `comment-intent-guard init` from the repository root.

The script is idempotent: running it again after it already succeeded changes
nothing and exits 0. It refuses (non-zero exit, nothing written) if
`.githooks/pre-commit` already exists and wasn't written by this guard -
report that message to the user rather than working around it.

After it runs, report to the user exactly what `init.sh` printed: which
files it created or left alone, and whether `core.hooksPath` was set.

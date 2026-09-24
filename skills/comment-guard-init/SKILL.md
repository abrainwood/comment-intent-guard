---
name: comment-guard-init
description: Wire the comment-intent guard into the current repo (pre-commit hook, CI gate, config, CLAUDE.md stanza). Use when the user asks to set up, install, or init the comment-intent guard in this repo, or invokes /comment-intent-guard:comment-guard-init.
---

Run `comment-intent-guard init` from the repository root.

The script is idempotent and per-file: running it again after it already
succeeded changes nothing and exits 0. Each of the four targets (pre-commit
hook, CI caller workflow, `.comment-intent-guard.json` allowlist, CLAUDE.md
stanza) is handled independently - written if absent, left alone with a
one-line notice if present and different from the template, skipped silently
if already identical. `--force` overwrites files that differ, except the
allowlist json, which is never overwritten (the notice explains how to merge
it by hand). It still refuses outright (non-zero exit, nothing written) for
two cases that predate any of the per-file targets: `core.hooksPath` already
pointing somewhere else, or a native `.git/hooks/pre-commit` already in
place - report that message to the user rather than working around it.

After it runs, report to the user exactly what `init.sh` printed: which
files it created, left alone, or overwrote, and whether `core.hooksPath` was
set.

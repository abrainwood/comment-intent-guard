# Security Policy

## Supported versions

Only the latest tagged release (`comment-intent-guard--vX.Y.Z`) is
supported. Update via `claude plugin update comment-intent-guard@comment-intent-guard`,
then restart Claude Code to apply it.

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/abrainwood/comment-intent-guard/security/advisories/new)
rather than in a public issue. Do not open a public issue for a suspected
vulnerability.

## What the hooks run and where their state lives

The plugin's hooks execute on your machine as part of your Claude Code
session, not on a remote server. They read the content Claude is about to
write or has already written (via `Write`/`Edit` tool input, or the Bash
backstop's git diff) and analyze it for the patterns described in the
README - they do not transmit anything over the network.

Two things persist to disk between hook invocations:

- **Comment/code density state**, at `~/.claude/comment-intent-guard/state.json`
  (override with the `COMMENT_INTENT_GUARD_STATE` env var). It stores
  running comment-line and code-line counts per session id, used to flag a
  comment-heavy session - not file contents or file paths.
- **Bash backstop stamps**, alongside it at
  `~/.claude/comment-intent-guard/bash_backstop_stamps.json`, recording the
  last-checked timestamp per session so the backstop only re-scans lines
  added since its previous check.

Both files are local, plain JSON, and scoped to your user account. Neither
is read by the pre-commit hook or the CI gate, which each run stateless,
one-shot checks over the diff they're given.

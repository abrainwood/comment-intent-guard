---
name: comment-guard-scan
description: On-demand scan of everything uncommitted in the current repo (tracked changes plus untracked files), beyond what the session's own edits have already flagged. Use when the user asks to scan, check, or audit the whole repo's uncommitted changes, or invokes /comment-intent-guard:comment-guard-scan.
---

Run `comment-intent-guard scan` from the repository root.

It exits 0 with "nothing uncommitted to scan" on a clean tree, 0 or 1 with
findings printed for advisory-only results, 3 if any bright line is
violated, and 2 if the current directory isn't inside a git repository -
report that message rather than retrying elsewhere. A run under
`--plugin-dir .` needs no other setup.

Report the findings back to the user grouped by file, in the order the
command printed them. For any bright line (a blocking finding, not an
advisory one), point the user at the self-documenting-code skill for how
to fix it rather than editing the flagged file yourself.

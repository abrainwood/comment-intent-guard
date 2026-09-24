---
name: comment-guard-scan
description: On-demand scan of everything uncommitted in the current repo (tracked changes plus untracked files), beyond what the session's own edits have already flagged. Use when the user asks to scan, check, or audit the whole repo's uncommitted changes, or invokes /comment-intent-guard:comment-guard-scan.
---

Run `comment-intent-guard scan` from the repository root.

It exits 0 on a clean tree, printing only "nothing uncommitted to scan" and
nothing else; 1 with advisory findings printed; 3 if any bright line is
violated; 4 if some files could not be read, still printing any BLOCKED
lines found among the files that were readable; and 2 if the current
directory isn't inside a git repository - report that message rather than
retrying elsewhere.

A bright line is any printed line prefixed "BLOCKED"; every other printed
finding is advisory.

Report the findings back to the user grouped by file, in the order the
command printed them. For any bright line (a blocking finding, not an
advisory one), point the user at the self-documenting-code skill for how
to fix it rather than editing the flagged file yourself.

---
name: self-documenting-code
description: Remediation guide for a comment-intent-guard deny, and the rule to apply before writing any comment or docstring. Use when a Write or Edit is denied for a rationale-in-comment violation, or when about to add a comment, docstring, or explanatory prose to source.
---

# Self-documenting code, always

Write code that needs no comment. If it needs one, that's an alarm about the design, not a fact to transcribe - answer it upstream: rename, retype, change the approach, or split. A split whose pieces each need explaining was the wrong move.

Two residues survive the alarm, each reviewer-checkable, tested per clause not per comment:

- **Body line** - only what the next editor inherits rather than what we decided: an external quirk, or an algorithm's own requirement (someone who knows the algorithm and has never seen this repo would write the same line). One line, at the line.
- **Interface docstring** - one line of contract, only when name and types are exhausted and deleting it would force the caller into the body.

Tests have no caller, and no test docstring is an external quirk or an algorithm's requirement - so every one is an alarm. Rename the test.

Why we chose it never lives in source; that's the PR. And the PR carries narrative only - nothing needed to edit safely lives there alone.

How to adjudicate a specific line, and worked examples: [comments.md](comments.md).

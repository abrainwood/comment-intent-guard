# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- C# support for the comment-intent guard, including `///` XML doc comments
  on test methods as a bright line - PR #30 (Add C# support), closing issue
  #25 (Support C# / .NET source).
- Mutation testing setup: `scripts/mutate.sh`, pinned `mutmut` venv, and
  patches crediting subprocess-reached tests - PR #32 (Commit the
  mutation-testing setup).

### Changed

- Uncommitted-file listing for `scan` moved from shell into Python - PR #28
  (Move uncommitted-file listing into Python), closing issue #22 (scan:
  move uncommitted-file listing into the guard CLI) and issue #21 (Bash
  backstop: filename with both a double quote and a char above U+00FF
  fails to unquote).
- `init.sh` now wires the pre-commit hook per-file instead of repo-wide,
  and resolves the native-hook path on git older than 2.31 - PR #27 (Make
  init per-file and support git older than 2.31), closing issue #24 (init
  refuses everything when .comment-intent-guard.json already differs from
  the template) and implementing the fallback issue #19 (init.sh
  native-hook check needs git >= 2.31) describes. Note: issue #19 itself
  is still open on GitHub despite the fix landing - worth closing
  separately.

### Fixed

- Closed test-suite gaps found by the mutation-testing audit in the guard
  module and the hooks - PR #33 (Close audit #31 gaps in the guard module
  tests) and PR #34 (Close audit #31 gaps in the hooks tests and cut their
  runtime), both against issue #31 (Test audit 2026-09-24: mutation
  survivors and suite gaps).

### Known follow-ups (not yet done)

- Issue #31 (Test audit 2026-09-24: mutation survivors and suite gaps) -
  parent tracking issue; PRs #33/#34 above close part of it, remainder
  still open.
- Issue #35 (C#: doc block between [Fact] and a second attribute reports
  the attribute name, not the method).
- Issue #37 (hooks.json: quote ${CLAUDE_PLUGIN_ROOT} in all three hook
  commands).
- Issue #38 (init: unknown arguments (e.g. --help) are ignored and init
  runs anyway).
- Issue #29 (scan --base HEAD: batch the per-file _added_line_numbers git
  calls).

## [1.0.0] - 2026-09-24 - Initial plugin release

Initial public release, shipped as a Claude Code plugin: PreToolUse deny
hook, PostToolUse Bash backstop, pre-commit hook, SessionStart hook that
injects the self-documenting-code rule into context, reusable CI gate
(`gate.yml`), `comment-intent-guard scan`/`check`/`init` CLI, and the
`self-documenting-code`, `comment-guard-init`, and `comment-guard-scan`
skills. Python, YAML, and Jinja support.

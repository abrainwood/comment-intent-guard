# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.2.1] - 2026-09-26

### Fixed

- C# unterminated `/*` on an attribute line no longer hides the following
  doc block - PR #53 (C#: unterminated /* on an attribute line hides the
  following doc block), closing issue #49. The lookahead now threads a
  resolved `(line, rest)` through the attribute walk via a single
  `_csharp_skip_comments` helper instead of re-deriving it from the raw
  line.
- C# block and line comments between two attributes on one line now
  report the method, not the attribute - PR #56 (C#: block comment
  between two attributes on one line names the attribute, not the
  method), closing issue #50. Fixes both the forward and backward
  attribute walk; `_csharp_is_only_comments` is deleted in favour of
  `_csharp_skip_comments`.
- C# a closed multi-line block comment between an attribute and a doc
  block is now handled on the backward path - PR #57 (C#: skip closed
  multi-line block comment on the backward attribute path), closing
  issue #55. Adds `_csharp_find_block_comment_open`, mirroring the
  existing forward `_csharp_find_block_comment_close`.
- `scan --base` batching leftovers from #29 (PR #54, closing issue #51):
  a chunk failure now names only the failing chunk in its warning instead
  of the whole group; both the `"a.py"` and `"./a.py"` spellings of the
  same file are kept in the result instead of one silently dropping the
  other; the scan path skips the redundant `git status` call since its
  file list already comes from `git diff --name-only`; a `git status`
  failure on one chunk now degrades only that chunk's files, matching the
  diff loop's existing per-chunk degradation (a behaviour change from the
  prior whole-group degrade); two flaky timing-dependent tests fixed. The
  status and diff loops now share one `_run_chunked_git_command` helper.

### Changed

- `tests/test_bin_scan.py` and `tests/test_scan_listing.py` migrated onto
  the session-scoped `git_repo` template fixture, the same pattern used
  for `test_init.py`/`test_workflows.py` under #39 - part of PR #54,
  closing issue #48's remaining item. Issue #48's other item,
  `scripts/mutate.sh` verified end-to-end on Linux, is also closed; scan
  tests run against the session repo template.

### Known gaps

- Issue #58 (C# stacked multi-line block comments between an attribute
  and a doc block, e.g. two chained `/* ... */` comments, are still
  missed on the backward path).

## [1.2.0] - 2026-09-25

### Fixed

- C# doc-block findings now name the method, not a trailing attribute, and
  report one finding per method instead of a duplicate - PR #44 (C#: name
  the method, not the attribute, and dedupe doc-block findings), closing
  issue #35 (C#: doc block between [Fact] and a second attribute reports
  the attribute name, not the method). Trailing comments on an attribute
  line no longer hide the doc block on either the forward or backward
  lookup.
- `scan --base` now issues one `git status` and one `git diff` per
  repository instead of two per file, with correct handling of quoted,
  non-ASCII, and space-containing paths and of files reached through a
  symlink - PR #47 (Batch _added_line_numbers git calls), closing issue
  #29 (scan --base HEAD: batch the per-file _added_line_numbers git
  calls).

### Changed

- The backstop diff parser now lives in `comment_intent_guard.py`, shared
  by the guard and the Bash backstop hook; the test suite runs off shared
  session-scoped templates and uses `pytest-xdist` in CI - PR #46 (Test
  suite speed and hygiene), closing issue #39 (Test suite speed and
  hygiene follow-ups from audit 2).

### Removed

- `docs/shippable-packaging.md`, pre-public planning notes not relevant to
  plugin contributors - PR #45 (Remove internal packaging notes doc).

### Known gaps

- Issue #49 (an attribute line with a genuinely unterminated `/*` followed
  by real code is treated as comment-only) and issue #50 (a block comment
  between two attributes on one line makes the violation report against
  the attribute name instead of the method below it).

## [1.1.0] - 2026-09-25

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
  the template) and issue #19 (init.sh native-hook check needs git >=
  2.31).

### Fixed

- Closed test-suite gaps found by the mutation-testing audit in the guard
  module and the hooks - PR #33 (Close audit #31 gaps in the guard module
  tests) and PR #34 (Close audit #31 gaps in the hooks tests and cut their
  runtime), both against issue #31 (Test audit 2026-09-24: mutation
  survivors and suite gaps).
- `init.sh` now validates its arguments (`--help`/`-h` prints usage and
  exits 0, an unknown flag prints usage to stderr and exits 2) and all
  three `hooks/hooks.json` commands quote `${CLAUDE_PLUGIN_ROOT}` - PR #40
  (init arg validation and quoted hook paths), closing issue #37
  (hooks.json: quote ${CLAUDE_PLUGIN_ROOT} in all three hook commands) and
  issue #38 (init: unknown arguments are ignored and init runs anyway).
- Closed the remaining audit-2 mutation survivors in the hooks
  (`bash_backstop.py`, `session_start.py`, `stamps.py`) - PR #41 (Audit 2:
  hooks survivors (#31)), part of issue #31.
- Closed the remaining audit-2 mutation survivors in the guard module and
  its C# support - PR #42 (Audit 2: guard and C# survivors (#31)), part of
  issue #31.

### Known follow-ups (not yet done)

- Issue #29 (scan --base HEAD: batch the per-file _added_line_numbers git
  calls).
- Issue #35 (C#: doc block between [Fact] and a second attribute reports
  the attribute name, not the method).
- Issue #39 (Test suite speed and hygiene follow-ups from audit 2).

## [1.0.0] - 2026-09-24 - Initial plugin release

Initial public release, shipped as a Claude Code plugin: PreToolUse deny
hook, PostToolUse Bash backstop, pre-commit hook, SessionStart hook that
injects the self-documenting-code rule into context, reusable CI gate
(`gate.yml`), `comment-intent-guard scan`/`check`/`init` CLI, and the
`self-documenting-code`, `comment-guard-init`, and `comment-guard-scan`
skills. Python, YAML, and Jinja support.

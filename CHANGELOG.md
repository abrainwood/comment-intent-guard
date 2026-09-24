# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- C# support for the comment-intent guard, including `///` XML doc comments
  on test methods as a bright line (#30).
- Mutation testing setup: `scripts/mutate.sh`, pinned `mutmut` venv, and
  patches crediting subprocess-reached tests (#32).

### Changed

- Uncommitted-file listing for `scan` moved from shell into Python (#28).
- `init.sh` now wires the pre-commit hook per-file instead of repo-wide,
  and supports git older than 2.31 (#24, #19).

### Fixed

- Closed test-suite gaps found by the mutation-testing audit in the guard
  module and the hooks (#33, #34).

### Known follow-ups (not yet done)

- #35, #29 - open, tracked separately.

## [1.0.0] - Initial plugin release

Initial public release, shipped as a Claude Code plugin: PreToolUse deny
hook, PostToolUse Bash backstop, pre-commit hook, reusable CI gate
(`gate.yml`), `comment-intent-guard scan`/`check`/`init` CLI, and the
`self-documenting-code` and `comment-guard-init` skills. Python, YAML, and
Jinja support.

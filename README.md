# comment-intent-guard

A PreToolUse hook and CLI that flags rationale written into source comments -
dates, measurements, commit SHAs, oversize docstrings and comment runs - that
belongs in the issue, PR, or design doc instead. Some findings are advisory;
a few (external ticket IDs, docstrings on test functions) are bright-line
denials.

## Hook mode

With no arguments, `comment_intent_guard.py` reads a Claude Code
`PreToolUse` JSON payload from stdin and reports on the `content` /
`new_string` of a `Write` or `Edit` tool call. A bright-line violation denies
the tool call; an advisory finding is surfaced as additional context. Wire it
up as a `PreToolUse` hook for `Write` and `Edit` in your Claude Code settings.

## CLI mode

```
comment_intent_guard.py --all <files...>
comment_intent_guard.py --base <git-ref> <files...>
```

Dispatches on file extension (`.py` vs `.yaml`/`.yml`). `--all` scans whole
files. `--base <ref>` restricts findings to lines added since `<ref>` (via
`git diff`), for CI use on a pull request.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Clean - no findings |
| 1 | Advisory findings only |
| 3 | A bright-line violation was found |
| 4 | Internal error (unreadable file, unsupported Python version, ...) |

## Requirements

Python 3.12+ - the Python analysis uses `tokenize`'s f-string token support,
added in 3.12. Below that, Python findings are skipped and reported as exit
code 4; YAML findings are unaffected.

## Consumers

`tests/test_public_api.py` is a contract test over this module's public
surface. Known external consumers:

- `home-assistant-config`'s differential comment-guard test imports
  `find_misplaced_rationale` and `DOCSTRING_LINE_THRESHOLD` directly.

If you change a symbol listed in `tests/test_public_api.py`, check for
consumers before merging.

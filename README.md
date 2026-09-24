# comment-intent-guard

A Claude Code plugin that flags rationale written into source comments -
dates, measurements, commit SHAs, issue references, oversize docstrings and
comment runs - that belongs in the issue, PR, or design doc instead. Some
findings are advisory; a few are bright-line denials. Python, YAML, Jinja,
and C#.

## Install

```
/plugin marketplace add abrainwood/comment-intent-guard
/plugin install comment-intent-guard@comment-intent-guard
```

Then, from inside the repo you want it to guard, run
`/comment-intent-guard:comment-guard-init` and make your first commit.

To pin the plugin for a whole team, commit `.claude/settings.json` with:

```json
{
  "extraKnownMarketplaces": {"comment-intent-guard": {"source": {"source": "github", "repo": "abrainwood/comment-intent-guard"}}},
  "enabledPlugins": {"comment-intent-guard@comment-intent-guard": true}
}
```

## The four enforcement layers

- **PreToolUse deny.** A `Write`/`Edit` whose new content trips a bright
  line is denied outright, before it lands on disk.
- **PostToolUse Bash backstop.** Catches source written via `Bash` (heredocs,
  `sed`, etc.), which the deny hook never sees. Session-scoped: seeded at
  `SessionStart`, it only looks at lines added since the last check, capped
  at 40 findings / 4KB. It never denies - findings surface as additional
  context for Claude to act on.
- **Pre-commit hook**, wired via `core.hooksPath`. Runs the guard over the
  staged index content (not the working tree). Blocks the commit on a
  bright-line finding; fails **open** with a warning if the guard can't be
  found or errors internally, so a broken hook never blocks a commit.
- **CI gate** (`gate.yml`, a reusable workflow). Runs on pull requests,
  diffs against the PR's merge-base, and fails the build on a bright-line or
  internal-error exit; advisory findings are posted as PR annotations, not
  blocking.

## Skills

- **self-documenting-code** - the rule to apply before writing any comment
  or docstring, and the remediation guide when a deny fires. See
  `skills/self-documenting-code/SKILL.md` and its `comments.md`.
- **comment-guard-init** - wires the guard into a repo: pre-commit hook, CI
  gate, config, CLAUDE.md stanza. `/comment-intent-guard:comment-guard-init`.
- **comment-guard-scan** - on-demand scan of everything uncommitted in the
  repo, tracked and untracked, beyond what the current session already
  flagged. `/comment-intent-guard:comment-guard-scan`.

## CLI mode

```
comment-intent-guard scan
comment_intent_guard.py --all <files...>
comment_intent_guard.py --base <git-ref> <files...>
```

`scan` covers everything uncommitted; `--all` scans whole files; `--base
<ref>` restricts advisory findings to lines added since `<ref>`.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Clean - no findings |
| 1 | Advisory findings only |
| 2 | Usage error - invalid or missing command-line arguments |
| 3 | A bright-line violation was found |
| 4 | Internal error (unreadable file, unsupported Python version, ...) |

## Bright lines and advisory findings

Bright lines (deny/block): an issue reference (`#123`) in a comment,
docstring, or YAML/Jinja/C# comment block; a docstring (or C# `///` XML doc
comment) on a test function/method; an external id (`SP-9`-style in a
docstring, `sp1`-style in a filename or test name) not covered by the
repo's allowlist.

Advisory (surfaced, never blocks): a date, measurement, or SHA in a comment
or docstring; a docstring over the 12-line threshold; a comment run over 4
lines.

## Per-repo id allowlist

Two bright lines flag identifier-shaped tokens as external ids. Some repos
have their own domain vocabulary that happens to match those shapes and
isn't a ticket reference at all - declare it in `.comment-intent-guard.json`
(nearest ancestor of the checked file wins):

```json
{
  "id_prefix_allowlist": ["sp", "mg"],
  "filename_only_id_prefix_allowlist": ["gh"]
}
```

`id_prefix_allowlist` clears a prefix everywhere; `filename_only_id_prefix_allowlist`
clears it in filenames only, for a convention like `gh<N>_<slug>.py` where
the id still shouldn't appear in the file's own prose. A missing,
unreadable, or malformed config file is a warning, not a disabled rule -
the bright lines stay enforced.

## Requirements

Python 3.12 or newer - the Python analysis uses `tokenize`'s f-string token
support, added in 3.12. Below that, Python findings are skipped and reported
as exit code 4; YAML findings are unaffected. CI runs the suite on 3.12,
3.13, and 3.14.

Git 2.31 or newer for the pre-commit hook's native-hook path resolution
(`git rev-parse --path-format=absolute`). See issue #19 for older-git
fallback status.

## Mutation testing

A mutant is a small automatic edit to the production code, such as flipping
`<` to `<=` or dropping an argument. The suite kills a mutant when some test
fails, and a surviving mutant is a code change no test notices.

```sh
scripts/mutate.sh                               # fast lane, a few minutes
scripts/mutate.sh 'hooks.session_start.*'       # one module
scripts/mutate.sh --with-subprocess-coverage    # full audit, about an hour
```

The script builds `.venv-mutate` with a pinned mutmut, applies the patches in
`scripts/mutmut-patches/`, runs, and prints the surviving mutants. The first
patch maps mutants to modules by file path, so hooks loaded under another name
or run as `__main__` still pick up their mutants. The second patch credits
tests that reach the code through a spawned process; it only switches on with
`--with-subprocess-coverage`. Neither fix is in mutmut 3.8.0 or upstream main.

The fast lane leaves out the shell tests (`test_bin_scan.py`, `test_init.py`),
the public-surface introspection test (it sees mutmut's generated names), and
the 51-session eviction test (slow). Score is detected / total mutants, where
detected is killed plus timed out. The gap between the fast lane and the full
audit is code verified only through subprocesses. Findings and the baseline
scores are in issue #31.

## Releases

Tags are `comment-intent-guard--vX.Y.Z`. `gate.yml` pins a specific tag via
its `guard-ref` input (default `comment-intent-guard--v1.0.0`). To pick up a
new release in an installed plugin, run `claude plugin update`.

## Consumers

`tests/test_public_api.py` is a contract test over this module's public
surface. Known external consumers:

- A private downstream consumer's differential comment-guard test imports
  `find_misplaced_rationale` and `DOCSTRING_LINE_THRESHOLD` directly, and
  also matches the returned message text against the `"Docstring spans"`
  prefix - not just the symbol name.

If you change a symbol or a message prefix listed in
`tests/test_public_api.py`, check for consumers before merging.

# Contributing

## Dev setup

This is a Claude Code plugin, not a packaged Python distribution - there's
no `pip install -e .`. Install the pinned dependencies CI uses directly:

```sh
pip install ruff==0.16.5 pytest==8.3.4 pyyaml==6.0.2
```

Python 3.12 or newer (see the README's Requirements section for why).

## Running the checks

```sh
ruff check .                 # lint
pytest -q                    # test suite
shellcheck init.sh templates/pre-commit.sh bin/comment-intent-guard
```

`ruff` and `shellcheck` are what `.github/workflows/ci.yml`'s `lint` job
runs; `pytest` is what its `test` job runs, on 3.12, 3.13, and 3.14.

## Running the guard on your own diff

This repo dogfoods itself. Before opening a PR, run the guard over what
you've changed:

```sh
comment-intent-guard scan
```

CI runs the same check (`comment_intent_guard.py --base origin/main ...`)
against `comment_intent_guard.py` and its own tests as part of the `lint`
job, and the reusable `gate.yml` workflow runs it against the full diff of
every PR, checked out at the PR's own `HEAD` SHA.

## Mutation testing

Before touching `comment_intent_guard.py` or a `hooks/*.py` module, check
that your new test actually kills mutants in the code you're changing:

```sh
scripts/mutate.sh                          # fast lane, a few minutes
scripts/mutate.sh 'hooks.session_start.*'   # one module
```

See the README's Mutation testing section for what the fast lane leaves
out and what `--with-subprocess-coverage` adds.

## Pull requests

- One logical change per PR.
- CI (lint, test matrix, comment-guard-gate) must be green before merge.
- PRs merge by squash.
- If you change a symbol or message prefix listed in
  `tests/test_public_api.py`, check for the documented external consumers
  before merging - that file is a contract test over this module's public
  surface.

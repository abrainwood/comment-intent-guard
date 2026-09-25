# Contributing

## Dev setup

This is a Claude Code plugin, not a packaged Python distribution - there's
no `pip install -e .`. Install the pinned dependencies CI uses directly:

```sh
pip install ruff==0.16.5 pytest==8.3.4 pyyaml==6.0.2 pytest-xdist==3.6.1
```

Python 3.12 or newer (see the README's Requirements section for why).

## Running the checks

```sh
ruff check .                 # lint
pytest -q -n auto            # full test suite, in parallel
shellcheck init.sh templates/pre-commit.sh bin/comment-intent-guard scripts/mutate.sh
```

`ruff` and `shellcheck` are what `.github/workflows/ci.yml`'s `lint` job
runs; `pytest` is what its `test` job runs, on 3.12, 3.13, and 3.14.

## Running the guard on your own diff

This repo dogfoods itself. Before opening a PR, run the guard over what
you've changed:

```sh
comment-intent-guard scan
```

Running the bare `comment-intent-guard` command resolves to whatever
version is installed as your Claude Code plugin, not necessarily this
checkout. To check this checkout's own code, run it from the repo root
instead:

```sh
./bin/comment-intent-guard scan
```

CI runs two checks of its own. The `lint` job's "Dogfood the guard on its
own diff" step runs `comment_intent_guard.py --base origin/main` against a
fixed list - `comment_intent_guard.py`, `tests/test_comment_intent_guard.py`,
`tests/test_public_api.py`. Separately, the `comment-guard-gate` job calls
the reusable `gate.yml` workflow with `guard-ref: ${{ github.sha }}` - on a
`pull_request` event `github.sha` is the test-merge commit GitHub creates
for the run, so this pins the gate to this PR's own code rather than a
release tag. That job diffs the PR's base against `HEAD` for files matching
`gate.yml`'s default `paths` globs (`*.py *.yaml *.yml *.jinja *.j2 *.cs`)
and runs the guard over whatever it finds.

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
- PRs merge by squash - the repo only allows squash merges.
- If you change a symbol or message prefix listed in
  `tests/test_public_api.py`, check for the documented external consumers
  before merging - that file is a contract test over this module's public
  surface.

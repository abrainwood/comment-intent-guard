# Packaging the comment-intent guard as a shippable unit

Target: a person installs Claude Code on a fresh laptop, has an existing repo
that has never seen Claude, runs one install step, and from then on the guard
enforces self-documenting code automatically - in the editor loop, at commit,
and in CI.

## What exists today (inventory, 2026-09-24)

| Piece | Lives in | Shippable as-is? |
|---|---|---|
| `comment_intent_guard.py` (hook + CLI, 1128 lines, 167 tests, MIT, public) | this repo | yes |
| Hook wiring (`PreToolUse` on `Write\|Edit`) | `claude-dotfiles/settings.json`, absolute path | no - private repo, hardcoded `/Users/Andrew_1` |
| Rule text the model reads (Section B + `comments.md`) | `claude-dotfiles/skills/dev/` | no - tangled with `/dev`, private |
| Global `CLAUDE.md` bullets on comments | `claude-dotfiles/CLAUDE.md` | no - private |
| Session density state | `~/.claude/hooks/state/comment_guard.json` | hardcoded path, assumes dotfiles layout |
| Per-repo allowlist (`.comment-intent-guard.json`) | consumer repos | yes, already documented |
| CI gate job | `home-assistant-config/.github/workflows/ci.yml`, inlined | copy-paste only |
| Pre-commit hook | none for the guard (memory says exo_pool has one; not found on disk) | missing |
| Evals (Phase 0 harness, never run) | `claude-dotfiles/evals/comment-density/` | not a shipping concern |

Three consumers, three different install paths (symlink into `~/.claude/hooks`,
`cp` in CI, nothing at commit). That is the thing to collapse.

## Why not "a skill"

A skill is text the model reads when it decides the skill is relevant. The
guard's whole point is that it fires whether or not the model wants it to. A
skill alone gets the model to *know* the rule; the exo_pool PR #4 incident
(16 bright-line violations shipped with the rule in three places) is the
proof that knowing is not enforcing.

But the rule text still matters: the deny message tells the model *what*
tripped, the skill tells it *how to answer the alarm* (rename, retype, move
rationale to the PR). Ship both, with the hook as the enforcement and the
skill as the remediation guide.

## Recommendation: a Claude Code plugin, in this repo, plus a repo-init command

A plugin is the only Claude Code unit that carries hooks, skills and agents
together, installs from a public GitHub repo, and fires with no per-repo
settings edit. It is the format built for exactly "install once, applies
everywhere".

### Repo layout

```
comment-intent-guard/
  .claude-plugin/
    plugin.json            name, version, description
    marketplace.json       single-entry marketplace pointing at "./" so
                           `/plugin marketplace add abrainwood/comment-intent-guard`
                           works with no second repo
  hooks/
    hooks.json             PreToolUse Write|Edit -> python3 ${CLAUDE_PLUGIN_ROOT}/comment_intent_guard.py
                           PostToolUse Bash      -> guard --base HEAD over files git says changed (closes the heredoc gap)
                           SessionStart startup|compact -> prints the one-paragraph rule so it is
                           always in context, not only when the model decides the skill is relevant
  skills/
    self-documenting-code/
      SKILL.md             the rule (Section B "Self-documenting code" lifted verbatim)
      comments.md          the two tests + worked examples (lifted verbatim)
    comment-guard-init/
      SKILL.md             /comment-intent-guard:comment-guard-init - drops into the CURRENT repo
                           (skills/ is the current mechanism; commands/ is legacy flat markdown)
                           - .comment-intent-guard.json (empty allowlist, commented example)
                           - .githooks/pre-commit + `git config core.hooksPath .githooks`
                           - .github/workflows/comment-guard.yml (the gate job, parameterised)
                           - a CLAUDE.md stanza pointing at the skill
  templates/
    pre-commit.sh
    comment-guard.yml      reusable workflow; consumers call it with `uses:`
    comment-intent-guard.json
  comment_intent_guard.py  unchanged
  tests/                   unchanged + tests for the templates and hooks.json shape
  README.md                rewrite around the three layers
```

### The three enforcement layers, and why all three

1. **Editor loop (plugin hook).** Denies bright lines before the file is
   written; advisory findings land as context. Zero cost to the user after
   install. Gap: writes that go through `Bash` heredocs never hit `Write|Edit`.
2. **Commit (pre-commit via `core.hooksPath`).** Runs the CLI over staged
   `.py/.yaml/.yml/.jinja/.j2`. Catches heredoc writes, human edits, and any
   agent that isn't Claude. Installed per repo by `/comment-guard-init`.
3. **CI (reusable workflow).** Runs `--base <merge-base>` over the PR's changed
   files; exit 3/4 fail, exit 1 annotates. Catches `--no-verify` and
   contributors who never installed anything. Checks the guard out from this
   public repo at a pinned tag, so no token and no submodule.

Layer 1 is the fast loop; layers 2 and 3 are the backstops. The memory file on
comment density records exactly the failure each backstop exists for.

### Plugin hook: closing the heredoc gap

Today the hook only sees `Write|Edit`. In Bash-preferring sessions (this one
included) nothing fires. Hook matchers match tool names, not what a shell
command does inside, so the options are:

- **PostToolUse on `Bash`, run the CLI over `git diff --name-only` since the
  last check.** Cheap, language-aware, no regex-parsing of shell. Cannot deny
  (the write already happened) but reports as context on the very next turn,
  which is what the advisory path does anyway. Recommended.
- `Stop` hook running the same CLI over `git diff` once per turn. Cheaper
  (one run per turn, not per Bash call) but the feedback arrives after the
  model has finished, so it lands a turn late. Fallback if PostToolUse proves
  noisy.
- PreToolUse on `Bash` sniffing for heredocs into `.py` files. Fuzzy; blocking
  on a fuzzy rule trains workarounds. Rejected.

### Install story (the success criterion)

Fresh laptop, existing repo, never seen Claude:

```
npm install -g @anthropic-ai/claude-code
claude
/plugin marketplace add abrainwood/comment-intent-guard
/plugin install comment-intent-guard@comment-intent-guard   # user scope: every repo
cd ~/src/their-repo && claude
/comment-guard-init                                          # per repo, once
git add -A && git commit -m "Add comment-intent guard"       # first run of the pre-commit
```

Six lines, no dotfiles repo, no symlinks, no submodule. There is no direct
git-URL install; the single-entry `marketplace.json` in this repo is what
makes the two-step add/install work. Teams pin it via
`enabledPlugins` + `extraKnownMarketplaces` in the repo's `.claude/settings.json`
so the next teammate is prompted on first open.

### What changes in the guard script

- Default state path moves from `~/.claude/hooks/state/` to
  `~/.claude/comment-intent-guard/state.json` (the plugin root is replaced on
  update, so state cannot live under `${CLAUDE_PLUGIN_ROOT}`). Env override
  already exists (`COMMENT_INTENT_GUARD_STATE`).
- Nothing else. The CLI and hook contracts stay; `tests/test_public_api.py`
  keeps protecting the downstream import.

### What the private consumers do afterwards

- `claude-dotfiles`: delete the submodule, the symlink, the two skill files
  (Section B keeps one sentence + a pointer at the plugin skill), and the
  `settings.json` hook entry. Install the plugin like anyone else.
- `home-assistant-config`: replace the inlined `comment-guard-gate` job with
  `uses: abrainwood/comment-intent-guard/.github/workflows/gate.yml@v1`.
- Both: run `/comment-guard-init` to get the pre-commit.

## Cross-agent portability (Codex, Devin, others)

There is no open *plugin* format. There are two open pieces plus a de facto
converged hook protocol, and the design should lean on all three so the
Claude plugin becomes one thin adapter among several.

**Open standards that exist (checked 2026-09-24):**

- **Agent Skills** (agentskills.io, Anthropic-published Dec 2025). `SKILL.md`
  folder under `.agents/skills/` is read by Codex, Devin, Cursor, Gemini CLI,
  Copilot, Zed and ~30 others. This is where the rule text goes. Claude Code
  reads the same folder via the plugin's `skills/`.
- **AGENTS.md.** The always-on instruction file every agent reads. One stanza
  pointing at the skill replaces the CLAUDE.md stanza; Claude reads it too.
- **Git pre-commit + GitHub Actions.** Agent-agnostic by construction; these
  are the layers that work on an agent with no hook support at all.

**Hook protocol: converged, not standardised.** Codex and Devin both copied
the Claude Code hook contract rather than inventing one:

| | Claude Code | Codex | Devin |
|---|---|---|---|
| Config | plugin `hooks/hooks.json` | `~/.codex/hooks.json`, `<repo>/.codex/hooks.json` | `.devin/hooks.v1.json`, `~/.config/devin/config.json` |
| Events | PreToolUse, PostToolUse, SessionStart, Stop, ... | same names | same names |
| stdin | `tool_name`, `tool_input`, `session_id`, `cwd` | same | same (no `cwd`) |
| Edit tool | `Write`/`Edit`, `tool_input.file_path` + `content`/`new_string` | `apply_patch`, `tool_input.command` = the patch text; matchers `Edit`/`Write` are aliases | not documented |
| Deny | `hookSpecificOutput.permissionDecision: deny` | identical | `{"decision":"block"}`, or exit 2 |
| Context | `hookSpecificOutput.additionalContext` | identical | identical |
| Extra | - | hooks must be trusted via `/hooks` before they run | reads `.claude/` hook configs automatically |

Consequences for the guard:

1. **One script, three one-file adapters.** The guard already speaks the
   Claude payload. Add an `apply_patch` reader that extracts added lines per
   file from the patch text, and Codex is covered by the same code path.
   Devin's deny shape differs, so emit exit 2 with the reason on stderr for
   blocking - every one of the three honours that - and keep the JSON
   `additionalContext` for advisories.
2. **`init` becomes a shell script, not a Claude skill.** `init.sh --agents
   claude,codex,devin` writes the per-repo files: `.comment-intent-guard.json`,
   `.githooks/pre-commit`, the CI workflow, `AGENTS.md` stanza,
   `.agents/skills/self-documenting-code/`, and whichever of
   `.codex/hooks.json` / `.devin/hooks.v1.json` were asked for. The Claude
   plugin's `/comment-guard-init` skill just runs it.
3. **Global install differs per agent.** Claude: plugin marketplace. Codex:
   `~/.codex/hooks.json` entry pointing at a checkout of this repo, then trust
   it in `/hooks`. Devin: `~/.config/devin/config.json`. `init.sh --global`
   handles the last two; the plugin handles the first.
4. **Per-repo is the portable path.** A repo that has run `init.sh` gets the
   editor-loop hook on any of the three agents without the contributor
   installing anything globally, because all three read repo-level hook
   config. That is a stronger success criterion than the fresh-laptop one
   and costs nothing extra.

Unverified: Codex's plugin system mentions `CLAUDE_PLUGIN_ROOT` for
backward compatibility, which suggests it can load Claude-layout plugins
directly. Worth a ten-minute test before building the Codex adapter; if it
holds, adapter 1 collapses into the plugin.

## Non-goals for the first cut (decide, don't drift)

- **Languages.** Python, YAML, Jinja only. "Anyone can use it" implies
  TS/JS/Go at some point; that is a separate design (tokenizer per language)
  and the README says so up front.
- **The ratchet** (per-session density trend, `claude-dotfiles#10` piece 1).
  Substrate exists; not needed to ship.
- **Evals.** Stay in `claude-dotfiles`; they measure the model, not the guard.
- **PyPI / pipx.** A plugin already ships the file; a second distribution
  channel doubles the release surface for no gain until someone asks.

## Sources

Plugin layout, hooks and scopes: code.claude.com/docs/en/plugins-reference,
/plugins, /plugin-marketplaces, /discover-plugins, /hooks, /plugin-dependencies.
Checked 2026-09-24 against Claude Code 2.1.281.

## Open decisions

1. Plugin name: `comment-intent-guard` (matches repo) or something shorter
   like `comment-guard`? The command/skill names follow from it.
2. Versioning: plugin tags must be `comment-intent-guard--v1.0.0`
   (`claude plugin tag --push` mints them; `claude plugin update` resolves
   semver against them). The reusable CI workflow is referenced by the same
   tag. `hooks.json` needs no ref - it runs whatever the plugin root holds.
3. Whether the PostToolUse Bash backstop ships in v1 or v1.1. It is the one
   piece with no existing tests.
4. Per-repo defaults: should `/comment-guard-init` also add `ruff` `ERA`
   (commented-out code) to a Python repo's config, or stay in its lane?

## Verification plan

- Plugin loads: `claude --plugin-dir ./ ` in a scratch repo, `/hooks` lists the
  PreToolUse entry, a `Write` of a test function with a docstring is denied.
- Fresh-laptop rehearsal: new macOS user account (or a clean Docker image with
  Node + Python 3.12), the six install lines above, then the same denial.
- Pre-commit: heredoc a violating `.py`, `git commit` exits non-zero with the
  finding.
- CI: open a PR against a scratch repo that `uses:` the reusable workflow with
  one bright-line violation; the check fails with the annotation.
- Existing 167 tests stay green; new tests cover `hooks.json` shape, state
  path resolution, and each template's substitution.

# plan-anchor

A Claude Code and Codex skill that keeps plans, and the code built from them, anchored to what you actually said while planning. Facts you state are captured verbatim as numbered **anchors**, turned into typed questions for [TypeSafe's Jev](https://typesafe.ai) decision model, and enforced mechanically at two gates: once against the plan, once against the delivered work. When something drifts, the report quotes your own words back.

> **This skill requires Jev. Data leaves the machine only when you say so.** Capture rubric checks, question tuning, fixture checks, and gate runs send scoped text to `api.typesafe.ai`. They require `TYPESAFE_API_KEY` and your recorded consent, `allow_remote_judge: true` in the committed `.sc/plan-anchor/settings.yaml`; without both, the skill refuses and sends nothing. You answer once per repository; agents never write the setting. The script redacts the live key and bearer tokens from every emitted value and never writes credentials to run files.

## The problem

Over a long planning conversation the specific things you say get compressed out of an agent's context. You ask for something concrete, "copy these crates from the legacy repo as the starting point and strip the legacy-specific code", the agent writes it down, and several rounds later it quietly writes a new implementation from scratch. Nothing checks that the plan still says what you said, or that the delivered work matches the plan, so you re-state the same facts every time you re-open the plan.

## How it works

1. **Capture.** While you plan, the orchestrator watches for directives about *how* the work must be done. For each one it writes one testable requirement (the anchor `statement`), keeps your exact words as the `quote`, checks the statement against a testability rubric and existing anchors, and proposes both. Nothing is locked until you confirm. A phase needs five to fifteen anchors, not one per sentence.
2. **Record and tune independently.** Locked anchors are numbered (`ANC-001`...) and stored with provenance in `doc/plan/phase-current/anchors.json`, rendered to `anchors.md`, and given a small bead tree so their questions version alongside the work. Existing requirements (`REQ-*`) and ADRs (`ADR-*`) join the same record under their own IDs. A separate higher-reasoning tuner (Claude: Opus; Codex: Sol) derives a frozen oracle from the approved intent and anchor, then loops over Jev calls while refining question text. It never receives "make this plan pass" as an objective.
3. **Planning gate.** Each planning bead is judged against every anchor by three orthogonal Jev questions: is the anchor relevant to this bead, does the bead address it, does the bead contradict it. Answers are gated in code into one verdict per anchor, coverage is computed across beads, and you iterate until nothing is forgotten or contradicted.
4. **Development gate.** When a sprint is delivered, the same anchors are judged against the account of the work (sprint report, PR, diff summary, tests) with a fourth question: is compliance *evidenced*, not just asserted. Each satisfied anchor is paired with a deterministic check, because Jev judges text and only a diff proves the code.
5. **Report and iterate.** A failing verdict reads: `bd-42 · ANC-012 · not addressed  Anchor: The runtime crates are created by copying the legacy repo's runtime crates and deleting the legacy-specific modules. You said (planning session, Oct 9): "copy the libraries from the legacy repo as the starting point and remove the legacy-specific code" This bead does not carry the directive forward.` Each finding is triaged (plan defect, anchor defect, question defect, or Jev error), fixed where the defect is, and re-run. An oversized bead is treated as a symptom: unapproved work is removed first, then prose and ceremony, and only remaining approved work is split.

The design is documented in [docs/design/architecture-and-call-graphs.md](docs/design/architecture-and-call-graphs.md) (components, call graphs and fan-out for both gates, retry policy) and [docs/design/data-model-and-gating.md](docs/design/data-model-and-gating.md) (record schema, verdict gating, lifecycle). The original PRD is [docs/plan-anchor-prd.md](docs/plan-anchor-prd.md).

## Use cases

- **Long or multi-session planning.** You re-open a phase plan next week; the skill loads the anchors first and nothing you said has to be repeated.
- **Multi-agent delivery.** A planning agent drafts beads, dev agents implement, a quality manager reviews. The planning gate stops forgotten directives before code exists; the development gate stops the quality manager accepting work that planned the directive and then abandoned it.
- **Requirement and ADR enforcement.** Numbered requirements and decisions you already maintain are judged bead by bead with the same machinery, so "REQ-014 is satisfied somewhere in this plan" is computed, not remembered.
- **Pull request review against the plan.** Point the development gate at a PR and get, per anchor, whether the PR description shows the directive was followed and where to look to confirm it.
- **CI without a key.** Fixture answers exercise the whole pipeline offline, so the gating logic and report format are testable, and CI gates on the JSON outcome (`data.summary.pass`); a nonzero exit is reserved for tool failure.
- **Promoting decisions.** An anchor that proves durable is promoted to an ADR and keeps its ID and history.

Not for: general code review, style review, or plan hardening without anchors. It composes with plan-hardening workflows rather than replacing them.

## Installation

**0.8.0 changes how plan-anchor is installed.** The marketplace plugin `sc-plan-anchor` now exposes one skill, `plan-anchor-installer`, which installs plan-anchor into a folder you choose. The `plan-anchoring` skill and its agents run from that install, not from the plugin, and every installed file names only your tracker (`br` or `bd`).

Claude Code:

```text
/plugin marketplace add randlee/plan-anchor
/plugin install sc-plan-anchor@plan-anchor
```

Codex: `codex plugin marketplace add randlee/plan-anchor`, then open `/plugins` and install **Plan Anchor**. Cursor: in Customize, import this GitHub repository (it reads `.cursor-plugin/marketplace.json`), then install **Plan Anchor**.

Then ask the agent to install plan-anchor, or run the `plan-anchor-installer` skill. It reports the installed and available versions, asks once for any setting the folder does not record yet (the tracker, and whether plan text may be sent to TypeSafe), and runs:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/install.py" --dest <folder> --tracker br|bd --allow-remote-judge|--no-remote-judge [--target claude,codex,cursor]
```

From a checkout of this repository the same command is `uv run plugins/sc-plan-anchor/install.py ...`; `--status --dest <folder>` reports the versions without writing.

- **Destination.** Any folder: a repository, or a parent folder holding several repositories (a folder that is not a repository needs `--tracker`). Global locations are refused with `INSTALL.DEST_GLOBAL` (exit 2): the home directory, `~/.claude`, `~/.codex`, `~/.cursor`, `~/.agents` and the plugin caches under them. The install writes `<folder>/.claude/`, `.codex/` and `.cursor/` (skill under `skills/plan-anchoring/`, agents under `agents/`) and `<folder>/.sc/plan-anchor/`.
- **Which install runs.** The gates accept only the `jev_judge.py` of the nearest install, walking up from the working directory and stopping before the home directory; a copy in a global location is refused with `VALIDATION.PATH`. The nearest `.sc/plan-anchor/settings.yaml` wins, so a child repository can override a parent folder's tracker with its own file. A `br` setting over a Dolt-backed `.beads/` is still `TRACKER.MISMATCH`; a bd repository under a br parent install needs its own install, because the installed prompts name one tracker. Harnesses discover project skills from the session's directory up to the git root, so a parent-folder install is picked up by a session started in the parent folder.
- **Upgrade.** Rerun the installer (or the skill) for the folder. It replaces only the files recorded in `<folder>/.sc/plan-anchor/install-lock.json`, removes files the new version no longer ships, and refuses to overwrite modified or foreign files without `--overwrite`. `--tracker` with the other value switches trackers: it re-renders the text and updates the settings file, and does not migrate issue data. A SessionStart hook prints one line when the nearest install is older than the plugin; it writes nothing and uses no network. Claude Code runs it; Codex and Cursor plugin hook discovery is untested.

Details: the installed `references/installation-and-troubleshooting.md` (source `plugins/sc-plan-anchor/install/templates/skills/plan-anchoring/references/installation-and-troubleshooting.md.j2`).

Hermes distribution is likewise deferred; it has no marketplace manifest and this package has not been landed in its registry.

| Need | For | Notes |
| --- | --- | --- |
| `python3` 3.9+ | everything | The scripts are standard-library only, except `anchor_tracker.py` and `plan_anchor_settings.py` (and `jev_judge.py` reading the settings file before a live call) |
| PyYAML 5.1+ | anchor tracker selection, live Jev calls | `python3 -m pip install pyyaml`; reads `.sc/plan-anchor/settings.yaml` |
| `br` ([beads_rust](https://github.com/Dicklesworthstone/beads_rust)) 0.7.x, or `bd` ([beads](https://github.com/steveyegge/beads)) 1.x with an existing Dolt-backed `.beads/` | the bead tree and reading beads | `anchor_tracker.py resolve` selects one (see installation-and-troubleshooting); agents use it read-only; the skill creates anchor beads and posts comments from the main session |
| `TYPESAFE_API_KEY` | the Jev-backed workflow | Get a key at typesafe.ai. Set it in the environment for local sessions and for cloud or remote agents (platform secrets); never commit it |
| `allow_remote_judge: true` in `.sc/plan-anchor/settings.yaml` | every live Jev operation | Your one-time answer to whether scoped plan text may be sent to TypeSafe: `install.py --allow-remote-judge` (or `--no-remote-judge`), or `python3 .claude/skills/plan-anchoring/scripts/plan_anchor_settings.py set allow_remote_judge true\|false` (in the install folder); commit the file. Absent or `false`: live calls are refused |

Offline dry runs, deterministic lint/shape/render commands, fixture-answer tests, and record maintenance need neither value. They support development and inspection; they do not replace the live rubric, tuning, and gate judgments required by the skill.

## Cloud and remote agents

Plan-anchor is **installed per repository** (not globally): each repo carries its own tracker choice, Jev consent, rendered skill text, and gate agents. Commit and push the install with the repo so every clone — including workers that run away from your laptop — sees the same configuration.

That model applies to **any cloud or remote agent** that checks out the repository and runs tools against it (hosted IDE agents, cloud coding agents, CI agents with an LLM step, self-hosted workers, and similar). Nothing here is specific to one vendor; the checklist is the same wherever the agent's environment is a git checkout plus a shell.

**What travels in git (per repo).**

- `.sc/plan-anchor/settings.yaml` — `anchor_tracker` (`br` or `bd`) and `allow_remote_judge` (policy, not a secret).
- `.sc/plan-anchor/install-lock.json` — installed version and owned file list.
- The harness tree you installed: `.claude/`, `.codex/`, and/or `.cursor/` (`skills/plan-anchoring/`, `agents/anchor-*.md`).
- Anchors, plans, and run history under your repo (for example `doc/plan/.../anchors.json`).

**What does not go in git.**

- `TYPESAFE_API_KEY` — the only secret or credential the scripts read; never commit it. Configure it in the **remote environment** (platform secrets, worker env, or your host's secret injection). It must be present when `jev_judge.py` makes a live call.

**Live Jev in cloud (same gate as local).**

Both must be true before any live rubric, tuning, fixture check, or gate run sends text to TypeSafe:

1. `TYPESAFE_API_KEY` is set in the agent's environment.
2. The repository's committed settings file sets `allow_remote_judge: true`.

If either is missing, the scripts fail closed (`AUTH.CREDENTIALS` or `POLICY.REMOTE_JUDGE_DISABLED`) and send nothing. Consent is **repository policy** (committed once per repo); the key is **runtime credentials** (injected per environment). Offline commands (`--dry-run`, `--answers-file`, lint, render) still work without the key.

**Runtime the worker must provide.**

- A checkout that includes the vendored install above (gates walk up from the working directory, stopping before the home directory, to the nearest `<D>/.claude|.codex|.cursor/skills/plan-anchoring/scripts/jev_judge.py` whose `<D>/.sc/plan-anchor/install-lock.json` lists that script; a hand-copied, lock-less, `.agents/`, global or plugin-cache copy fails with `VALIDATION.PATH`).
- `python3` 3.9+, `jq`, PyYAML 5.1+, and the anchor tracker CLI named in settings (`br` or `bd`).
- Outbound HTTPS to the Jev endpoint (see the installed `references/jev-api.md`).

**Operational notes.**

- Install into the **repository root** (or a parent folder you actually open as the workspace) so skill discovery and nearest-install trust match where the agent runs. A cloud or remote agent checks out only the repository, so it needs the install committed inside the repository itself; a parent-folder install is not in its checkout.
- Parent-folder installs and per-repo overrides follow the same rules as on a local machine: nearest `.sc/plan-anchor/settings.yaml` wins; tracker must match each repo's `.beads/` layout. A parent-folder install does not travel with a clone, so cloud and remote agents need the install committed inside the repository itself.
- Gate subagents are the **installed** agent definitions under `.claude/agents/`, `.codex/agents/`, or `.cursor/agents/` in that tree — not the marketplace plugin bundle.

For PATH, GUI-launched hosts, and Codex shell policy around `TYPESAFE_API_KEY`, see the installed `references/installation-and-troubleshooting.md`.

## Quick start

```bash
S=.claude/skills/plan-anchoring/scripts/jev_judge.py   # in the install folder (or .codex/, .cursor/)
A=doc/plan/phase-current/anchors.json

# lock the first anchor (creates anchors.json) after the live Jev rubric, then render the human view
python3 $S add --rubric --anchors $A --quote "copy the libraries from the legacy repo as the starting point and remove the legacy-specific code" \
  --statement "The runtime crates are created by copying the legacy repo's runtime crates and deleting the legacy-specific modules; no runtime crate is written from scratch." \
  --stated-by "<name>" --context "planning session" --summary "Runtime crates copied, not rewritten" \
  --scope "any bead that creates the runtime crates" --status locked
python3 $S validate --anchors $A && python3 $S render --anchors $A

# see exactly what a planning-gate request would send, without a key
python3 $S judge --anchors $A --gate plan --all --item-id bd-42 --item-file /tmp/bd-42.txt --dry-run

# run the planning gate for a bead (needs the key and `allow_remote_judge: true`), then read the report
python3 $S judge --anchors $A --gate plan --all --item-id bd-42 --item-file /tmp/bd-42.txt
python3 $S report --run doc/plan/phase-current/anchor-runs/<run>.json --format md

# coverage across all judged beads
python3 $S coverage --runs doc/plan/phase-current/anchor-runs --gate plan --format md
```

In a Claude Code, Codex, or Cursor session the installed skill does this for you: say "anchor this" or "lock this" while planning, then "run the planning gate on the sprint 2 beads" or "review sprint 2 against the anchors". Claude Code invokes Sonnet gate agents and an Opus tuner from the install folder's `.claude/agents/`; Codex invokes Luna gate agents and a Sol tuner from `.codex/agents/`. Claude uses the Agent tool, never the Task tool. Cursor invokes Composer gate agents and a Grok-high tuner from `.cursor/agents/` through the Task tool, with no model override.

## What you get back

| Verdict | Meaning | Planning gate | Development gate |
| --- | --- | --- | --- |
| `contradicted` | The item proposes or did what the anchor rules out | Change the approach or escalate | Block acceptance |
| `not_addressed` | The item is silent on the directive | Add the directive's specific content | Block until the work shows it |
| `asserted_only` | Compliance is claimed with nothing checkable | n/a | Get evidence or run the deterministic check |
| `underspecified` | Jev was not confident | Sharpen the anchor's scope or the bead | Usually a vague report |
| `satisfied` | The directive is carried forward or followed | Nothing | Run the paired deterministic check |
| `not_applicable` | The anchor does not govern this item | Nothing | Nothing |
| `excluded` | Not asked: the anchor's `exclude` list names this item, with a reason | Nothing | Nothing |

Every run is stored in `anchor-runs/` so edits can be diffed against the last run. Coverage, counts and "satisfied anywhere" are computed from run files, never asked of Jev. Verdicts are gate outcomes, but before editing on one, the caller re-reads the exact text that was sent and says so in the report if Jev looks wrong.

## Repository layout

```
docs/
├── plan-anchor-prd.md                     product requirements
└── design/                                architecture, call graphs, data model, gating
.claude-plugin/marketplace.json            Claude marketplace catalog
.agents/plugins/marketplace.json           Codex repository marketplace catalog
.cursor-plugin/marketplace.json            Cursor marketplace catalog
plugins/sc-plan-anchor/
├── plugin.json                            portable Agent Plugins manifest
├── .claude-plugin/plugin.json             Claude manifest
├── .codex-plugin/plugin.json              Codex compatibility/presentation overlay
├── .cursor-plugin/plugin.json             Cursor manifest
├── skills/plan-anchor-installer/SKILL.md  the only skill the plugin exposes
├── hooks/                                 SessionStart version check (check_install.py)
├── install.py                             the installer
└── install/
    ├── templates/skills/plan-anchoring/   SKILL.md, references (sc-compose templates), scripts, assets
    ├── templates/agents/                  agent bodies (sc-compose templates)
    ├── harness/{claude,codex,cursor}/     agent frontmatter and registry per harness
    └── legacy-owned.json                  bytes of earlier releases, for pre-lock upgrades
```

### The script

`jev_judge.py` owns everything that must not be left to a language model.

| Subcommand | Does |
| --- | --- |
| `add`, `update`, `retire`, `promote` | Maintain the anchor record; `add` allocates the next `ANC-NNN`, lints the statement and refuses near-duplicates |
| `lint`, `rubric`, `dedupe`, `shape` | Testability lint (deterministic); Jev-judged testability rubric; duplicate detection (lexical, optionally Jev); per-bead size and ceremony metrics |
| `validate`, `render` | Check the record; write `anchors.md` |
| `set-beads` | Record the anchor tree's bead IDs |
| `compose-item` | Turn `bd show --json` output into the labelled item text the agents send |
| `agent-preflight` | Canonicalize and confine agent-provided paths to the repository; validate IDs and PR numbers before any read or upload |
| `judge` | One Jev request per anchor for one item; gating; writes the run file. Exit 0 when the run completed (outcome in `data.summary.pass`), 2 fatal; the only exit codes are 0, 2 and 130 |
| `check-fixtures` | Judge each anchor's pass and fail fixture sentences and confirm they land as expected |
| `report`, `coverage`, `diff` | Render a run; anchors × items matrix; verdict and composed-item size changes between runs |

Planning-gate requests stay under 24,000 bytes: fitting beads are sent whole, and only oversized beads have the fewest eligible code blocks reduced before `PLAN.TOO_LARGE`. Development evidence can be shortened from the tail and halved on a context response down to 2,000 characters. Transient API failures get three attempts with backoff before an anchor is marked `error`; credential and consent failures abort immediately and are never retried.

## Development

```bash
python3 -m unittest discover -s tests/sc-plan-anchor -v
```

Maintainer tests live outside the marketplace plugin so plugin consumers do not
redistribute or inherit this repository's test suite. They use fixture answers
and a stub transport; they cover ID allocation, gating, overrides, retries and
context shortening, response validation, report format, coverage and diffs,
not Jev's judgment. CI runs them on Linux, macOS and Windows with Python 3.9
and the latest 3.x, once against the br render of the scripts and once against the bd render
(CONTRIBUTING.md). The scripts are templates, so a smoke run installs first (it needs the
sc-compose wheel) and then runs the installed copy with no key (exits 0 with `data.summary.pass: false`,
because the example gate fails by design):

```bash
D=$(mktemp -d) && python3 plugins/sc-plan-anchor/install.py --dest "$D" --tracker br --target claude --no-remote-judge
S=$D/.claude/skills/plan-anchoring/scripts/jev_judge.py
X=$D/.claude/skills/plan-anchoring/assets/examples
python3 $S judge --anchors $X/anchors.example.json --gate plan --all --item-id smoke --item-file README.md \
  --answers-file $X/answers.fixture.json --out /tmp/anchor-smoke.json && python3 $S report --run /tmp/anchor-smoke.json --format md
```

## Status

Revision 0.4 builds on the first real multi-sprint use and 245 live Jev requests ([docs/experiments/2026-10-10-phase-h-jev-experiments.md](docs/experiments/2026-10-10-phase-h-jev-experiments.md)). It adds the independent Opus/Sol tuner, harness-specific agents, repository-confined inputs, credential redaction, and remediation growth checks. The measured 0.3 findings remain the basis for the gate design:

- Anchors are testable requirements with the user's words kept as a `quote`; a testability lint, a Jev-judged rubric and deduplication guard capture, because the first live use minted untestable, duplicated anchors from raw sentences.
- Anchor kinds: prohibitions are judged on contradiction only and structural anchors by their deterministic check, because the generic "addressed" question failed both on every bead.
- The planning gate judges a bead's description and acceptance criteria; a planted contradiction scored 0.79 near the top of a bead and 0.46 when buried 28k characters into its design. An oversized bead is a symptom, triaged as unapproved work, then prose and ceremony, then split last; `shape` measures it first.
- Per-anchor question tuning is an independent higher-reasoning agent's job. It freezes an intent-derived oracle before its first Jev call and iterates wording without access to a plan-pass objective.
- Near-threshold cells are re-asked once because run-to-run noise flipped one cell in six; every cell reports its leaning.

The offline suite runs on Linux, macOS and Windows in CI. The repository is a Claude, Codex, and Cursor marketplace containing the `sc-plan-anchor` plugin; the plugin ships the installer, which renders the shared skill body and separate harness-owned agent definitions into a folder.

## Versioning

`VERSION` is the single source of truth: `SKILL.md` metadata, every reference, every harness's agents and registries, and all plugin and marketplace manifests equal it exactly. `scripts/check_version_sync.py` and `tests/sc-plan-anchor/test_version_ssot.py` run in CI and fail on identity, path, version, or changelog drift.

## License

MIT. See [LICENSE](LICENSE).

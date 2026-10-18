# Contributing

plan-anchoring is a general-purpose skill. Anyone, human or agent, may propose an upgrade. These rules keep it auditable and keep it general.

## What a good change looks like

- **One aspect per pull request.** The skill is a table of contents (`SKILL.md`) with one reference per aspect. Change the reference that owns the aspect; add a new reference only for a new aspect, and list it in `SKILL.md`.
- **General wording.** No project names, people, issue numbers, crate names or team-specific process. Use neutral examples (the "legacy repo" example is the house one). `grep -rniE "<your repo>|<your team>" plugins/sc-plan-anchor/` must return nothing.
- **Concise.** One idea per sentence. State a rule once, where it is defined; elsewhere cite it. Justify numbers from `references/measured-behaviour.md`; a behaviour change that rests on how Jev judges comes with measurements (see `docs/experiments/` for the protocol).
- **Script and docs together.** A new flag, field, verdict, error code or exit code lands with its reference text, its agent text if an agent uses it, and a test. Existing names are never renamed or removed in a patch; add only.
- **Prompts are templates.** Every installed prompt (the skill, its references and assets templates, the agent bodies) has its source in `plugins/sc-plan-anchor/install/templates/` (sc-compose, `tracker` = `br` or `bd`; there is no neutral render) and is installed only by `install.py`. Agent frontmatter and registries live in `install/harness/<target>/`. The plugin itself exposes only `skills/plan-anchor-installer/`. After a release, run `python3 scripts/gen_install_data.py` to refresh `install/legacy-owned.json` (the byte list of earlier releases).
- **Tests green.** `python3 -m unittest discover -s tests/sc-plan-anchor` and `python3 scripts/check_version_sync.py --base origin/main` both pass before you open the PR.
- **Never a secret.** No keys, no live run output containing private plan text. Fixture answers and dry runs are how tests touch Jev.

## Versioning

`VERSION` at the repo root is the single source of truth. Every version declared in shipped metadata equals it exactly: the plugin manifests, the marketplace manifests that carry a version, `SKILL.md`, each `references/*.md`, each harness agent, and each `registry.yaml` entry. Nothing has its own patch line.

A PR that changes shipped content (anything under `plugins/` or a marketplace manifest) raises `VERSION` (patch for a fix or addition, minor for a release-worthy change), sets every version above to it, and adds a `## X.Y.Z — date` section to `CHANGELOG.md`. A PR that touches only tests, `scripts/` or `docs/` needs no bump.

`scripts/check_version_sync.py` enforces this: by default it checks that every declaration it finds by glob equals `VERSION` and that the changelog has the entry; with `--base <ref>` (CI runs it on every pull request) it also checks that a PR changing shipped content raised `VERSION` and changed `CHANGELOG.md`. `tests/sc-plan-anchor/test_version_ssot.py` runs the same discovery in the suite. Template `metadata.version` and `schema_version` values are wire-contract versions pinned by the JSON schemas, not release versions.

## Proposing a change as an agent

1. Read `SKILL.md`, then only the reference you intend to change.
2. Make the change; if it touches shipped content, raise `VERSION`, set every version to it, and add the changelog section.
3. Run the tests, the version check with `--base`, and the general-wording grep.
4. Open the PR with: what changed, which aspect, the evidence (test names, measured cells), and the before and after `VERSION`.

## What not to propose

- Repo-specific anchors, question overrides, or examples: those live in the consuming repository's `anchors.json` and question beads, not in the skill.
- Raising a size cap, lowering a threshold, or changing default question wording without a measurement that shows the effect.
- A rename of a flag, field, verdict or error code. Deprecate by adding the new name and keeping the old.

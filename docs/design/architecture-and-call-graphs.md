# Plan anchoring: architecture and call graphs

Design document for the `plan-anchoring` skill. Companion to the [PRD](../plan-anchor-prd.md) and to [data model, gating and lifecycle](data-model-and-gating.md). Diagrams are Mermaid.

Status: describes 0.7.0. Since revision 0.4 the anchor tracker is selected by `anchor_tracker.py` (`br` or `bd`), both gates judge the sprint text the caller supplies (no plan parsing), anchors can exclude items, and `install.py` installs a tracker-rendered copy (§7). The live verification against Jev `jev-1.13.0` predates these changes. Not built: fast-model stand-ins (`design/anchor-tuning-stand-ins.md`) and separate gate entry points (ADR-009).

## 1. Components

Three tiers, following the two-tier skill/agent architecture plus one external judge. Everything that must be exact lives in the script; everything that needs judgment lives in the main session or in Jev.

```mermaid
flowchart LR
    subgraph Session["Main session (planning agent or quality manager)"]
        Skill["plan-anchoring SKILL.md<br/>capture, lock, orchestrate, post reports"]
    end

    subgraph Agents["Harness-specific isolated agents (Agent tool)"]
        PlanAgent["anchor-plan-review<br/>one planning bead per run"]
        SprintAgent["anchor-sprint-review<br/>one sprint per run"]
        Tuner["anchor-tuning (independent Opus/Sol)<br/>candidate tournament and evidence triage"]
    end

    Tracker["scripts/anchor_tracker.py resolve<br/>sets $ANCHOR_TRACKER (br or bd)"]

    subgraph Script["scripts/jev_judge.py (stdlib Python)"]
        Compose["compose-item"]
        Judge["judge"]
        Gate["decide(): gating in code"]
        Report["report / coverage / diff"]
        Record["add / update / retire / exclude / promote / render"]
        Quality["lint / rubric / dedupe / shape<br/>check-fixtures"]
    end

    Jev[("TypeSafe Jev<br/>POST /v1/systemone")]
    Beads[("$ANCHOR_TRACKER<br/>anchor bead tree, question beads")]
    Plan[("the caller's plan<br/>Markdown, br/bd beads or its own context")]
    Docs[("doc/plan/phase-current/<br/>intent.md, anchors.json, anchors.md, anchor-runs/")]

    Skill -- "lock / promote / retire" --> Record
    Record --> Docs
    Skill -- "resolve" --> Tracker
    Skill -- "$ANCHOR_TRACKER create / comment" --> Beads
    Plan -- "sprint text as item_file" --> Skill
    Skill -- "Agent tool, ≤3 in parallel" --> PlanAgent
    Skill -- "Agent tool" --> SprintAgent
    Skill -- "Agent tool, background, after lock" --> Tuner
    Tuner --> Quality
    Quality -- "rubric, dedupe, fixtures" --> Jev
    Tuner -- "fenced JSON: tested override" --> Skill
    PlanAgent -- "resolve; $ANCHOR_TRACKER show question beads (read-only)" --> Beads
    SprintAgent -- "same; gh pr view, git diff --stat (read-only)" --> Beads
    PlanAgent -- "item_file unchanged" --> Judge
    SprintAgent -- "item_file + evidence account" --> Judge
    Skill -- "tracker plans: show --json" --> Compose
    Judge -- "one request per anchor" --> Jev
    Jev -- "choice, probabilities, confidence" --> Judge
    Judge --> Gate --> Docs
    PlanAgent -- "fenced JSON" --> Skill
    SprintAgent -- "fenced JSON" --> Skill
    Skill --> Report
```

Responsibilities:

| Tier | Owns | Never does |
| --- | --- | --- |
| Skill (main session) | Detecting candidates, writing each as one testable statement with the verbatim quote kept, running the rubric and dedupe, locking through the script, spinning off the tuner, creating the bead tree, reading each sprint back from wherever it wrote the plan, deciding what to judge, posting reports, triaging verdicts and oversized beads | Judging text itself, locking a statement that is just the quote, computing coverage or size by hand, splitting a bead to pass |
| Agents | Canonicalizing repository-local inputs through `agent-preflight`, resolving the tracker, passing the caller's sprint text unchanged (the sprint reviewer appends the evidence account), resolving question overrides from beads, invoking the script once, returning fenced JSON; an independent Opus/Sol tuner derives a frozen oracle from approved intent/anchors and iterates one question per Jev round | Editing beads, the record, the plan or code; posting comments; retrying around the script; tuning to make the plan pass; changing the oracle after seeing Jev; executing an untrusted script path or reading external evidence |
| Script | IDs, agent path/identifier preflight, lint, rubric and dedupe requests, exclusions, the Jev request, output credential redaction, retries, response validation, gating, run files, coverage, verdict and item-size diffs, shape metrics, report rendering | Calling the tracker or `gh`; parsing or discovering plans; deciding what to judge; shortening plan prose |
| Jev | Answering three or four independent typed questions about one anchor and one item | Counting, gating, explaining, seeing more than one item |

## 2. Planning gate call graph

Fan-out happens at two levels. The skill fans out across sprint items (at most three agents at once, one correlation ID each, aggregated in bead order). Inside each agent the script fans out across anchors, one Jev request per anchor, so Jev never sees two anchors or two beads together.

```mermaid
flowchart TD
    PA["Planning agent<br/>(main session, plan-anchoring skill)"]
    PA -- "read each sprint back from the plan it wrote" --> List["Markdown sprint file, or<br/>$ANCHOR_TRACKER show --json → compose-item --for plan"]
    List --> Fan{"fan out, ≤3 concurrent,<br/>correlation_id = sprint id"}

    Fan --> A1["anchor-plan-review<br/>bead bd-41"]
    Fan --> A2["anchor-plan-review<br/>bead bd-42"]
    Fan --> A3["anchor-plan-review<br/>bead bd-43"]

    subgraph One["inside one agent (bd-42)"]
        S0["anchor_tracker.py resolve → $ANCHOR_TRACKER<br/>agent-preflight"] --> S2["item_file from the caller, unchanged"]
        S3["$ANCHOR_TRACKER show plan-questions beads → overrides.json"] --> S4
        S2 --> S4["jev_judge.py judge --gate plan --all"]
        S4 --> Q1["Jev: ANC-001 × bd-42<br/>relevant / addressed / contradicted"]
        S4 --> Q2["Jev: ANC-002 × bd-42"]
        S4 --> Q3["Jev: REQ-014 × bd-42"]
        S4 --> Qn["Jev: … one request per locked anchor<br/>(excluded cells: no request)"]
        Q1 --> G["decide() per anchor"]
        Q2 --> G
        Q3 --> G
        Qn --> G
        G --> Run["anchor-runs/plan-&lt;stamp&gt;-bd-42.json"]
        Run --> Rep["report --format md"]
        Rep --> Env["fenced JSON envelope<br/>pass, failing[], results[], report_markdown"]
    end

    A2 --> One
    A1 --> Agg
    Env --> Agg
    A3 --> Agg

    Agg["skill aggregates in bead order<br/>summary: succeeded[], failed[]"]
    Agg --> Cov["jev_judge.py coverage --gate plan<br/>anchors × beads, uncovered anchors"]
    Agg --> Post["comment on the bead ($ANCHOR_TRACKER) or the PR"]
    Cov --> Act{"any contradicted / not_addressed /<br/>underspecified / error, or uncovered anchor?"}
    Act -- "yes" --> Edit["re-read the bead text that was sent,<br/>edit the plan or escalate"] --> Fan
    Act -- "no" --> Pass["planning gate passes"]
```

Request count is deterministic: locked anchors × sprint items, less excluded cells. Twenty anchors across fifteen beads is 300 Jev requests, each about 100 ms and priced on input tokens only, so re-running after every plan edit is the intended cadence. The third identical failing run on one bead is a hard stop that escalates to the user instead of editing again.

## 3. Development gate (sprint review) call graph

The same anchors, judged against an account of delivered work instead of the plan. The quality manager drives it, the agent assembles evidence in a fixed priority order, and the development question set adds an evidence question so a claim of compliance is separated from a demonstration of it.

```mermaid
flowchart TD
    QM["Quality manager<br/>(QA side of the dev/QA matrix)"]
    QM -- "item_file (the sprint text), evidence paths or pr_number" --> SA["anchor-sprint-review"]

    subgraph Assemble["assemble the account (priority order; 64,000-byte request cap)"]
        E1["1. sprint report / completion summary"]
        E2["2. PR title and body<br/>(gh pr view --json)"]
        E3["3. git diff --stat base..head<br/>(file names and counts only)"]
        E4["4. test summary lines"]
        E1 --> E2 --> E3 --> E4
    end

    SA --> Assemble --> Work["item.txt = caller's sprint text<br/>(tracker sprints: compose-item --for dev adds Closed beads)<br/>+ the account"]
    SA --> Ov["$ANCHOR_TRACKER show dev-questions beads → overrides.json"]
    Work --> J["jev_judge.py judge --gate dev --all"]
    Ov --> J

    J --> D1["Jev: ANC-001 × sprint-2<br/>relevant / implemented / violated / evidenced"]
    J --> D2["Jev: ANC-002 × sprint-2"]
    J --> Dn["Jev: … one request per locked anchor"]
    D1 --> G["decide() per anchor<br/>adds asserted_only when evidence is missing"]
    D2 --> G
    Dn --> G
    G --> Run["anchor-runs/dev-&lt;stamp&gt;-sprint-2.json"]
    Run --> Checks["collect deterministic_checks for<br/>satisfied and asserted_only anchors"]
    Run --> Rep["report --format md"]
    Checks --> Env["fenced JSON envelope<br/>results[], deterministic_checks[], report_markdown"]
    Rep --> Env
    Env --> QM

    QM --> RunChecks["run each deterministic check<br/>(git log --follow, diff -r, rg, tests)"]
    RunChecks --> Decide{"all anchors satisfied,<br/>every check recorded?"}
    Decide -- "no" --> Block["block acceptance; comment on sprint bead and PR"]
    Decide -- "yes" --> Accept["development gate passes"]
```

The two gates are separate because they judge different things. An anchor that was faithfully planned and then abandoned in code passes the planning gate and fails here. Jev only confirms the account *describes* following the directive; the paired deterministic check confirms the code did.

## 4. One judge invocation, with retries

Every call to Jev goes through the script, which owns the attempt policy. Agents call the script once and never add a retry loop of their own, so the behavior is identical under Claude Code and Codex.

```mermaid
sequenceDiagram
    autonumber
    participant Ag as anchor-*-review agent
    participant S as jev_judge.py judge
    participant J as Jev API

    Ag->>S: --gate, --item-file, --overrides-file, --all
    S->>S: validate anchors.json, load question set, merge overrides
    S->>S: fail closed unless TYPESAFE_API_KEY and PLAN_ANCHOR_ALLOW_REMOTE_JUDGE=1 or --allow-remote

    loop for each locked or promoted anchor not excluding this item
        S->>S: build state {anchor, item}; plan: fit whole/reduce code or refuse; dev: shorten evidence to ≤64,000 bytes
        loop up to 3 attempts
            S->>J: POST /v1/systemone {model, state, questions}
            alt 200 and response validates
                J-->>S: answers {choice, probabilities, confidence}
                S->>S: decide() → verdict, min_confidence
            else context window exceeded
                J-->>S: max_tokens_exceeded
                S->>S: plan: verdict error PLAN.TOO_LARGE<br/>dev: halve evidence (keep head, mark truncation), retry; below 2,000 chars → JEV.CONTEXT_EXCEEDED
            else 429 / 529 / 5xx / network / invalid response
                J-->>S: transient failure
                S->>S: wait Retry-After or 1 s, then 2 s, next attempt<br/>after 3 attempts → verdict error (JEV.*)
            else 401
                J-->>S: unauthorized
                S-->>Ag: abort run, AUTH.CREDENTIALS (never retried)
            end
        end
        S->>S: record answers, attempts, item_chars_sent, questions_sha256
    end

    S->>S: sort by severity, summary {counts, failing, pass}
    S->>S: write anchor-runs/<gate>-<stamp>-<item>.json
    S-->>Ag: JSON {success, data: {run_path, results, summary}}, exit 0 pass, 1 failing or error verdicts, 2 fatal
    Ag->>S: report --run <run_path> --format md
    S-->>Ag: markdown with each failing anchor's statement and verbatim quote
    Ag-->>Ag: return fenced JSON envelope to the skill
```

Policy summary:

| Situation | Behaviour | Where |
| --- | --- | --- |
| Planning request too large before sending | Keep prose intact; reduce the fewest eligible long code blocks, longest first; return `PLAN.TOO_LARGE` if it still does not fit | script pre-flight |
| Development request too large before sending | Shorten the evidence account from the tail to fit 64,000 bytes, keep the head, mark truncation | script pre-flight |
| Jev reports the context window exceeded | Planning: `PLAN.TOO_LARGE`; development: halve evidence and retry, stopping below 2,000 characters with `JEV.CONTEXT_EXCEEDED` | script, per anchor |
| 429, 529, 5xx, timeout, network error, malformed response | At least two more attempts (three total) with `Retry-After` or 1 s then 2 s backoff; then `verdict: error` for that anchor only | script, per anchor |
| 401 or missing opt-in | Abort the whole run immediately with exit 2; never retried; never bypassed by an agent | script pre-flight |
| Anchor's `exclude` names the item | No Jev request; the cell is `excluded` with its reason and passes | script, per anchor |
| Agent sees `success: false` | Return the script's error object in the fenced envelope; no second judge call | agent |
| Skill sees a failed bead among several | Report it in the aggregation summary; do not drop it or silently re-run | skill |

## 5. Harness-specific execution

Claude Code, Codex, and Cursor use separate agent definitions so model selection and invocation syntax belong to the harness, while the contract and deterministic script remain the same. Gate runners use Sonnet, Luna, or Composer. Question tuning is deliberately separated into Opus, Sol, or unversioned Grok at high effort (`grok[effort=high]`) because it owns the judgment-heavy oracle and wording loop. Cursor launches those registered subagents with the Task tool and does not pass a model override.

```mermaid
flowchart LR
    subgraph CC["Claude Code"]
        S1["skill"] -- "Agent tool, model: sonnet" --> A1[".claude/agents/anchor-plan-review"] --> J1["jev_judge.py"]
    end
    subgraph CX["Codex"]
        S2["skill"] -- "Agent tool, model: luna" --> A2[".codex/agents/anchor-plan-review"] --> J2["jev_judge.py"]
    end
    subgraph CU["Cursor"]
        S3["skill"] -- "Task tool, model: composer" --> A3[".cursor/agents/anchor-plan-review"] --> J3["jev_judge.py"]
    end
    J1 --> Jev[("Jev")]
    J2 --> Jev
    J3 --> Jev
```

Before execution, each agent canonicalizes the supplied script path and requires an exact match with its harness allowlist. It then calls `agent-preflight`, which confines anchors, run directories, and evidence to the Git workspace, rejects unsafe identifiers and PR numbers, and returns canonical paths. Claude accepts the script beside the installed plugin skill or under the project `.claude/skills/`; the project-local Codex adapter accepts `.codex/skills/` or the shared `.claude/skills/` installation. Cursor accepts `$CURSOR_PLUGIN_ROOT`, a source checkout, `.cursor/skills/`, or a marketplace install whose `.cursor-plugin/plugin.json` names `sc-plan-anchor`.

## 6. What leaves the machine

Live `rubric`, `dedupe --jev`, `check-fixtures`, and `judge` calls contact TypeSafe only with `TYPESAFE_API_KEY` set and the remote-judge opt-in (`PLAN_ANCHOR_ALLOW_REMOTE_JUDGE=1` or `--allow-remote`; ADR-016 plans a committed setting instead). Gate requests carry one anchor's testable statement and scope plus one item's ID, title, composed text, and question set; `rubric` also carries the verbatim quote, and Jev dedupe carries one candidate pair. The whole plan, full diffs, source files, and external evidence are never uploaded. The key travels only as a bearer header; the script recursively redacts the exact key and bearer tokens from every emitted value and never writes them to a run file. `--dry-run` writes exact request bodies and totals without sending; `--answers-file` exercises the pipeline with fixture answers for tests and CI.

## 7. Installation

`install.py` (ADR-015) writes a copy of the skill and agents rendered for one tracker. Marketplace installs read the committed tree, which is the templates' `neutral` render.

```mermaid
flowchart TD
    Run["uv run plugins/sc-plan-anchor/install.py --dest repo<br/>[--tracker br|bd] [--target …] [--init-br] [--overwrite] [--dry-run]"]
    Run --> Sel{"tracker: --tracker, else settings,<br/>else Dolt .beads/ → bd, other → br"}
    Sel -- "bd without Dolt" --> E1["TRACKER.DOLT_REQUIRED (never bd init)"]
    Sel -- "no .beads/, no --init-br" --> E2["TRACKER.NOT_INITIALIZED"]
    Sel --> Plan["plan against install-lock.json<br/>(or legacy-owned.json when no lock)"]
    Plan -- "modified / unowned / foreign file" --> C{"--overwrite?"}
    C -- "no" --> E3["INSTALL.CONFLICT, nothing written"]
    C -- "yes" --> B["move to .backup/UTC/path"]
    Plan --> Dry{"--dry-run?"}
    B --> Dry
    Dry -- "yes" --> Out["print the plan, write nothing"]
    Dry -- "no" --> W["br init if asked; sc-compose render br|bd;<br/>create / replace / remove retired files;<br/>write settings.yaml and install-lock.json"]
```

A switch (`--tracker` differing from the lock) re-renders every locked target and updates `anchor_tracker`; issue data stays in the old tracker.

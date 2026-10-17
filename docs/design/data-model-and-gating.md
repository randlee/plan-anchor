# Plan anchoring: data model, verdict gating and lifecycle

Companion to [architecture and call graphs](architecture-and-call-graphs.md). Covers what is stored, how independent Jev answers become one verdict, and how an anchor moves through its life.

## 1. Artifacts

```mermaid
flowchart LR
    subgraph Plan["doc/plan/phase-current/ (git)"]
        Intent["intent.md<br/>one page, frames everything, never judged"]
        Rec["anchors.json<br/>record of truth, script-edited"]
        Md["anchors.md<br/>rendered view, never hand-edited"]
        Runs["anchor-runs/*.json<br/>one file per gate run"]
    end
    subgraph Beads["beads (bd)"]
        AB["anchor bead (type decision)<br/>description = testable statement, notes = verbatim quote"]
        PQ["plan-questions child<br/>fenced JSON overrides or {}"]
        DQ["dev-questions child<br/>fenced JSON overrides or {}"]
        PB["planning beads"]
        SB["sprint epic + children"]
    end
    subgraph SkillAssets["skill assets"]
        QP["assets/questions/plan.json"]
        QD["assets/questions/dev.json"]
    end
    Rec -- "render" --> Md
    Rec -- "beads.anchor / plan_questions / dev_questions" --> AB
    AB --> PQ
    AB --> DQ
    QP -- "defaults" --> PQ
    QD -- "defaults" --> DQ
    PB -- "item text" --> Runs
    SB -- "evidence account" --> Runs
    Rec -- "statement, scope, provenance" --> Runs
```

The record is the single place to look: it holds every anchor and points at its beads. Beads point back only through labels (`anchor:ANC-012`). Runs copy the statement and provenance they judged, so an old run is self-describing even after the record moves on.

## 2. Anchor record

```mermaid
classDiagram
    class AnchorsFile {
        schema = "plan-anchoring/anchors/1"
        plan
        intent_ref
        anchors : Anchor[]
    }
    class Anchor {
        id : ANC-NNN | REQ-* | ADR-*
        source_type : ANC | REQ | ADR
        source_ref
        statement : testable requirement, authored, approved
        quote : verbatim user words, immutable
        stated_by
        stated_at : ISO date
        context
        summary : table label, never judged
        scope : feeds the relevance question
        deterministic_check
        fixtures : pass[], fail[]
        question_overrides : plan?, dev?
        exclude : item, reason []
        version : int
        status : proposed | locked | promoted | retired
        promoted_to
        beads : anchor, plan_questions, dev_questions
        history : Event[]
    }
    class Run {
        schema = "plan-anchoring/run/1"
        run_id : gate-stamp-item
        gate : plan | dev
        item : id, title, source, chars, truncated
        model_requested
        model_answered
        threshold
        dry_run, fixture
        results : Result[]
        summary : counts, failing, errors, pass
    }
    class Result {
        anchor_id
        statement, stated_by, stated_at, context
        question_set : gate, version, overridden
        questions_sha256
        answers : per question choice, probabilities, confidence
        verdict
        min_confidence
        attempts, item_chars_sent, item_shortened
        explanation
        deterministic_check
    }
    AnchorsFile "1" --> "*" Anchor
    Run "1" --> "*" Result
    Result ..> Anchor : copies statement and provenance
```

Rules that follow from the model:

- `quote` is immutable: the user's words. `statement` is the instrument Jev judges; it may be reworded for testability (`update --statement`), and every run file copies the statement it judged, so past verdicts keep their meaning. A changed directive is a new anchor; the old one is retired with `replaced_by` in its history.
- `version` bumps on statement, scope, summary, fixtures, overrides or status changes. `exclude` (items the anchor does not apply to, each with a reason) never bumps it: `judge` skips the cell with no Jev call and reports `excluded`, which passes.
- `ANC-NNN` is allocated by the script as max plus one and never reused. REQ and ADR anchors use their register ID so a report line points at the register directly.
- `summary` exists for tables; Jev never sees it. `scope` is sent, because it drives the relevance question.

## 3. What Jev sees

One anchor, one item, three or four questions. Nothing else.

```json
{
  "model": "jev-latest",
  "state": {
    "anchor": {"id": "ANC-012", "statement": "copy the libraries from the legacy repo as the starting point and remove the legacy-specific code", "scope": "the runtime crates sprint and any bead that creates the core library implementation"},
    "item": {"id": "bd-42", "title": "Sprint 2 runtime", "text": "# Sprint 2 runtime\n\n## Description\n..."}
  },
  "questions": {
    "relevant":     {"type": "choice", "instructions": "...", "criteria": {"yes": "...", "no": "...", "unclear": "..."}},
    "addressed":    {"type": "choice", "instructions": "...", "criteria": {"yes": "...", "no": "...", "unclear": "..."}},
    "contradicted": {"type": "choice", "instructions": "...", "criteria": {"yes": "...", "no": "...", "unclear": "..."}}
  }
}
```

| Gate | Question IDs | Roles |
| --- | --- | --- |
| plan | `relevant`, `addressed`, `contradicted` | relevance, compliance, conflict |
| dev | `relevant`, `implemented`, `violated`, `evidenced` | relevance, compliance, conflict, evidence |

Each question isolates one failure mode and says explicitly what it does not judge, because Jev answers them independently and cannot see its other answers. Wording of record is `assets/questions/{plan,dev}.json`; a question bead may override wording for one anchor but keeps the IDs and the `yes`/`no`/`unclear` options so the gating still applies.

## 4. Verdict gating

Jev returns a `choice` and a `confidence` per question. The script combines them with threshold `t` (default 0.6), evaluated top to bottom, first match wins.

```mermaid
flowchart TD
    Start(["answers for one anchor × one item"]) --> R{"relevance = no<br/>and confidence ≥ t?"}
    R -- "yes" --> NA["not_applicable"]
    R -- "no" --> C{"conflict = yes<br/>and confidence ≥ t?"}
    C -- "yes" --> CO["contradicted"]
    C -- "no" --> U{"relevance or compliance unclear,<br/>or either confidence &lt; t?"}
    U -- "yes" --> US["underspecified"]
    U -- "no" --> A{"compliance?"}
    A -- "no" --> NAd["not_addressed"]
    A -- "yes" --> E{"evidence role exists and<br/>evidence = no with confidence ≥ t?"}
    E -- "yes" --> AO["asserted_only"]
    E -- "no" --> SAT["satisfied"]

    classDef fail fill:#f8d7da,stroke:#842029,color:#000
    classDef ok fill:#d1e7dd,stroke:#0f5132,color:#000
    classDef na fill:#e2e3e5,stroke:#41464b,color:#000
    class CO,NAd,AO,US fail
    class SAT ok
    class NA na
```

Severity order for sorting and reports: `contradicted` > `not_addressed` > `asserted_only` > `underspecified` > `satisfied` > `not_applicable`. A run passes when no result is in the failing set or `error`. Contradiction outranks underspecification because a confident conflict is actionable even when relevance was shaky. `min_confidence` is reported so an anchor that is `underspecified` across many beads can be recognised as badly worded rather than the beads being vague.

What each verdict means for the caller:

| Verdict | Planning gate | Development gate |
| --- | --- | --- |
| `contradicted` | Bead proposes what the directive rules out: change the approach or escalate | Work went against the directive: block acceptance |
| `not_addressed` | Bead is silent on the directive: add its specific content | Account does not show the directive was followed: block until shown |
| `asserted_only` | n/a | Compliance claimed without evidence: get evidence or run the deterministic check |
| `underspecified` | Jev not confident: sharpen `scope` or the bead | Same, usually a vague sprint report |
| `satisfied` | Nothing | Run the paired deterministic check |
| `not_applicable` | Nothing, unless the anchor should have applied (scope too narrow) | Same |
| `excluded` | Nothing; Jev was not asked, the anchor's `exclude` names this item with a reason | Same |

Before editing on any failing verdict, the caller re-reads the exact text that was sent (the composed item file) at the point the anchor governs. If Jev looks wrong, the posted report says so with the reason and the user is asked, rather than rewording the bead until Jev agrees.

## 5. Coverage and diffs are computed, not asked

```mermaid
flowchart LR
    R1["run: plan × bd-41"] --> M
    R2["run: plan × bd-42"] --> M
    R3["run: plan × bd-43"] --> M
    M["coverage: latest run per (gate, item)<br/>anchors × items matrix, columns gate:item"] --> U["uncovered anchors:<br/>no item is satisfied"]
    Prev["run N-1 (bd-42)"] --> D["diff: changed / added / removed<br/>regressions, pass before → after"]
    Next["run N (bd-42)"] --> D
```

Jev cannot count or compare across beads, so "is ANC-012 satisfied anywhere" and "what did my edit change" are answered from run files by the script. An anchor that is `not_applicable` to every bead is reported as uncovered on purpose: either its scope is wrong or the plan lacks the bead that should carry it.

## 6. Anchor lifecycle

```mermaid
stateDiagram-v2
    [*] --> proposed : detected and quoted, not yet confirmed
    proposed --> locked : user confirms or says lock this
    proposed --> retired : never confirmed
    locked --> promoted : promote --adr ADR-NNNN (keeps ID, gains ADR ref)
    locked --> retired : directive changed or withdrawn; new anchor replaces it
    promoted --> retired : ADR superseded
    retired --> [*]

    note right of locked
        Judged at both gates.
        Statement immutable from here.
    end note
    note right of proposed
        Recorded so it survives
        context compression; not judged.
    end note
```

Only `locked` and `promoted` anchors are judged by `--all`; an explicit `--anchor` on a proposed or retired anchor is refused. Fixtures (`pass` and `fail` sentences) are drafted at lock time and approved by the user; `check-fixtures` judges them as items to confirm the question wording lands them where expected, and `--answers-file` fixtures exercise the gating offline in CI.

## 7. Capture, as a sequence

```mermaid
sequenceDiagram
    participant U as User
    participant P as Planning agent (skill loaded)
    participant S as jev_judge.py
    participant B as bd

    U->>P: "copy the libraries from the legacy repo as the starting point and remove the legacy-specific code"
    P->>U: Anchor candidate quoted verbatim. Lock as ANC-012?
    U->>P: lock it
    P->>S: add --statement "<verbatim>" --scope ... --status locked
    S-->>P: ANC-012 allocated, anchors.json written
    P->>S: validate, render → anchors.md
    P->>B: bd create anchor bead (type decision, labels anchor, anchor:ANC-012)
    P->>B: bd create plan-questions child, dev-questions child (gate:plan, gate:dev)
    P->>S: set-beads --id ANC-012 --anchor-bead ... --plan-bead ... --dev-bead ...
    P->>U: drafts one pass and one fail fixture, user approves
    P->>S: update --id ANC-012 --fixture-pass ... --fixture-fail ... --deterministic-check ...
```

Capture is the one interactive step and stays in the main session. Nothing is locked without the user's confirmation. The statement proposed is a testable requirement that passed the rubric, not the quote; the quote is kept verbatim. After locking, the planner launches the independent higher-reasoning `anchor-tuning` subagent (Opus on Claude, Sol on Codex). It freezes an oracle from approved intent and anchors before its first Jev call, evaluates candidate questions without a plan-pass objective, and seals only protocol-validated production sets. The same identity later triages disputed review evidence without accepting a desired verdict.

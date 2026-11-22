"""Pure fixture builders shared by offline tests and the real-wheel harness."""
import json
from pathlib import Path

from layout_support import SCRIPTS

STATEMENT = "The runtime crates are created by copying the legacy repo's runtime crates and deleting the legacy-specific modules; no runtime crate is written from scratch."
QUOTE = "copy the libraries from the legacy repo as the starting point and remove the legacy-specific code"
ROLES = ("addressed", "contradicted", "relevant")
ANCHOR_STATE = {"id": "ANC-001", "statement": STATEMENT, "scope": "the runtime crates", "kind": "directive"}
PLAN_QS = json.loads((SCRIPTS.parent / "assets" / "questions" / "plan.json").read_text(encoding="utf-8"))


def anchor(aid="ANC-001", status="locked", source_type="ANC", source_ref=None, statement=STATEMENT, quote=None, **extra):
    """A valid anchor record. ANC anchors get the verbatim QUOTE; REQ/ADR anchors quote their register text."""
    if quote is None:
        quote = QUOTE if source_type == "ANC" else statement
    rec = {
        "id": aid, "source_type": source_type, "source_ref": source_ref, "statement": statement, "quote": quote,
        "stated_by": "the user", "stated_at": "2026-10-09", "context": "planning session",
        "summary": "start from the legacy repo", "scope": "the runtime crates", "deterministic_check": "",
        "fixtures": {"pass": [], "fail": []}, "question_overrides": {}, "version": 1, "status": status,
        "promoted_to": None, "beads": {"anchor": None, "plan_questions": None, "dev_questions": None}, "history": [],
    }
    rec.update(extra)
    return rec


def record(*anchors):
    return {"schema": "plan-anchoring/anchors/1", "plan": "phase-z", "intent_ref": "docs/plans/phase-z/intent.md",
            "anchors": list(anchors)}


def write(d, name, value):
    path = Path(d) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
    return str(path)


def question(role, n):
    return {"type": "choice", "instructions": f"Variant {n}: does `item.text` meet the {role} judgment for `anchor.statement`?",
            "criteria": {"yes": f"{role} holds ({n})", "no": f"{role} does not hold ({n})", "unclear": f"cannot tell ({n})"}}


def request_line(item_id, text, *cands, title=""):
    return {"item": {"id": item_id, "title": title, "text": text}, "anchor": dict(ANCHOR_STATE),
            "questions": [{"candidate_id": c, "questions": qs} for c, qs in cands]}


def alt_set(n):
    return {role: question(role, n) for role in ROLES}


def jsonl(lines):
    return "".join(json.dumps(x) + "\n" for x in lines)


BATCH_LINES = [request_line("s1", "We copy the legacy crates.", ("cur", PLAN_QS["questions"]), ("alt", alt_set(1)), title="Sprint 1"),
               request_line("s3", "# Sprint 3\n\nCopy the legacy runtime crates.\n", ("cur", PLAN_QS["questions"]))]


def wheel_line(line, *, position=0, sends=1):
    """Add ResultLine envelope fields to a controlled legacy fixture."""
    value = json.loads(line) if isinstance(line, str) else dict(line)
    value.setdefault("session_id", "01ARZ3NDEKTSV4RRFFQ69G5FAV")
    value.setdefault("position", position)
    value.setdefault("digests", {})
    value.setdefault("sends", value.get("error", {}).get("attempts", sends))
    from sc_decidr_test_double import envelope
    return envelope(value)


def context_overflow_line(*, sends=1, position=0):
    """Build the controlled context-overflow result shape."""
    return wheel_line({"error": {
        "id": "decision.context_exceeded",
        "message": "the API answered HTTP 413: request exceeds the model's context window",
        "action": "shorten the request and send again", "status": 413, "category": "validation",
    }}, sends=sends, position=position)

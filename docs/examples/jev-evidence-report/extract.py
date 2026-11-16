"""Extract plan-anchoring run evidence into one compact JSON for the report.

Usage: python3 extract.py <anchor-runs-dir> <report-data.json>

<anchor-runs-dir> holds testability/, rubric/, check-fixtures-{dev,plan}/ and plan-gate/
as written by plan-anchoring runs (schema plan-anchoring/run/1).
"""
import json
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])


def load(p):
    return json.loads((root / p).read_text())


def ans(a):
    if not a:
        return None
    return {q: {"choice": v.get("choice"), "conf": v.get("confidence"), "probs": v.get("probabilities")} for q, v in a.items()}


# ---- tuning tournament
t = (root / "testability/result.md").read_text()
td = json.loads(t[t.index("{"): t.rindex("}") + 1])["data"]
oracle = load("testability/oracle.json")
cases = [
    {
        "id": c["case_id"],
        "rationale": c["rationale"],
        "statement": c["state"]["anchor"]["statement"],
        "quote": c["state"]["anchor"]["quote"],
        "expected": c["expected"],
    }
    for c in oracle["semantic_cases"]
]
ev = td["evidence"]
tuning = {
    "explanation": td["explanation"],
    "accepted": td["accepted"],
    "candidate_count": td["candidate_count"],
    "corpus_case_count": td["corpus_case_count"],
    "production_threshold": td["production_confidence_threshold"],
    "reference_threshold": td["confidence_reference_threshold"],
    "semantic_score": td["semantic_score"],
    "dedupe_score": td["dedupe_score"],
    "lint": {
        "total": len(td["deterministic_lint"]["cases"]),
        "match": sum(1 for c in td["deterministic_lint"]["cases"] if c["match"]),
    },
    "jev_calls": int(ev["jev_calls"]),
    "jev_endpoint": ev["jev_endpoint"],
    "jev_model": ev["jev_model"],
    "workspace_head_note": ev["workspace_head_note"],
    "rankings": td["candidate_rankings"],
    "best": "E1",
    "cells": [
        {
            "case": r["case_id"],
            "role": r["role"],
            "expected": r["expected"],
            "accepted": r["accepted"],
            "primary": r["primary"],
            "replication": r["replication"],
        }
        for r in td["acceptance_table"]
    ],
    "cases": cases,
}

# ---- rubric rounds (anchor quality)
def rubric_round(anchors):
    return {
        "n": len(anchors),
        "verdicts": Counter(a["verdict"] for a in anchors),
        "failing": Counter(f for a in anchors for f in a["failing"]),
        "anchors": [{"id": a["id"], "statement": a["statement"], "verdict": a["verdict"], "failing": a["failing"]} for a in anchors],
    }

r0 = load("rubric/rubric-round0-original-19.json")["data"]["anchors"]
r2raw = load("rubric/rubric-round2-candidates.json")
r2 = []
for k, v in r2raw.items():
    for a in v["result"]["data"]["anchors"]:
        a = dict(a)
        a["id"] = k
        r2.append(a)
rubric = {"round0": rubric_round(r0), "round2": rubric_round(r2)}

# ---- fixture checks
import re
EXPECTED = {"pass": ["satisfied"], "fail": ["not_addressed", "contradicted"]}
fixtures = {}
for g in ["dev", "plan"]:
    s = load(f"check-fixtures-{g}/summary.json")["data"]
    sentences = {(c["anchor_id"], c["kind"]): c["sentence"] for c in s["checks"]}
    files = sorted((root / f"check-fixtures-{g}/fixtures").glob("*.json"))
    latest = {}
    for f in files:
        m = re.search(r"(\d{8}T\d{6}Z)-fixture_(ANC-\d+)_(pass|fail)", f.name)
        latest[(m[2], m[3])] = f.name
    rows = []
    for f in files:
        m = re.search(r"(\d{8}T\d{6}Z)-fixture_(ANC-\d+)_(pass|fail)", f.name)
        anchor, kind = m[2], m[3]
        run = json.loads(f.read_text())
        res = run["results"][0]
        verdict = res["verdict"]
        rows.append({
            "anchor": anchor,
            "kind": kind,
            "latest": latest[(anchor, kind)] == f.name,
            "sentence": sentences.get((anchor, kind)),
            "verdict": verdict,
            "expected": EXPECTED[kind],
            "expected_ok": None if verdict == "deterministic_only" else verdict in EXPECTED[kind],
            "min_conf": res.get("min_confidence"),
            "answers": ans(res.get("answers")),
            "statement": res.get("statement"),
            "anchor_version": res.get("anchor_version"),
            "created_at": run["created_at"],
            "model": run["model_answered"],
            "tokens": (res.get("usage") or {}).get("input_tokens", 0) + (res.get("usage") or {}).get("output_tokens", 0),
        })
    fixtures[g] = {"summary_pass": s["pass"], "summary_checks": len(s["checks"]), "files": len(files), "rows": rows, "threshold": 0.6}

# ---- plan gate
gate = []
for i in range(1, 8):
    j = load(f"plan-gate/final/atm-bo-{i}.judge.json")
    gate.append({
        "bead": j["item"]["id"],
        "title": j["item"]["title"],
        "chars": j["item"]["chars"],
        "created_at": j["created_at"],
        "pass": j["summary"]["pass"],
        "results": [
            {"anchor": r["anchor_id"], "verdict": r["verdict"], "min_conf": r.get("min_confidence"),
             "answers": ans(r.get("answers")), "statement": r.get("statement")}
            for r in j["results"]
        ],
    })

tr = load("plan-gate/triage-round1.json")
triage = {
    "run": tr["run"],
    "rounds": [
        {"name": "Round 1", "edits": tr["to_fix"]},
        {"name": "Round 2", "edits": tr["round2"]},
        {"name": "Round 3", "edits": tr["round3"].get("to_fix", []), "note": tr["round3"].get("split")},
    ],
    "exclude": tr["exclude"],
}

json.dump({
    "source": {"repo": "randlee/atm-core", "commit": "f97d33e", "deleted_by": "a2c2bdf (PR #2331)", "path": "docs/plans/phase-bo/anchor-runs/"},
    "tuning": tuning, "rubric": rubric, "fixtures": fixtures, "gate": gate, "triage": triage,
}, out.open("w"), default=dict)
print("ok", out.stat().st_size)

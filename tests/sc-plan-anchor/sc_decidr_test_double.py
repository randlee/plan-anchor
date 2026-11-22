"""Deterministic test double for the optional sc-decidr wheel boundary.

Consumer unit tests control the JSON wire lines and must not import a compiled
wheel, read credentials, or contact a provider. This double models only the
public operations the generated client calls.
"""
from __future__ import annotations

import json
import math
from types import ModuleType


class SagError(Exception):
    def __init__(self, detail):
        if isinstance(detail, str):
            detail = json.loads(detail)
        detail = dict(detail)
        super().__init__(detail.get("id", "unknown"))
        self.id = detail.get("id")
        self.message = detail.get("message")
        self.detail = detail
        self.category = detail.get("category", "other")


def category(detail: str) -> str:
    return json.loads(detail).get("category", "other")


def retryable(detail: str) -> bool:
    return category(detail) in {"busy", "network"}


class Cancel:
    def cancel(self):
        pass


def parse_result(line: str, wheel: ModuleType | None = None) -> dict:
    parsed = json.loads(line)
    error_detail = parsed.get("error")
    error = None
    if error_detail is not None:
        error_type = getattr(wheel, "SagError", SagError) if wheel is not None else SagError
        error = error_type(error_detail)
        for key in ("id", "message", "category", "status", "attempts", "retry_after_ms"):
            if key in error_detail:
                setattr(error, key, error_detail[key])
    response = parsed.get("response") or {}
    answers = response.get("answers", {})
    if not isinstance(answers, dict):
        error_type = getattr(wheel, "SagError", SagError) if wheel is not None else SagError
        error = error_type({"id": "decision.response_parse", "category": "response_invalid",
                            "message": "answers must be an object", "attempts": parsed.get("sends", 0)})
    elif any(not _valid_answer(answer) for answer in answers.values()):
        error_type = getattr(wheel, "SagError", SagError) if wheel is not None else SagError
        error = error_type({"id": "decision.response_parse", "category": "response_invalid",
                            "message": "answer is not a typed answer", "attempts": parsed.get("sends", 0)})
    return {
        "session_id": parsed.get("session_id"),
        "position": parsed.get("position"),
        "sends": parsed.get("sends"),
        "digests": parsed.get("digests", {}),
        "error": error,
        "answers": answers,
        "usage": response.get("usage", {}),
    }


def _unit_interval(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _valid_answer(answer) -> bool:
    if not isinstance(answer, dict):
        return False
    kind = answer.get("type")
    if kind == "noul":
        return _unit_interval(answer.get("noul"))
    if kind == "choice":
        probs = answer.get("probabilities")
        return (isinstance(answer.get("choice"), str) and _unit_interval(answer.get("confidence"))
                and isinstance(probs, dict) and bool(probs)
                and all(isinstance(key, str) and _unit_interval(value) for key, value in probs.items())
                and math.isclose(sum(probs.values()), 1.0, rel_tol=0, abs_tol=1e-6))
    if kind == "score":
        return _unit_interval(answer.get("score")) and _unit_interval(answer.get("confidence"))
    if kind == "box":
        box = answer.get("box")
        return (isinstance(box, dict) and all(_unit_interval(box.get(side)) for side in ("top", "bottom", "left", "right"))
                and (answer.get("confidence") is None or _unit_interval(answer.get("confidence"))))
    return False


def envelope(line):
    value = json.loads(line) if isinstance(line, str) else dict(line)
    if "ok" in value:
        return value
    if value.get("error") is not None:
        detail = dict(value["error"])
        detail.setdefault("attempts", value.get("sends", 1))
        return {"ok": False, "error": detail, "index": value.get("position", 0)}
    body = dict(value.get("response", {}))
    body.setdefault("answers", {})
    body.update(attempts=value.get("sends", 1), session_id=value.get("session_id"), question_digests=value.get("digests", {}))
    return {"ok": True, "value": body, "index": value.get("position", 0)}


def send(*args, **kwargs):
    return envelope({"sends": 0, "error": {"id": "auth.credentials", "category": "auth", "message": "missing key", "attempts": 0}})


def send_batch(*args, **kwargs):
    return {"ok": True, "value": []}


def batch_result(lines, on_result):
    items = []
    for line in lines:
        value = envelope(line)
        index = value.pop("index", 0)
        on_result(index, value)
        items.append({"index": index, "result": value})
    return {"ok": True, "value": sorted(items, key=lambda item: item["index"])}


def as_module() -> ModuleType:
    module = ModuleType("sc_agent")
    module.SagError = SagError
    module.Cancel = Cancel
    module.category = category
    module.retryable = retryable
    module.parse_result = lambda line: parse_result(line, module)
    module.logger = lambda name: {"ok": True, "value": object()}
    module.send = send
    module.send_batch = send_batch
    return module

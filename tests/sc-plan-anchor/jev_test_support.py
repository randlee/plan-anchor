"""Offline judge helpers; importing this module intentionally installs the wheel double."""
import contextlib
import io
import sys

import sc_decidr_test_double
sys.modules["sc_agent"] = sc_decidr_test_double.as_module()

from layout_support import SCRIPTS
from jev_inputs import (
    ANCHOR_STATE, BATCH_LINES, PLAN_QS, QUOTE, STATEMENT, alt_set, anchor,
    context_overflow_line, jsonl, question, record, request_line, wheel_line, write,
)

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import jev_judge as jj


def run_cli(argv):
    """Run main() in-process against the deterministic wheel double."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = jj.main(argv)
    out = buf.getvalue()
    try:
        import json
        return code, json.loads(out)
    except json.JSONDecodeError:
        return code, out

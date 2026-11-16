"""The test child timeout is a hang guard, not an elapsed-time assertion."""
import subprocess
import unittest
from unittest import mock

from child_support import HANG_GUARD_SECONDS, run_test_child


class ChildSupportTests(unittest.TestCase):
    def test_input_and_shorter_timeout_are_preserved(self):
        with mock.patch("child_support.subprocess.run") as run:
            run_test_child(["child"], input=b"data", timeout=30)
        self.assertEqual(run.call_args.kwargs, {"input": b"data", "timeout": 30})

    def test_no_input_closes_stdin(self):
        with mock.patch("child_support.subprocess.run") as run:
            run_test_child(["child"])
        self.assertEqual(run.call_args.kwargs, {"stdin": subprocess.DEVNULL, "timeout": HANG_GUARD_SECONDS})

    def test_timeout_fails_with_the_original_cause(self):
        error = subprocess.TimeoutExpired(["child"], 30)
        with mock.patch("child_support.subprocess.run", side_effect=error):
            with self.assertRaises(AssertionError) as caught:
                run_test_child(["child"], timeout=30)
        self.assertIs(caught.exception.__cause__, error)
        self.assertIn("child", str(caught.exception))

    def test_timeout_cannot_be_disabled_or_widened(self):
        for value in (None, HANG_GUARD_SECONDS + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_test_child(["child"], timeout=value)

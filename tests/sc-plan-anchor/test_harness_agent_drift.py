"""Fail when Claude, Codex, and Cursor copies diverge after harness frontmatter.

Installed agent bodies (fresh renders, per tracker) must match once YAML
frontmatter is removed. Registries (install/harness/<harness>/registry.yaml)
must match once each ``.{harness}/`` path prefix is normalized.
"""

from pathlib import Path
import difflib
import re
import unittest

from layout_support import HARNESS, TRACKERS, rendered_agent


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "sc-plan-anchor"
HARNESSES = ("claude", "codex", "cursor")
AGENTS = ("anchor-cleanup-proposer.md", "anchor-plan-review.md", "anchor-sprint-review.md", "anchor-tuning.md")
HARNESS_PATH = re.compile(r"\.(claude|codex|cursor)/")


def posix_bash():
    """bash as Claude Code runs hooks with it: on Windows, Git Bash (beside git), never the WSL launcher in System32."""
    import shutil, sys
    if sys.platform != "win32":
        return shutil.which("bash")
    git = shutil.which("git")
    for root in Path(git).resolve().parents if git else ():
        candidate = root / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def body_after_frontmatter(text: str, path: Path) -> str:
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} has no YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AssertionError(f"{path} has unterminated YAML frontmatter")
    return text[end + 5 :]


def explain(label: str, left_name: str, left: str, right_name: str, right: str) -> str:
    diff = "".join(
        difflib.unified_diff(
            left.splitlines(keepends=True),
            right.splitlines(keepends=True),
            fromfile=left_name,
            tofile=right_name,
        )
    )
    return f"{label} drifted:\n{diff}"


class HarnessAgentDriftTests(unittest.TestCase):
    def test_agent_bodies_match_after_frontmatter(self):
        for tracker in TRACKERS:
            for name in AGENTS:
                bodies = {}
                for harness in HARNESSES:
                    path = rendered_agent(tracker, harness, name)
                    self.assertTrue(path.is_file(), f"missing {path}")
                    bodies[harness] = body_after_frontmatter(path.read_text(encoding="utf-8"), path)
                baseline = bodies["claude"]
                for harness in HARNESSES[1:]:
                    self.assertEqual(
                        baseline,
                        bodies[harness],
                        explain(f"{tracker} {name}", "claude", baseline, harness, bodies[harness]),
                    )

    def test_registries_match_after_harness_path(self):
        normalized = {}
        for harness in HARNESSES:
            path = HARNESS / harness / "registry.yaml"
            self.assertTrue(path.is_file(), f"missing {path}")
            normalized[harness] = HARNESS_PATH.sub(".HARNESS/", path.read_text(encoding="utf-8"))
        baseline = normalized["claude"]
        for harness in HARNESSES[1:]:
            self.assertEqual(
                baseline,
                normalized[harness],
                explain("registry.yaml", "claude", baseline, harness, normalized[harness]),
            )

    def test_cleanup_proposer_hook_allows_only_read_only_git(self):
        """The Claude proposer may run Bash only for git log, git blame and git show (its PreToolUse hook). The hook's
        code is hex-encoded so every shell hands Python the same bytes; the header comment shows it decoded."""
        import json, os, shutil, subprocess, sys, tempfile
        bash = posix_bash()
        if bash is None:
            self.skipTest("the hook command runs under bash (Git Bash on Windows, as Claude Code runs hooks there)")
        header = (HARNESS / "claude" / "agents" / "anchor-cleanup-proposer.md").read_text(encoding="utf-8").split("---\n")[1]
        self.assertRegex(header, r"(?m)^hooks:\n  PreToolUse:\n    - matcher: Bash\n      hooks:\n        - type: command\n          command: ")
        command = re.search(r"(?m)^          command: (.+)$", header).group(1)
        hexed = re.fullmatch(r"python3 -c 'import sys; exec\(bytes\.fromhex\(sys\.argv\[1\]\)\)' ([0-9a-f]+)", command).group(1)
        shown = "".join(line[4:] + "\n" if line.startswith("# | ") else "\n" for line in header.splitlines() if line.startswith("# |"))
        self.assertEqual(bytes.fromhex(hexed).decode("utf-8"), shown, "the comment shows the hook's code exactly")
        # `python3` is the interpreter running this test, whatever the machine's PATH holds.
        shim = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, shim, True)
        with open(os.path.join(shim, "python3"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n')
        os.chmod(os.path.join(shim, "python3"), 0o755)
        env = dict(os.environ, PATH=shim + os.pathsep + os.environ.get("PATH", ""))
        for cmd, code in (('git log -S"retry 5 times" -- docs', 0), ("git -C repo blame docs/REQ-1.md", 0), ("git show abc:docs/x.md", 0),
                          ("git log; rm -rf x", 2), ("git log --output=x", 2), ("git push", 2), ("git show $(id)", 2), ("cat x", 2),
                          ("git log\nrm x", 2)):
            got = subprocess.run([bash, "-c", command], input=json.dumps({"tool_input": {"command": cmd}}).encode("utf-8"),
                                 capture_output=True, check=False, env=env)
            self.assertEqual(got.returncode, code, (cmd, got.stdout, got.stderr))
        got = subprocess.run([bash, "-c", command], input=b"not json", capture_output=True, check=False, env=env)
        self.assertEqual(got.returncode, 2, "unreadable input fails closed")

if __name__ == "__main__":
    unittest.main()

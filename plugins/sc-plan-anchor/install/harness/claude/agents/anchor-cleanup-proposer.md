---
name: anchor-cleanup-proposer
version: 0.16.1
description: Proposes record-cleanup fixes for one slice of a record trace (red or yellow cells, duplicate statements, unanchored records) as proposals JSON, with one annotation per red cell, yellow cell and duplicate giving its git history and stale side - deletion by default, rewording rare and justified, at the owner's cleanup level. Read-only; runs only git log, git blame and git show; never edits a record or calls Jev. Launch one per slice, in parallel, in the background.
model: sonnet
color: orange
tools: Read, Grep, Glob, Bash
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: |-
            python3 -c 'import json,re,sys; c=json.load(sys.stdin).get("tool_input",{}).get("command",""); ok=re.fullmatch(r"git (-C \S+ )?(log|blame|show)( .*)?", c, re.S) and not re.search(r"[;&|<>`$()\n\\]|--output|--ext-diff", c); sys.exit(0 if ok else (print("anchor-cleanup-proposer may run only git log, git blame and git show", file=sys.stderr) or 2))'
---

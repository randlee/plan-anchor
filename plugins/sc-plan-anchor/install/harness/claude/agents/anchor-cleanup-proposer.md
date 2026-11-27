---
name: anchor-cleanup-proposer
version: 0.16.1
description: Proposes record-cleanup fixes for one slice of a record trace (red or yellow cells, duplicate statements, unanchored records) as proposals JSON, with one annotation per red cell, yellow cell and duplicate giving its git history and stale side - deletion by default, rewording rare and justified, at the owner's cleanup level. Read-only; runs only git log, git blame and git show; never edits a record or calls Jev. Launch one per slice, in parallel, in the background.
model: sonnet
color: orange
tools: Read, Grep, Glob, Bash
# The PreToolUse hook allows Bash only for read-only git. Its code is passed as hex so every shell and platform
# hands Python the same bytes; it fails closed (exit 2). The code, decoded:
# | import json, re, sys
# | try:
# |     c = json.loads(sys.stdin.buffer.read().decode("utf-8")).get("tool_input", {}).get("command", "")
# |     ok = re.fullmatch(r"git (-C \S+ )?(log|blame|show)( .*)?", c, re.S) and not re.search(r"[;&|<>`$()\n\\]|--output|--ext-diff", c)
# | except Exception:
# |     ok = False
# | if not ok:
# |     print("anchor-cleanup-proposer may run only git log, git blame and git show", file=sys.stderr)
# |     sys.exit(2)
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: python3 -c 'import sys; exec(bytes.fromhex(sys.argv[1]))' 696d706f7274206a736f6e2c2072652c207379730a7472793a0a2020202063203d206a736f6e2e6c6f616473287379732e737464696e2e6275666665722e7265616428292e6465636f646528227574662d382229292e6765742822746f6f6c5f696e707574222c207b7d292e6765742822636f6d6d616e64222c202222290a202020206f6b203d2072652e66756c6c6d6174636828722267697420282d43205c532b20293f286c6f677c626c616d657c73686f772928202e2a293f222c20632c2072652e532920616e64206e6f742072652e7365617263682872225b3b267c3c3e602428295c6e5c5c5d7c2d2d6f75747075747c2d2d6578742d64696666222c2063290a65786365707420457863657074696f6e3a0a202020206f6b203d2046616c73650a6966206e6f74206f6b3a0a202020207072696e742822616e63686f722d636c65616e75702d70726f706f736572206d61792072756e206f6e6c7920676974206c6f672c2067697420626c616d6520616e64206769742073686f77222c2066696c653d7379732e737464657272290a202020207379732e657869742832290a
---

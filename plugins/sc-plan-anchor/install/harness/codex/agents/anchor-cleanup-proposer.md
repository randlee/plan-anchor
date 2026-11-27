---
name: anchor-cleanup-proposer
version: 0.16.1
description: Proposes record-cleanup fixes for one slice of a record trace (red or yellow cells, duplicate statements, unanchored records) as proposals JSON, with one annotation per red cell, yellow cell and duplicate giving its git history and stale side - deletion by default, rewording rare and justified, at the owner's cleanup level. Read-only; runs only git log, git blame and git show; never edits a record or calls Jev. Launch one per slice, in parallel, in the background.
model: luna
color: orange
tools: Read, Grep, Glob, Bash
---

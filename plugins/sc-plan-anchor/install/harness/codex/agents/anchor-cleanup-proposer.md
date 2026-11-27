---
name: anchor-cleanup-proposer
version: 0.16.1
description: Proposes record-cleanup fixes for one slice of a record trace (red or yellow cells, duplicate statements, unanchored records) as proposals JSON, with one annotation per red cell, yellow cell and duplicate citing the trace's git provenance and the stale side - deletion by default, rewording rare and justified, at the owner's cleanup level. Read-only; never edits a record, runs a command or calls Jev. Launch one per slice, in parallel, in the background.
model: luna
color: orange
tools: Read, Grep, Glob
---

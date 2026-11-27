---
name: anchor-cleanup-proposer
version: 0.16.0
description: Proposes record-cleanup fixes for one slice of a record trace (red or yellow cells, duplicate statements, unanchored records) as proposals JSON - deletion by default, rewording rare and justified, at the run's cleanup level. Read-only; never edits a record or calls Jev. Launch one per slice, in parallel, in the background.
model: luna
color: orange
tools: Read, Grep, Glob
---

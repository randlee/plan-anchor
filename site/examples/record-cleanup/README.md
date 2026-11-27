# Record cleanup: sc-agent records against the phase-j anchors

**Shows:** a real trace of 8 sc-agent records against 16 anchors, with real Jev answers, and agent-written proposals at level `aggressive`.

**Page:** [the report](report.html)

## Where the data came from

A live trace and a live overlap run on 2026-11-26:

- **Trace** (`plan-anchoring/trace/2`): 85 records from two Raptor indexes, against 16 locked anchors. That is 1360 cells, each with its 4 Jev answers.
- **Overlap run**: 11 requests holding 290 per-statement questions over 14 records.

This example keeps the 8 REQ records whose overlap requests the current code builds exactly as the live run sent them, with the same item text and the same statement questions. That makes 128 cells, plus 5 overlap requests holding 77 statements.

The overlap run's 6 ADRs were dropped because the live run split an ADR's decision into several statements, while the current code asks about it as one statement. No real answer exists for those requests.

## What is real and what is agent-written

- **Real**, in `inputs/`:
  - `anchors.json`: the trace's embedded anchors.
  - `raptor-sc-agent.json`: the saved Raptor index, keeping only the 8 records, each unchanged.
  - `ids.txt`: the 8 record ids.
  - `source.json`: the records' repository and the commit they were read at.
  - `answers.json`: the live Jev answers. Cells are keyed `<record>/<anchor>` and overlap requests `<item>/overlap`. There is no `*` fallback and no made-up answer.
- **Agent-written**: `inputs/proposals.json`. The `anchor-cleanup-proposer` agents wrote it at level `aggressive` from slices of the trace, and the lead merged it. No person or Jev wrote these proposals. Where each one came from:

Four proposers ran in parallel, one per slice, each with no shared context.

- Panel 1: `wave-1-dups` (the duplicate REQ-SAG-0019/REQ-SAG-0801/7).
- Panels 2–3: `wave-1-red-0801` (REQ-SAG-0801 at ANC-001, red, and at ANC-009).
- Panels 4–7: `wave-1-yellow-a` (the yellow cells of REQ-SAG-0003, 0008 and 0019).
- Panels 8–13: `wave-1-yellow-b` (the yellow cells of REQ-SAG-0101, 0102 and 0103).

The lead dropped one proposal. `wave-1-red-0801` proposed deleting REQ-SAG-0801's paid-API key rule and anchoring it. Panel 1 already deletes that statement as a duplicate, and panel 6 proposes the anchor for the copy kept in REQ-SAG-0019. The proposers' text is otherwise unedited.

- **Pending**: `inputs/annotations.json`, the `anchor-cleanup-proposer` annotations, each citing the trace's provenance, for every red cell, yellow cell and duplicate. It is not checked in yet. Until it is, those panels show "No reviewer annotation yet." and the Proposed fixes tab lists the items under "Cells and duplicates without an annotation with git history". The lead will fill it from the proposers' `annotations` output. `build-examples.py` passes it to `change_report.py --annotations` once it exists. The example always renders with `--draft`, so the page carries the draft banner while any gap remains. Each statement's `provenance` is real: `build-examples.py` reads it from the records' repository at the commit in `inputs/source.json`, the one the live trace read, 7 minutes before it ran. It fails if any of the 8 records' statements is not in the files at that commit. `--no-provenance` builds offline, with no provenance. The dropped proposal above is not yet recorded in the proposals file's `dropped` list either.

The report is replayed offline from the fixture answers. So the generated trace shows `model_answered: fixture` and no session ids. The original Jev session ids are in the live trace, which is not checked in.

## Reproduce

```bash
python3 scripts/build-examples.py
```

This renders the installed scripts and runs `jev_judge.py trace` offline, then `change_report.py --trace --proposals`. It writes `report.html`, `report/`, `trace.json` and `record-trace.md` (the rendered reference the Duplicates rows link to) here. Those files are build artifacts, so they are gitignored. `pages.yml` rebuilds them at deploy, which keeps the deployed example in step with the current code. It needs the `sc-compose` CLI on PATH.

# Example: Jev evidence report

A one-page web report built from the run files of one real plan-anchoring cycle. It is an example of what a report over the Jev run ledger could show, not a shipped feature.

Open `index.html` in a browser. It is self-contained (data, CSS and script inline, no network).

## Source data

The anchor-run evidence for atm-core phase-bo (`docs/plans/phase-bo/anchor-runs/` at `randlee/atm-core@f97d33e`), later removed from that repo in PR #2331. The report shows only data from those files.

## Sections

1. **Question tuning:** the 13 candidate question sets ranked by cells (17 cases × 5 roles) that were exact, confident and stable. It also shows the four Jev calls per case for the best candidate, plotted against the 0.6 and 0.8 lines, and the weakest call per role.
2. **Anchor rubric:** how many draft anchors failed each role, in round 0 and round 2.
3. **Fixture calibration:** the weakest answer for each anchor's pass and fail fixture, with earlier re-runs shown, and a count of which question was weakest.
4. **Plan gate:** for each bead, the anchors it was judged against, shaded by the weakest answer.
5. **Triage:** the bead edits, per round, that made the gate pass, with before and after text.
6. **Ledger gaps:** fields the run files lack that a run ledger needs: commit, durable inputs, a Jev run ID and a reviewer link.

## Rebuild

```sh
python3 extract.py <anchor-runs-dir> report-data.json
python3 build.py report-data.json            # writes index.html from template.html
```

`extract.py` reads `testability/result.md`, `testability/oracle.json`, `rubric/*.json`, `check-fixtures-{dev,plan}/` (every run file, not only `summary.json`, which covers just the first round) and `plan-gate/`. For other data you must change three things it hard-codes for this run: the `source` block, the best candidate (`E1`) and the bead IDs (`atm-bo-1` to `atm-bo-7`).

## Findings from this run

- No question set was sealed. Every candidate's shortfall was on the faithful role, and it was low confidence, not a wrong answer. E1's byte-identical replication dropped one case to 0.58.
- On the plan gate, "addressed" was the weakest answer in 20 of the 36 fixtures Jev judged.
- All 7 beads pass. The weakest answer was 0.66.

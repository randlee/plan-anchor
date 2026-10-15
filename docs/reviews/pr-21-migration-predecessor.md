# PR #21 follow-up: migration predecessor integrity

Parent: `ehrvs:fix/calibration-contract-compatibility`, PR #21.
Pinned parent head: `1d93c254077f3bc82e6766da1d034d452e7f8c9b`.
Child branch: `fix/calibration-migration-predecessor`.
The follow-up was authored as a dependent git layer because the original PR
comes from a fork. At the maintainer's direction, these additions and the
schema/release work are being consolidated into Erik's original PR #21 through
its enabled maintainer-edits permission, preserving his commits.

## Finding 1 — P2: first-event migrations can omit their predecessor

The parent allows `supersedes: null` for event 1 and requires an object only
from event 2 onward. That also permits a first event labeled
`protocol_re_evaluated` to omit the decision being migrated. Both JSON schemas
and the relational contract accepted that case, contrary to the requirement
to preserve prior decisions during migration.

Fix: require an object when the event is a protocol migration, independently
of its index. Preserve null for a genuine first non-migration event. Enforce
the same rule in the request schema, result schema, and relational validator.
The validator also rejects later events with missing predecessor objects,
matching the existing schema constraint.

## Finding 2 — test coverage: request history represented the result

The calibration test helper copied the entire result history into the request.
That meant a first-event test supplied an already populated request, while the
result's before-history digest represented an empty history.

Fix: supply all but the newly appended event as request history. Assert that
fresh requests are empty and later requests contain only prior events. Derive
the before-history digest from that same request state.

## Verification

Offline regression coverage preserves valid fresh histories and migrations
with predecessor objects, rejects missing first-migration predecessors in both
schemas and both relational entry points, rejects later null predecessors,
and checks the actual empty-before/one-event-after transition. No live Jev or
GitHub GraphQL calls are required.

## Scope

This follow-up retains PR #21's evaluator-ID compatibility and fresh-history
support. It does not change evaluation questions, confidence thresholds, or
the frozen corpus. The response-envelope repair and release preparation in
PR #22 were authored separately and are included in that consolidation.

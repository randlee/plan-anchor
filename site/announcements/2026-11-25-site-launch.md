# plan-anchor has a home — anchors, gates and drift reports on the web

**Released:** November 25, 2026

plan-anchor exists because the specific things you say during planning get
compressed out of an agent's context. You ask for something concrete, and
several rounds later the work quietly goes another way. plan-anchor captures
those statements as numbered anchors and judges the plan, then the delivered
work, against them.

## What is new

This repository now publishes a static site:

- **Reports** — gate runs and drift findings, date-stamped
- **Diagrams** — how capture, planning gate and development gate fit together
- **Announcements** — this page

## Honest state

The site is live and the navigation is real; the first gate reports appear here
as runs are published. Nothing is backfilled or invented to make the page look
busy.

## How it is built

Only sources are committed. Index pages are generated at deploy time by
`scripts/build-site.py`, so the site cannot drift from the records it describes.

# Installed-wheel integration

Unit tests remain offline. Run the live variants only with authorization to send
the bundled, synthetic test inputs to TypeSafe. They reuse the existing judge
and batch inputs, invoke the real installed client, and check the resulting
artifact, batch correlation and durable log, and invalid-key auth/redaction.
They supply no answer fixtures and assert no model probability or timing.

Use the canonical sc-agent prerelease installer to checksum-verify and install
the chosen matched wheels in a fresh Python 3.11+ environment. Install pytest,
jsonschema, PyYAML and the supported sc-compose Python package there; put the
released sc-compose CLI on PATH. Keep a source archive at the wheel's exact
sc-agent commit: the command reuses its report renderer. Pass the TypeSafe credential variable
name from the sc-agent export explicitly; plan-anchor does not parse SDK source
for credential names. A missing renderer fails before any live test runs.

Export credentials with sc-agent's existing `scripts/integration.py --export-env`
to a new temporary mode-0600 `.env` outside a checkout. The integration command
passes only the TypeSafe key to its child and consumes/deletes the file even on
failure. Its configuration-only client partials put actual wheel logs in the
test scratch directory; they do not replace responses or transport.

Run from a clean plan-anchor checkout, setting these paths and pins to the actual
installed prerelease and source revision:

```sh
python scripts/integration.py --venv "$PRERELEASE_VENV" \
  --env-file "$TEMP_CREDENTIALS" --key-variable "$TYPESAFE_KEY_VARIABLE" \
  --sc-agent-source "$SC_AGENT_SOURCE" \
  --source-sha "$PLAN_ANCHOR_SHA" --pin-tag "$SC_AGENT_TAG" --pin-sha "$SC_AGENT_SHA" \
  --platform macos --results /tmp/plan-anchor-integration-macos
```

For an authorized source build, build the wheel with maturin at the exact SDK
commit and install that wheel into a fresh environment. Pass `--pin-tag source-build`
and `--wheel-version` with its distribution version; `--pin-sha` remains the actual
SDK source commit. The report identifies a source build rather than a published tag.

Repeat the same command in a disposable Colima container with `--platform colima`
and its Linux prerelease installation. Each run writes JUnit and renders
`site/reports/integration/<platform>.xhtml` from that JUnit. The report records the
plan-anchor source separately from the sc-agent wheel pin. FAIL remains FAIL;
a missing key or dependency fails rather than inventing a result. Commit and
push the panels as part of the run; do not copy private plan inputs or logs.

For a clean account such as atmbench, put Python, the canonical install root,
selector directory, tools, caches, both source archives and temporary files in
one disposable directory. A temporary manifest copy may change only installation
and selector locations; preserve asset selection, checksums and verify commands.
Remove that directory, installed environments and credentials after collecting
the reports, including on failure. Remove the disposable Colima container too.

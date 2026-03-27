# Example FixTape Session Walkthrough

This example shows how a real debugging session looks with FixTape.

**Scenario:** A billing webhook is duplicating charges when the payment
provider retries a failed delivery.

## 1. Start the session

```bash
fixtape start "billing webhook duplicates charges on retry"
```

## 2. Capture the investigation

```bash
# Add notes as you discover clues
fixtape note "Reproduced with retry header present — charges appear twice"
fixtape note "Idempotency key exists in payload but is ignored on retry path"

# Capture test runs
fixtape capture pytest tests/test_billing.py -k duplicate

# Attach evidence files
fixtape attach trace examples/sample-traceback.txt
fixtape attach payload examples/sample-payload.json

# Link to your ticket tracker
fixtape link ticket PAY-456
```

## 3. Finish with a verdict

```bash
fixtape finish \
  --verdict fixed \
  --summary "Retry path now validates idempotency key before processing" \
  --ref commit:abc123
```

## 4. Review what was captured

```bash
# See the full session
fixtape show

# Compact digest
fixtape digest

# Search your debugging history
fixtape search "idempotency"

# Export for a teammate
fixtape export billing-handoff.zip
```

## Generated artifacts

After `fixtape finish`, the session directory contains:

```
.fixtape/sessions/2025-03-27_..._billing-webhook-duplicates-charges/
  session.json              # Session metadata
  events.jsonl              # Full event timeline
  commands/                 # Captured stdout/stderr
  artifacts/                # Attached files (trace, payload)
  generated/
    debug-summary.md        # Structured debugging report
    handoff.md              # Team handoff package
    repro.sh                # Reproduction script
    session-digest.json     # Compact machine-readable digest
    session-digest.md       # Human-readable digest
    parsed-artifacts.json   # Extracted failure signals
    regression-draft.json   # Suggested regression test inputs
    timeline.json           # Full event timeline as JSON
```

## Sample files

- [sample-traceback.txt](sample-traceback.txt) — Python traceback
- [sample-payload.json](sample-payload.json) — Failing webhook payload
- [sample-debug-summary.md](sample-debug-summary.md) — Generated summary

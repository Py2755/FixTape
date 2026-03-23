# Demo Session Walkthrough

This is the kind of workflow FixTape is designed to support.

## Scenario

An engineer is debugging a retry-related billing bug that causes duplicate invoice processing.

## Commands

```powershell
fixtape start "duplicate invoice on retry" --tag incident --tag billing --include-last 40m
fixtape note "Issue shows up only when provider retries with same external id"
fixtape capture pytest tests/test_billing.py -k duplicate
fixtape attach payload failing_invoice.json
fixtape attach trace traceback.txt
fixtape snapshot
fixtape note "Likely missing idempotency check on retry path"
fixtape capture --repro python scripts/replay_invoice.py failing_invoice.json
fixtape finish --verdict fixed --summary "Retry flow now checks idempotency key before write" --include-last 20m
fixtape show
```

## Result

The engineer ends the session with:
- a debugging summary ready to share,
- the exact commands that mattered,
- attached evidence,
- Git context around the fix,
- a regression test TODO that can be turned into a real test next,
- and enough flight-recorder context to recover from a late session start.

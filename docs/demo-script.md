# Demo Script

Use this script when recording a terminal demo or explaining FixTape live.

## Goal

Show that FixTape is not just logging commands. It preserves the debugging trail as a reusable engineering artifact.

## Suggested flow

1. Start a session.
2. Add a note that narrows the failure condition.
3. Run a failing command through FixTape.
4. Attach a payload or trace.
5. Snapshot Git state.
6. Run a reproducible command.
7. Finish the session.
8. Show the summary and search the session history.

## Example commands

```powershell
fixtape start "duplicate invoice on retry" --tag incident --tag billing
fixtape note "Provider retries the same event id after timeout"
fixtape run pytest tests/test_billing.py -k duplicate
fixtape attach payload failing_invoice.json
fixtape snapshot
fixtape run --repro python scripts/replay_invoice.py failing_invoice.json
fixtape finish --verdict fixed --summary "Retry path now checks idempotency key"
fixtape show
fixtape search retry
```

## Talking points

- The session is local-first and file-based.
- The debugging trail survives beyond the final commit.
- The result is useful for handoff, review, and regression work.

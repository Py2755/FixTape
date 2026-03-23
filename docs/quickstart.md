# Quickstart

## Install

```powershell
python -m pip install -e .
```

## Run a full session

```powershell
fixtape start "duplicate invoice on retry" --tag incident --tag billing
fixtape note "Reproduces only when retry header is present"
fixtape run pytest tests/test_billing.py -k duplicate
fixtape attach trace traceback.txt
fixtape attach payload failing_invoice.json
fixtape snapshot

# apply the fix

fixtape note "Idempotency key was ignored in retry path"
fixtape run --repro python scripts/replay_invoice.py failing_invoice.json
fixtape finish --verdict fixed --summary "Retry path now uses idempotency key"
```

## Inspect the result

```powershell
fixtape list
fixtape show
fixtape search idempotency
fixtape export .\fixtape-session.zip
```

## What gets created

```text
.fixtape/
  sessions/
    <session-id>/
      session.json
      events.jsonl
      commands/
      artifacts/
      snapshots/
      generated/
        debug-summary.md
        repro.ps1|repro.sh
        regression-test.todo.md
        timeline.json
```

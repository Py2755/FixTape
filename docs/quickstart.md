# Quickstart

## Install

```powershell
python -m pip install -e .
```

## Optional shell helpers

```powershell
Invoke-Expression (& fixtape shell-init powershell)
```

This gives you:
- `ft` for `fixtape capture -- ...`
- `ftr` for `fixtape capture --repro -- ...`
- `ftnote` for notes
- `ftsnap` for snapshots
- `ftshow` and `ftsearch` for revisiting sessions
- `ftdoctor` and `ftsuggest` for flight-recorder guidance

## Optional shell hooks

If you want zero-touch pre-session capture, enable hooks:

```powershell
Invoke-Expression (& fixtape shell-init powershell --mode all)
ftenable
```

Hooks now keep a rolling flight recorder even before a session exists.
For full stdout/stderr capture, use `fixtape capture`.

You can inspect the buffer and get a start recommendation with:

```powershell
fixtape doctor --window 40m
fixtape suggest-start --window 20m
```

## Search old debugging work

```powershell
fixtape search "retry idempotency"
fixtape search "pytest duplicate" --field commands
fixtape reindex
fixtape link ticket PAY-123
fixtape refs
```

Search results are ranked, and the CLI prints compact snippets with the field that matched.
The local cross-session index is stored in `.fixtape/session-index.json`.

## Run a full session

```powershell
fixtape start "duplicate invoice on retry" --tag incident --tag billing --include-last 40m
fixtape note "Reproduces only when retry header is present"
fixtape capture pytest tests/test_billing.py -k duplicate
fixtape attach trace traceback.txt
fixtape attach payload failing_invoice.json
fixtape snapshot

# apply the fix

fixtape note "Idempotency key was ignored in retry path"
fixtape capture --repro python scripts/replay_invoice.py failing_invoice.json
fixtape finish --verdict fixed --summary "Retry path now uses idempotency key" --ref ticket:PAY-123 --ref commit:abc123 --include-last 20m
```

## Inspect the result

```powershell
fixtape list
fixtape show
fixtape search idempotency
fixtape doctor --window 40m
fixtape suggest-start --window 20m
fixtape export .\fixtape-session.zip
```

The exported archive now starts with handoff-first files:
- `HANDOFF.md`
- `SUMMARY.md`
- `REPRO_SCRIPT`
- `REGRESSION_TEST_TODO.md`
- `metadata.json`

The finished session also includes:
- `generated/regression-test.todo.md`
- `generated/regression-draft.json`
- `generated/parsed-artifacts.json`

These files use the captured notes, repro commands, refs, and payload-like artifacts to draft the next regression test step.
Parsed failure signals are extracted from attached traces and captured command outputs when FixTape can detect them.

## What gets created

```text
.fixtape/
  flight-recorder/
    buffer.jsonl
    outputs/
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

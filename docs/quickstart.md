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
- `ft` for `fixtape run -- ...`
- `ftr` for `fixtape run --repro -- ...`
- `ftnote` for notes
- `ftsnap` for snapshots
- `ftshow` and `ftsearch` for revisiting sessions

## Optional shell hooks

If you want lower-friction capture, enable hooks:

```powershell
Invoke-Expression (& fixtape shell-init powershell --mode all)
ftenable
```

Hook mode captures command line, exit code, and working directory for ordinary shell commands.
For full stdout/stderr capture, keep using `fixtape run`.

## Search old debugging work

```powershell
fixtape search "retry idempotency"
fixtape search "pytest duplicate" --field commands
fixtape reindex
```

Search results are ranked, and the CLI prints compact snippets with the field that matched.
The local cross-session index is stored in `.fixtape/session-index.json`.

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
fixtape finish --verdict fixed --summary "Retry path now uses idempotency key" --ref ticket:PAY-123 --ref commit:abc123
```

## Inspect the result

```powershell
fixtape list
fixtape show
fixtape search idempotency
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

These files use the captured notes, repro commands, refs, and payload-like artifacts to draft the next regression test step.

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

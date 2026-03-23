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
```

Search results are ranked, and the CLI prints compact snippets with the field that matched.

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

# FixTape

FixTape is a local-first CLI that turns debugging sessions into reusable engineering artifacts.

Instead of ending a hard bug hunt with just a patch and a vague memory, FixTape gives you:
- a structured debugging summary,
- a reproducible command trail,
- attached evidence such as traces, logs, and payloads,
- Git-aware snapshots of the code context,
- and a handoff package another engineer can actually use.

## Why it exists

The expensive part of debugging is often not the final fix. It is the path to understanding:
- what reproduced the bug,
- which commands mattered,
- what traces were observed,
- what changed in the repo,
- and how to verify the bug is really gone.

Most teams lose that path.

FixTape preserves it.

## Current scope

This repository implements an MVP with:
- `start` to create a debugging session,
- `status` to inspect the active session,
- `note` to add time-stamped observations,
- `run` to execute and capture commands,
- `attach` to preserve traces, logs, payloads, and other evidence,
- `snapshot` to capture Git context,
- `finish` to generate final artifacts,
- `export` to bundle a finished session into a zip file.

## Example flow

```powershell
fixtape start "billing webhook duplicates charges"
fixtape note "Can reproduce only with retry header present"
fixtape run pytest tests/test_webhook.py -k duplicate
fixtape attach trace traceback.txt
fixtape attach payload failing_event.json
fixtape snapshot

# fix the bug

fixtape note "Root cause was idempotency key ignored on retry path"
fixtape run --repro python scripts/replay_event.py failing_event.json
fixtape finish --verdict fixed --summary "Retry path now respects idempotency keys"
```

After finishing, the session contains:
- `session.json`
- `events.jsonl`
- `generated/debug-summary.md`
- `generated/repro.ps1` or `generated/repro.sh`
- `generated/regression-test.todo.md`
- copied artifacts and command outputs

## Installation

### Local editable install

```powershell
python -m pip install -e .
```

### Run tests

```powershell
python -m unittest discover -s tests -v
```

## Session storage

FixTape stores sessions locally inside:

```text
.fixtape/
  active-session.json
  sessions/
    <session-id>/
```

If FixTape runs inside a Git repository, it stores data at the repository root. Otherwise it stores data in the current working directory.

## Design choices

- Local-first: no backend, no sync requirement, inspectable files.
- Explicit capture: the MVP captures commands run through `fixtape run`.
- Git-aware: snapshots include branch, commit, dirty state, and diffs.
- File-based artifacts: every session is portable and easy to inspect.

## Roadmap

Planned directions after the MVP:
- shell integration for passive command capture,
- richer stack trace extraction,
- IDE integration,
- search across old debugging sessions,
- AI-generated summaries and regression test drafts.

## License

MIT

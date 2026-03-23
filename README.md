# FixTape

[![CI](https://github.com/Py2755/FixTape/actions/workflows/ci.yml/badge.svg)](https://github.com/Py2755/FixTape/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

FixTape is a local-first CLI that turns debugging sessions into reusable engineering artifacts.

Instead of ending a hard bug hunt with just a patch and a vague memory, FixTape gives you:
- a structured debugging summary,
- a reproducible command trail,
- attached evidence such as traces, logs, and payloads,
- Git-aware snapshots of the code context,
- and a handoff package another engineer can actually use.

## The pitch

When a hard bug is finally fixed, most teams still lose the most expensive part of the work:
- how the issue was reproduced,
- which commands mattered,
- which traces were useful,
- which hypothesis was discarded,
- why the final fix won,
- and how the team can prove the bug stays fixed.

FixTape preserves that path.

It is not a debugger.
It is not a note-taking app.
It is a debugging memory layer.

## Why it feels different

Most developer tools help you:
- write code faster,
- inspect state faster,
- or generate code faster.

FixTape helps you **not lose the investigation itself**.

That makes it useful for:
- backend debugging,
- flaky integration failures,
- infra incidents,
- reproducible handoffs,
- and turning debugging effort into regression assets.

## What you get

At the end of a debugging session, FixTape can generate:
- `generated/debug-summary.md`
- `generated/repro.ps1` or `generated/repro.sh`
- `generated/regression-test.todo.md`
- `generated/timeline.json`
- copied artifacts such as traces, logs, payloads, and command outputs

## Command set

Current commands:
- `fixtape start <title>`
- `fixtape status`
- `fixtape note "<text>"`
- `fixtape run [--repro] <command...>`
- `fixtape attach <kind> <path>`
- `fixtape snapshot`
- `fixtape finish --verdict <fixed|unresolved|handoff|needs-more-data>`
- `fixtape list`
- `fixtape show [session-id]`
- `fixtape export <destination.zip>`

## 60-Second Quickstart

### 1. Install

```powershell
python -m pip install -e .
```

### 2. Start a session

```powershell
fixtape start "billing webhook duplicates charges" --tag incident --tag backend
```

### 3. Capture the investigation

```powershell
fixtape note "Can reproduce only with retry header present"
fixtape run pytest tests/test_webhook.py -k duplicate
fixtape attach trace traceback.txt
fixtape attach payload failing_event.json
fixtape snapshot
```

### 4. Finalize the fix

```powershell
fixtape note "Root cause was idempotency key ignored on retry path"
fixtape run --repro python scripts/replay_event.py failing_event.json
fixtape finish --verdict fixed --summary "Retry path now respects idempotency keys"
```

### 5. Revisit the result

```powershell
fixtape list
fixtape show
fixtape export .\fixtape-session.zip
```

## Example session flow

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
fixtape show
```

See more:
- [Quickstart](docs/quickstart.md)
- [Architecture](docs/architecture.md)
- [Demo Session Walkthrough](docs/demo-session.md)

## Session storage

FixTape stores sessions locally inside:

```text
.fixtape/
  active-session.json
  last-session.json
  sessions/
    <session-id>/
      session.json
      events.jsonl
      commands/
      artifacts/
      snapshots/
      generated/
```

If FixTape runs inside a Git repository, it stores data at the repository root. Otherwise it stores data in the current working directory.

## Design principles

- Local-first: no backend, no sync requirement, inspectable files.
- Explicit capture: the MVP captures commands run through `fixtape run`.
- Git-aware: snapshots include branch, commit, dirty state, and diffs.
- File-based artifacts: every session is portable and easy to inspect.
- Useful without AI: the generated package should already help a human engineer.

## Project status

FixTape is currently an early but working MVP.

Already included:
- runnable CLI
- session lifecycle
- command capture
- artifact capture
- Git snapshots
- markdown/script generation
- unit tests
- GitHub Actions CI

Planned next:
- shell integration for passive capture
- richer trace parsing
- search across old sessions
- IDE integration
- AI-assisted summarization
- regression-test draft generation from evidence

## Development

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Contributing guide:
- [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT

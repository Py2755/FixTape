# Architecture

FixTape is intentionally simple in the MVP.

## Core components

### CLI
The CLI is the user entry point. It translates commands into session actions and generators.

### Session store
The session store owns:
- session creation,
- active session pointers,
- finished session pointers,
- event persistence,
- session lookup and listing.

### Event timeline
Each important action is stored as an append-only event in `events.jsonl`.

This keeps the model:
- inspectable,
- debuggable,
- future-proof for search or AI summarization,
- and easy to export.

### Git integration
Git is treated as a first-class source of debugging context:
- branch,
- commit,
- dirty state,
- changed files,
- and diff snapshots.

### Output generators
FixTape currently generates:
- markdown summaries,
- repro scripts,
- regression test TODO scaffolds,
- and machine-readable timelines.

## Why the MVP is explicit

The project deliberately does not start with:
- shell hooks,
- IDE plugins,
- passive machine-wide capture.

The explicit command model is more reliable, easier to test, and enough to prove the core value before heavier integrations are added.

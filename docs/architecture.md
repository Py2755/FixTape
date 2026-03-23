# Architecture

FixTape is still intentionally local and inspectable, but it is no longer only a narrow MVP.

## Core components

### CLI
The CLI is the user entry point. It translates commands into session actions and generators.

### Session store
The session store owns:
- session creation,
- active session pointers,
- finished session pointers,
- event persistence,
- session lookup and listing,
- pre-session promotion into formal sessions,
- and history-driven suggestion enrichment.

### Flight recorder
The flight recorder owns:
- rolling pre-session command memory,
- bounded output storage for `fixtape capture`,
- recorder pressure / doctor status,
- and incident-start suggestions before a formal session exists.

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
- incident kickoff bundles,
- session digests,
- handoff docs,
- and machine-readable timelines.

## Why the product is still explicit where it matters

The project deliberately still avoids:
- hidden network services,
- opaque remote storage,
- and fully automatic session creation.

FixTape now has zero-touch pre-session capture and type-aware start suggestions, but it still keeps the transition into a real session explicit and inspectable.

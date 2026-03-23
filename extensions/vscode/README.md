# FixTape VS Code Extension

This extension surfaces FixTape sessions from the current workspace inside VS Code.

## Features

- Shows active and recent FixTape sessions in a dedicated sidebar.
- Opens `handoff.md` or `debug-summary.md` directly from the tree.
- Reveals the underlying session folder in the OS file explorer.
- Refreshes automatically when `.fixtape` content changes.

## Current scope

This extension is intentionally lightweight:
- it reads the existing `.fixtape/` store,
- it does not reimplement FixTape core logic,
- it focuses on visibility and quick access.

## Expected workspace layout

The extension looks for:

```text
.fixtape/
  active-session.json
  sessions/
    <session-id>/
```

## Suggested usage

1. Use the FixTape CLI in the repository.
2. Open the same workspace in VS Code.
3. Open the `FixTape` activity bar icon.
4. Open the latest handoff or summary from the session list.

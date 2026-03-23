# VS Code Extension

FixTape includes a lightweight VS Code extension under `extensions/vscode`.

## What it does

- shows active and recent FixTape sessions in the VS Code activity bar,
- opens `handoff.md` or `debug-summary.md` directly,
- reveals the session folder in the OS file explorer,
- refreshes when `.fixtape` content changes inside the workspace.

## Why it exists

The CLI remains the source of truth for capture.
The extension exists to make finished and active sessions visible inside the editor without rebuilding the product around VS Code.

## Run it locally

1. Open the repository in VS Code.
2. Open the `extensions/vscode` folder or keep it inside the current multi-root workspace.
3. Press `F5` from the extension folder in VS Code to launch an Extension Development Host.
4. Open a workspace that contains `.fixtape/`.
5. Use the `FixTape` activity bar icon.

## Current scope

This first version focuses on:
- session visibility,
- quick artifact opening,
- low maintenance cost,
- no duplication of CLI business logic.

Future work can add:
- active session status actions,
- tighter workspace commands,
- richer session details,
- direct links into generated artifacts and timelines.

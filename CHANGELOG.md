# Changelog

All notable changes to this project will be documented in this file.

## [0.1.8] - 2026-03-24

### Added
- Parsed artifact and stack trace extraction.
- `generated/parsed-artifacts.json` with extracted failure signals.

### Improved
- Summaries and handoff docs now surface parsed failure signals from traces, logs, and command outputs.

## [0.1.7] - 2026-03-24

### Added
- Cross-session indexing via `.fixtape/session-index.json`.
- `fixtape reindex` to rebuild the local session index.

### Improved
- `fixtape list` and `fixtape search` now run on a maintained session index rather than scanning all session files on each call.

## [0.1.6] - 2026-03-24

### Added
- Lightweight VS Code extension for FixTape session visibility.
- Activity bar view with active and recent sessions.
- Commands to open session handoff/summary files and reveal the underlying session folder.

### Improved
- Repository docs now include a dedicated VS Code extension guide.

## [0.1.5] - 2026-03-24

### Added
- Smarter regression-test drafting from captured debugging evidence.
- `generated/regression-draft.json` with machine-readable suggested test inputs.

### Improved
- `regression-test.todo.md` now includes suggested test name, candidate fixtures, repro commands, linked refs, and assertion ideas.

## [0.1.4] - 2026-03-23

### Added
- Richer handoff bundles with top-level `HANDOFF.md`, `SUMMARY.md`, repro entry points, and `metadata.json`.
- Support for linking related refs during `finish`, such as `ticket:PAY-123` or `commit:abc123`.
- Generated `handoff.md` inside each finished session.

### Improved
- Exported archives now open on a summary-first structure instead of forcing readers to browse the raw session tree first.

## [0.1.3] - 2026-03-23

### Added
- Ranked session search with weighted field scoring.
- Compact field-labeled snippets in `fixtape search` output.

### Improved
- Search now prefers stronger matches such as title and summary over weaker low-signal matches.

## [0.1.2] - 2026-03-23

### Added
- Low-friction shell hook capture mode via `fixtape shell-init --mode all`.
- Hidden shell hook recording path for command line, exit code, and working directory capture.
- Summary output now shows whether a command was captured by `fixtape run` or by a shell hook.

### Improved
- Quickstart and README now document when to use full capture versus hook-based capture.

## [0.1.1] - 2026-03-23

### Added
- Demo asset and demo script for a stronger first impression in the repository.
- `fixtape search --field ...` filtering for more focused session lookup.
- `fixtape shell-init` for PowerShell and POSIX helper wrappers.
- Roadmap documentation for the next public iterations.

## [0.1.0] - 2026-03-23

### Added
- Initial FixTape MVP.
- Local-first CLI workflow for debugging sessions.
- Session lifecycle commands: `start`, `status`, `note`, `finish`.
- Command capture with `run`.
- Evidence capture with `attach`.
- Git snapshots with `snapshot`.
- Session discovery commands: `list`, `show`, `search`, `export`.
- Shell helper generation with `shell-init`.
- Generated outputs for summaries, repro scripts, and regression TODOs.
- Automated tests and GitHub Actions CI.

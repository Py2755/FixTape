# Changelog

All notable changes to this project will be documented in this file.

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

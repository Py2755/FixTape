# Changelog

All notable changes to this project will be documented in this file.

## [0.2.2] - 2026-03-24

### Improved
- `fixtape suggest-start` now scores recent failures by incident type instead of relying mostly on generic burst detection.
- Runtime, HTTP, SQL, test, and infra-style failures now compete with different weights, so specific incident classes beat generic `process_failure`.
- Historical family playbooks, hotspots, and outcome rates now boost suggestion confidence and can switch the recommendation from `start` to `kickoff`.
- `fixtape doctor` now shows the same enriched, type-aware start recommendation as `fixtape suggest-start`.

## [0.2.1] - 2026-03-24

### Added
- `fixtape suggest-start` for incident-start suggestions based on recent failure bursts and traceback-style signals.
- Shell notify support with cooldown-based suppression to avoid repeating the same start suggestion every prompt render.

### Improved
- `fixtape doctor` now surfaces the best current session-start suggestion when recent activity looks like an investigation.
- Shell helpers now expose `ftsuggest` and can print a one-line “start a session now” hint instead of forcing an automatic session open.

## [0.2.0] - 2026-03-24

### Added
- Zero-touch flight recorder under `.fixtape/flight-recorder` with rolling pre-session command memory.
- `fixtape doctor` for inspecting buffered command history and recorder pressure.
- `fixtape promote --include-last ...` for importing recent buffered commands into the active session.
- `fixtape capture` for full stdout/stderr capture even when no FixTape session is active yet.
- `--include-last ...` support on `start`, `kickoff`, and `finish`.

### Improved
- Shell helpers now default to an always-on recorder flow after `fixtape shell-init`.
- Debugging can start as a low-friction black box and be promoted into a formal FixTape session later.
- Captured command history now survives the common "I forgot to start FixTape first" failure mode.

## [0.1.16] - 2026-03-24

### Added
- `fixtape triage` for matching a current signal against the best historical playbooks, recipes, hotspots, and sessions.
- `fixtape kickoff` for starting a new session with a generated incident kickoff bundle from historical context.
- Generated kickoff artifacts: `generated/incident-kickoff.json` and `generated/incident-kickoff.md`.

### Improved
- Historical guidance can now be used at the very start of an incident, not only after enough evidence has already been captured.
- Repeatable playbooks and recipes now feed directly into session startup UX.

## [0.1.15] - 2026-03-24

### Added
- `fixtape playbooks` for repeatable troubleshooting playbooks across recurring failure families.
- `fixtape recipes` for concrete fix recipes around repeated failure buckets and repro paths.

### Improved
- Session history now turns repeated incidents into reusable starter steps, artifact checklists, and stable entry points.
- Regression and digest history now feed practical guidance, not just analytics.

## [0.1.14] - 2026-03-24

### Added
- `fixtape regressions` for recurring regression memory across historical sessions.
- `fixtape outcomes` for fix outcome analytics across families and verdict distributions.

### Improved
- Cross-session indexing now carries regression draft fields such as suggested test name, entry point, and fixture candidates.
- Session history can now be read as repeatable regression opportunities and outcome analytics, not only incident patterns.

## [0.1.13] - 2026-03-24

### Added
- `fixtape digest` for a compact per-session debugging brief.
- `generated/session-digest.json` and `generated/session-digest.md` for finished sessions.
- `fixtape lenses` for root-cause lenses across families, areas, and repeated digest themes.

### Improved
- Cross-session indexing now includes digest-level fields such as likely area, root-cause hint, and next step.
- Session history can now be read as compressed debugging briefs instead of only raw timelines.

## [0.1.12] - 2026-03-24

### Added
- `fixtape clusters` for connected incident clusters across historical sessions.
- `fixtape hotspots` for recurring failure hotspots by file, exception, family, status, or fingerprint.

### Improved
- Cross-session intelligence now rolls up related failures into reusable clusters instead of only pairwise matches.
- Hotspot analysis now surfaces repeat-problem areas with open-session pressure and recency.

## [0.1.11] - 2026-03-24

### Added
- Smarter failure parsing for Python, Node, Java, HTTP, SQL, pytest, and command-level failures.
- Structured parsed artifact metadata such as fingerprints, exception types, file hints, and status codes.
- `fixtape similar` for finding related debugging sessions.
- `fixtape patterns` for surfacing recurring failure fingerprints across history.

### Improved
- `fixtape search` can now match parsed failure signals directly through `--field signals`.
- `fixtape show` now surfaces nearby similar sessions.
- Cross-session indexing now stores structured failure data for better retrieval and clustering.

## [0.1.10] - 2026-03-24

### Added
- Separate packaging workflows for the Python CLI and the VS Code extension.
- Publishing documentation for building wheels, sdists, and `.vsix` artifacts.
- Extension packaging metadata and ignore rules for cleaner VSIX output.

### Improved
- Package versions are now aligned across Python metadata, runtime version, and extension metadata.

## [0.1.9] - 2026-03-24

### Added
- `fixtape link` and `fixtape refs` commands for direct ref management.
- Search support for linked refs such as tickets and commits.

### Improved
- `show` and `status` now surface linked refs directly.

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

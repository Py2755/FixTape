# Contributing to FixTape

Thanks for contributing to FixTape.

## Principles

Please keep changes aligned with the product shape of the project:
- local-first,
- inspectable files over hidden state,
- explicit capture over fragile magic,
- useful even without AI integrations.

## Development setup

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Project structure

- `src/fixtape/` contains the CLI and core logic.
- `src/fixtape/generators/` contains human-readable and machine-readable output generation.
- `tests/` contains the current automated test suite.

## Contribution guidelines

- Keep the CLI predictable and scriptable.
- Prefer portable file-based designs for the MVP.
- Add tests for behavior changes.
- Keep docs updated when commands or generated outputs change.
- Avoid adding network requirements to the core product loop.

## Pull request checklist

- The project still installs.
- `python -m unittest discover -s tests -v` passes.
- README and docs still reflect the current CLI behavior.
- New commands or options include at least one test.

## Good first areas

- shell integration helpers,
- better summary rendering,
- richer artifact kinds,
- session search and filtering,
- regression-test drafting,
- editor integrations.

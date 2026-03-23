# Publishing

FixTape now has two delivery surfaces:

1. the Python CLI
2. the VS Code extension

## CLI packaging

The CLI is packaged from the repository root through the Python project in `pyproject.toml`.

Local build example:

```powershell
python -m pip install --upgrade build
python -m build --no-isolation
```

Expected outputs:
- `dist/*.whl`
- `dist/*.tar.gz`

## VS Code extension packaging

The extension lives in `extensions/vscode`.

Local packaging example:

```powershell
cd extensions/vscode
npm ci
npx @vscode/vsce package
```

Expected output:
- `extensions/vscode/*.vsix`

## GitHub workflows

The repository now includes:
- `.github/workflows/package-cli.yml`
- `.github/workflows/package-vscode-extension.yml`

These workflows package the CLI and the VS Code extension separately on version tags.

## Version alignment

For release tags, keep these versions aligned:
- `pyproject.toml`
- `src/fixtape/__init__.py`
- `extensions/vscode/package.json`

That keeps packaged artifacts, runtime metadata, and extension metadata consistent for each published release.

## Local Windows note

On this repository, `python -m build` may fail under isolated build mode on some Windows setups because of a local `pip/build` Unicode decoding issue.

If that happens locally, use:

```powershell
python -m build --no-isolation
```

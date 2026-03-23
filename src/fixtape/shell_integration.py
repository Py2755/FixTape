from __future__ import annotations


def render_shell_init(shell_name: str) -> str:
    normalized = shell_name.lower()
    if normalized in {"powershell", "pwsh"}:
        return _powershell_init()
    if normalized in {"bash", "zsh", "sh"}:
        return _posix_init()
    raise ValueError(f"Unsupported shell for init: {shell_name}")


def _powershell_init() -> str:
    return """function ft {
    if ($args.Count -eq 0) {
        Write-Error "Usage: ft <command...>"
        return
    }
    fixtape run -- @args
}

function ftr {
    if ($args.Count -eq 0) {
        Write-Error "Usage: ftr <command...>"
        return
    }
    fixtape run --repro -- @args
}

function ftnote {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$Text)
    fixtape note ($Text -join " ")
}

function ftsnap {
    fixtape snapshot
}

function ftshow {
    fixtape show @args
}

function ftsearch {
    fixtape search @args
}
"""


def _posix_init() -> str:
    return """ft() {
  fixtape run -- "$@"
}

ftr() {
  fixtape run --repro -- "$@"
}

ftnote() {
  fixtape note "$*"
}

ftsnap() {
  fixtape snapshot
}

ftshow() {
  fixtape show "$@"
}

ftsearch() {
  fixtape search "$@"
}
"""

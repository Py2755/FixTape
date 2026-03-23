from __future__ import annotations


def render_shell_init(shell_name: str, mode: str = "all") -> str:
    normalized = shell_name.lower()
    if normalized in {"powershell", "pwsh"}:
        return _powershell_init(mode)
    if normalized in {"bash", "zsh", "sh"}:
        return _posix_init(normalized, mode)
    raise ValueError(f"Unsupported shell for init: {shell_name}")


def _powershell_init(mode: str) -> str:
    helpers = """function ft {
    if ($args.Count -eq 0) {
        Write-Error "Usage: ft <command...>"
        return
    }
    fixtape capture -- @args
}

function ftr {
    if ($args.Count -eq 0) {
        Write-Error "Usage: ftr <command...>"
        return
    }
    fixtape capture --repro -- @args
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

function ftdoctor {
    fixtape doctor @args
}

function ftpromote {
    fixtape promote @args
}
"""
    hooks = """
function ftenable {
    $env:FIXTAPE_HOOKS_ENABLED = '1'
    Write-Host 'FixTape flight recorder enabled.'
}

function ftdisable {
    $env:FIXTAPE_HOOKS_ENABLED = '0'
    Write-Host 'FixTape flight recorder disabled.'
}

if (-not $global:FixTapeOriginalPrompt) {
    $global:FixTapeOriginalPrompt = $function:prompt
}
if (-not $global:FixTapeLastHistoryId) {
    $global:FixTapeLastHistoryId = 0
}
if (-not $env:FIXTAPE_HOOKS_ENABLED) {
    $env:FIXTAPE_HOOKS_ENABLED = '1'
}

function global:prompt {
    $exitCode = if ($?) { 0 } elseif ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } else { 1 }
    $history = Get-History -Count 1 -ErrorAction SilentlyContinue
    if ($env:FIXTAPE_HOOKS_ENABLED -eq '1' -and $history -and $history.Id -ne $global:FixTapeLastHistoryId) {
        $global:FixTapeLastHistoryId = $history.Id
        $cmd = [string]$history.CommandLine
        if ($cmd -and $cmd -notmatch '^(fixtape|ft|ftr|ftnote|ftsnap|ftshow|ftsearch|ftdoctor|ftpromote|ftenable|ftdisable)\\b') {
            fixtape record-shell-command --command $cmd --exit-code $exitCode --shell powershell --cwd (Get-Location).Path --captured-via shell_hook *> $null
        }
    }
    & $global:FixTapeOriginalPrompt
}
"""
    return _render_mode(helpers, hooks, mode)


def _posix_init(shell_name: str, mode: str) -> str:
    helpers = """ft() {
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

ftdoctor() {
  fixtape doctor "$@"
}

ftpromote() {
  fixtape promote "$@"
}
"""
    hooks_common = """
ftenable() {
  export FIXTAPE_HOOKS_ENABLED=1
  echo "FixTape flight recorder enabled."
}

ftdisable() {
  export FIXTAPE_HOOKS_ENABLED=0
  echo "FixTape flight recorder disabled."
}

: "${FIXTAPE_HOOKS_ENABLED:=1}"
"""
    if shell_name in {"bash", "sh"}:
        hooks = hooks_common + r"""
_fixtape_capture_last_command() {
  local exit_code=$?
  [[ "${FIXTAPE_HOOKS_ENABLED:-0}" != "1" ]] && return
  local hist_line hist_num cmd
  hist_line="$(history 1 2>/dev/null)"
  [[ -z "$hist_line" ]] && return
  hist_num="${hist_line%% *}"
  cmd="${hist_line#*  }"
  [[ "$hist_num" == "${_FIXTAPE_LAST_HIST:-}" ]] && return
  _FIXTAPE_LAST_HIST="$hist_num"
  case "$cmd" in
    fixtape*|ft\ *|ftr\ *|ftnote*|ftsnap*|ftshow*|ftsearch*|ftdoctor*|ftpromote*|ftenable*|ftdisable*)
      return
      ;;
  esac
  fixtape record-shell-command --command "$cmd" --exit-code "$exit_code" --shell bash --cwd "$PWD" --captured-via shell_hook >/dev/null 2>&1 || true
}

if [[ -n "${PROMPT_COMMAND:-}" ]]; then
  PROMPT_COMMAND="_fixtape_capture_last_command; ${PROMPT_COMMAND}"
else
  PROMPT_COMMAND="_fixtape_capture_last_command"
fi
"""
    else:
        hooks = hooks_common + r"""
_fixtape_capture_last_command() {
  local exit_code=$?
  [[ "${FIXTAPE_HOOKS_ENABLED:-0}" != "1" ]] && return
  local last_cmd="$(fc -ln -1 2>/dev/null)"
  [[ -z "$last_cmd" ]] && return
  [[ "$last_cmd" == "${_FIXTAPE_LAST_CMD:-}" ]] && return
  _FIXTAPE_LAST_CMD="$last_cmd"
  case "$last_cmd" in
    fixtape*|ft\ *|ftr\ *|ftnote*|ftsnap*|ftshow*|ftsearch*|ftdoctor*|ftpromote*|ftenable*|ftdisable*)
      return
      ;;
  esac
  fixtape record-shell-command --command "$last_cmd" --exit-code "$exit_code" --shell zsh --cwd "$PWD" --captured-via shell_hook >/dev/null 2>&1 || true
}

typeset -ga precmd_functions
if (( ${precmd_functions[(Ie)_fixtape_capture_last_command]} == 0 )); then
  precmd_functions+=(_fixtape_capture_last_command)
fi
"""
    return _render_mode(helpers, hooks, mode)


def _render_mode(helpers: str, hooks: str, mode: str) -> str:
    if mode == "helpers":
        return helpers
    if mode == "hooks":
        return hooks
    if mode == "all":
        return helpers + "\n" + hooks
    raise ValueError(f"Unsupported shell init mode: {mode}")

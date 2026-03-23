from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from fixtape.config import (
    flight_recorder_buffer_path,
    flight_recorder_outputs_root,
    flight_recorder_root,
    flight_recorder_suggestion_state_path,
)
from fixtape.utils import (
    append_jsonl,
    ensure_dir,
    format_bytes,
    iso_now,
    iso_to_datetime,
    parse_time_window,
    read_json,
    read_jsonl,
    write_json,
    utc_now,
)

DEFAULT_RETENTION_WINDOW = "60m"
DEFAULT_MAX_BYTES = 48 * 1024 * 1024
PREVIEW_LIMIT = 240
DEFAULT_SUGGEST_WINDOW = "20m"
DEFAULT_SUGGEST_COOLDOWN = "15m"


class PreSessionRecorder:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.root = flight_recorder_root(self.cwd)
        self.buffer_path = flight_recorder_buffer_path(self.cwd)
        self.outputs_dir = flight_recorder_outputs_root(self.cwd)
        self.suggestion_state_path = flight_recorder_suggestion_state_path(self.cwd)
        self.max_bytes = int(os.environ.get("FIXTAPE_RECORDER_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
        self.retention_window = os.environ.get("FIXTAPE_RECORDER_WINDOW", DEFAULT_RETENTION_WINDOW)

    def record_command(
        self,
        *,
        command: str,
        exit_code: int,
        shell: str,
        cwd: str | None,
        timestamp: str | None = None,
        duration_ms: float | None = None,
        args: list[str] | None = None,
        repro: bool = False,
        stdout_text: str | None = None,
        stderr_text: str | None = None,
        captured_via: str = "shell_hook",
    ) -> dict[str, Any]:
        event_timestamp = timestamp or iso_now()
        entry_id = self._build_entry_id(event_timestamp, command)
        stdout_meta = self._write_output(entry_id, "stdout", stdout_text)
        stderr_meta = self._write_output(entry_id, "stderr", stderr_text)
        event = {
            "type": "command_ran",
            "timestamp": event_timestamp,
            "duration_ms": duration_ms,
            "repro": bool(repro),
            "command": command,
            "args": args,
            "exit_code": int(exit_code),
            "stdout_file": stdout_meta["path"],
            "stderr_file": stderr_meta["path"],
            "stdout_sha256": stdout_meta["sha256"],
            "stderr_sha256": stderr_meta["sha256"],
            "stdout_preview": stdout_meta["preview"],
            "stderr_preview": stderr_meta["preview"],
            "stdout_bytes": stdout_meta["size"],
            "stderr_bytes": stderr_meta["size"],
            "captured_via": captured_via,
            "shell": shell,
            "cwd": cwd,
            "pre_session_id": entry_id,
            "recorded_before_session": True,
        }
        append_jsonl(self.buffer_path, event)
        self._prune()
        return event

    def recent_entries(self, window: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        entries = self._load_entries()
        if window:
            cutoff = utc_now() - parse_time_window(window)
            entries = [entry for entry in entries if self._entry_datetime(entry) and self._entry_datetime(entry) >= cutoff]
        if limit is not None:
            return entries[-max(0, limit) :]
        return entries

    def status(self, window: str | None = None, preview_limit: int = 5) -> dict[str, Any]:
        entries = self.recent_entries(window=window)
        suggestion = self.suggest_session_start(window=window or DEFAULT_SUGGEST_WINDOW, cooldown="")
        if not entries:
            return {
                "entry_count": 0,
                "buffer_bytes": 0,
                "output_bytes": 0,
                "max_bytes": self.max_bytes,
                "retention_window": self.retention_window,
                "recent": [],
                "oldest_timestamp": None,
                "newest_timestamp": None,
                "suggestion": suggestion,
            }
        output_bytes = sum(self._entry_size_bytes(entry) for entry in entries)
        return {
            "entry_count": len(entries),
            "buffer_bytes": self.buffer_path.stat().st_size if self.buffer_path.exists() else 0,
            "output_bytes": output_bytes,
            "max_bytes": self.max_bytes,
            "retention_window": self.retention_window,
            "oldest_timestamp": entries[0].get("timestamp"),
            "newest_timestamp": entries[-1].get("timestamp"),
            "recent": [
                {
                    "timestamp": entry.get("timestamp"),
                    "command": entry.get("command"),
                    "exit_code": entry.get("exit_code"),
                    "captured_via": entry.get("captured_via"),
                    "has_output": bool(entry.get("stdout_file") or entry.get("stderr_file")),
                }
                for entry in entries[-preview_limit:]
            ],
            "output_bytes_human": format_bytes(output_bytes),
            "max_bytes_human": format_bytes(self.max_bytes),
            "suggestion": suggestion,
        }

    def suggest_session_start(
        self,
        *,
        window: str = DEFAULT_SUGGEST_WINDOW,
        cooldown: str = DEFAULT_SUGGEST_COOLDOWN,
        active_session: bool = False,
        mark_seen: bool = False,
    ) -> dict[str, Any] | None:
        if active_session:
            return None
        entries = self.recent_entries(window=window)
        if len(entries) < 2:
            return None

        failing = [entry for entry in entries if int(entry.get("exit_code") or 0) != 0]
        if not failing:
            return None

        repeated_fail = self._repeated_fail_bucket(failing)
        trace_signals = [entry for entry in failing if self._has_trace_signal(entry)]
        recent_fail_span_minutes = self._fail_span_minutes(failing)
        score = 0
        reasons: list[str] = []

        if len(failing) >= 2:
            score += 30
            reasons.append(f"{len(failing)} non-zero commands in {window}")
        if len(failing) >= 3:
            score += 15
        if recent_fail_span_minutes <= 10:
            score += 10
            reasons.append(f"fail burst over {recent_fail_span_minutes}m")
        if repeated_fail:
            score += 20
            reasons.append(f"repeated target: {repeated_fail}")
        if trace_signals:
            score += 35
            reasons.append("traceback or exception signal detected")
        if int(entries[-1].get("exit_code") or 0) != 0:
            score += 10

        if score < 45:
            return None

        query = self._build_query(failing, trace_signals, repeated_fail)
        title = self._build_title(query, repeated_fail)
        signature = hashlib.sha256(
            "|".join(str(entry.get("pre_session_id") or "") for entry in failing[-4:]).encode("utf-8")
        ).hexdigest()
        suggestion = {
            "score": score,
            "confidence": "high" if score >= 70 else "medium",
            "query": query,
            "title": title,
            "include_last": window,
            "reason": reasons[0] if reasons else "recent non-zero failure activity",
            "reasons": reasons,
            "command_start": f'fixtape start "{title}" --include-last {window}',
            "command_kickoff": f'fixtape kickoff "{title}" --query "{query}" --include-last {window}',
            "signature": signature,
        }

        if cooldown and self._is_suppressed(signature, cooldown):
            return None
        if mark_seen:
            self._mark_suggestion_seen(signature)
        return suggestion

    def _load_entries(self) -> list[dict[str, Any]]:
        entries = read_jsonl(self.buffer_path)
        entries.sort(key=lambda item: str(item.get("timestamp") or ""))
        return entries

    def _entry_datetime(self, entry: dict[str, Any]):
        return iso_to_datetime(str(entry.get("timestamp") or "")) if entry.get("timestamp") else None

    def _entry_size_bytes(self, entry: dict[str, Any]) -> int:
        size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        for key in ("stdout_file", "stderr_file"):
            path_text = entry.get(key)
            if path_text:
                path = Path(path_text)
                if path.exists():
                    size += path.stat().st_size
        return size

    def _build_entry_id(self, timestamp: str, command: str) -> str:
        digest = hashlib.sha256(f"{timestamp}|{command}".encode("utf-8")).hexdigest()[:12]
        safe_timestamp = timestamp.replace(":", "").replace("+", "_").replace(".", "_")
        return f"{safe_timestamp}_{digest}"

    def _write_output(self, entry_id: str, stream: str, text: str | None) -> dict[str, Any]:
        if not text:
            return {"path": None, "sha256": None, "preview": None, "size": 0}
        sanitized = self._sanitize_text(text)
        path = ensure_dir(self.outputs_dir) / f"{entry_id}_{stream}.txt"
        path.write_text(sanitized, encoding="utf-8")
        return {
            "path": str(path),
            "sha256": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
            "preview": self._preview_text(sanitized),
            "size": path.stat().st_size,
        }

    def _preview_text(self, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= PREVIEW_LIMIT:
            return compact
        return compact[: PREVIEW_LIMIT - 3] + "..."

    def _sanitize_text(self, text: str) -> str:
        patterns = [
            (re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s]+)"), r"\1[REDACTED]"),
            (re.compile(r"(?i)\b(password|token|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)=([^\s]+)"), r"\1=[REDACTED]"),
            (re.compile(r"(?i)\b(gh[pousr]_[A-Za-z0-9_]+)\b"), "[REDACTED_GITHUB_TOKEN]"),
        ]
        sanitized = text
        for pattern, replacement in patterns:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def _has_trace_signal(self, entry: dict[str, Any]) -> bool:
        text_parts = [
            str(entry.get("command") or ""),
            str(entry.get("stderr_preview") or ""),
            str(entry.get("stdout_preview") or ""),
        ]
        combined = " ".join(text_parts).lower()
        patterns = [
            "traceback",
            "exception",
            "runtimeerror",
            "valueerror",
            "typeerror",
            "assertionerror",
            "pytest",
            "failed",
            "panic",
        ]
        return any(token in combined for token in patterns)

    def _repeated_fail_bucket(self, failing: list[dict[str, Any]]) -> str | None:
        buckets: dict[str, int] = {}
        for entry in failing:
            bucket = self._command_focus(entry)
            if bucket:
                buckets[bucket] = buckets.get(bucket, 0) + 1
        if not buckets:
            return None
        bucket, count = sorted(buckets.items(), key=lambda item: (item[1], item[0]), reverse=True)[0]
        return bucket if count >= 2 else None

    def _command_focus(self, entry: dict[str, Any]) -> str | None:
        args = entry.get("args")
        tokens = [str(item) for item in args] if isinstance(args, list) else str(entry.get("command") or "").split()
        interesting = []
        for token in tokens:
            cleaned = token.strip().strip('"').strip("'")
            if not cleaned or cleaned.startswith("-") or cleaned in {"python", "python.exe", "pytest", "node", "npm", "pnpm"}:
                continue
            if "/" in cleaned or "\\" in cleaned or "." in cleaned:
                interesting.append(cleaned)
            elif re.fullmatch(r"[a-z0-9_-]{4,}", cleaned.lower()):
                interesting.append(cleaned)
        if interesting:
            return interesting[0]
        if tokens:
            return tokens[0]
        return None

    def _fail_span_minutes(self, failing: list[dict[str, Any]]) -> int:
        datetimes = [self._entry_datetime(entry) for entry in failing if self._entry_datetime(entry)]
        if len(datetimes) < 2:
            return 0
        delta_seconds = max((max(datetimes) - min(datetimes)).total_seconds(), 0)
        return max(1, round(delta_seconds / 60))

    def _build_query(self, failing: list[dict[str, Any]], trace_signals: list[dict[str, Any]], repeated_fail: str | None) -> str:
        if trace_signals:
            for entry in reversed(trace_signals):
                snippet = str(entry.get("stderr_preview") or entry.get("stdout_preview") or "").strip()
                if snippet:
                    compact = " ".join(snippet.split())
                    return compact[:120]
        last_command = str(failing[-1].get("command") or "").strip()
        if repeated_fail and last_command:
            return f"{repeated_fail} {last_command}"[:120]
        if last_command:
            return last_command[:120]
        return "recent failure burst"

    def _build_title(self, query: str, repeated_fail: str | None) -> str:
        base = repeated_fail or query
        tokens = re.findall(r"[a-z0-9_.-]+", base.lower())
        filtered = [
            token
            for token in tokens
            if token not in {"traceback", "exception", "pytest", "python", "failed", "error", "runtimeerror", "typeerror"}
        ]
        if not filtered:
            filtered = ["incident"]
        return " ".join(filtered[:4])

    def _is_suppressed(self, signature: str, cooldown: str) -> bool:
        state = read_json(self.suggestion_state_path, default={}) or {}
        if state.get("signature") != signature:
            return False
        seen_at = iso_to_datetime(str(state.get("seen_at") or ""))
        if seen_at is None:
            return False
        return seen_at >= (utc_now() - parse_time_window(cooldown))

    def _mark_suggestion_seen(self, signature: str) -> None:
        write_json(self.suggestion_state_path, {"signature": signature, "seen_at": iso_now()})

    def _prune(self) -> None:
        entries = self._load_entries()
        if not entries:
            return

        cutoff = utc_now() - parse_time_window(self.retention_window)
        kept = [entry for entry in entries if self._entry_datetime(entry) and self._entry_datetime(entry) >= cutoff]
        if not kept:
            kept = entries[-1:]

        while kept and sum(self._entry_size_bytes(entry) for entry in kept) > self.max_bytes:
            dropped = kept.pop(0)
            self._delete_output_file(dropped.get("stdout_file"))
            self._delete_output_file(dropped.get("stderr_file"))

        kept_ids = {entry.get("pre_session_id") for entry in kept}
        for entry in entries:
            if entry.get("pre_session_id") not in kept_ids:
                self._delete_output_file(entry.get("stdout_file"))
                self._delete_output_file(entry.get("stderr_file"))

        if kept:
            lines = [json.dumps(entry, ensure_ascii=False) for entry in kept]
            self.buffer_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif self.buffer_path.exists():
            self.buffer_path.unlink()

    def _delete_output_file(self, path_text: Any) -> None:
        if not path_text:
            return
        path = Path(str(path_text))
        if path.exists():
            path.unlink()

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from fixtape.config import flight_recorder_buffer_path, flight_recorder_outputs_root, flight_recorder_root
from fixtape.utils import append_jsonl, ensure_dir, format_bytes, iso_now, iso_to_datetime, parse_time_window, read_jsonl, utc_now

DEFAULT_RETENTION_WINDOW = "60m"
DEFAULT_MAX_BYTES = 48 * 1024 * 1024
PREVIEW_LIMIT = 240


class PreSessionRecorder:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.root = flight_recorder_root(self.cwd)
        self.buffer_path = flight_recorder_buffer_path(self.cwd)
        self.outputs_dir = flight_recorder_outputs_root(self.cwd)
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
        }

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

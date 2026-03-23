from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def build_parsed_artifacts(events: list[dict[str, Any]]) -> dict[str, Any]:
    parsed_items: list[dict[str, Any]] = []

    for event in events:
        if event["type"] == "artifact_attached":
            stored_path = event.get("stored_path")
            if stored_path:
                parsed_items.append(
                    _parse_text_artifact(
                        Path(str(stored_path)),
                        source_type="attached_artifact",
                        label=str(event.get("kind") or "artifact"),
                    )
                )
        elif event["type"] == "command_ran":
            for file_key, label in (("stderr_file", "command_stderr"), ("stdout_file", "command_stdout")):
                target = event.get(file_key)
                if target:
                    parsed_items.append(
                        _parse_text_artifact(
                            Path(str(target)),
                            source_type="command_output",
                            label=label,
                            command=str(event.get("command") or ""),
                        )
                    )

    parsed_items = [item for item in parsed_items if item["signals"]]

    signal_count = sum(len(item["signals"]) for item in parsed_items)
    top_signals: list[str] = []
    for item in parsed_items:
        for signal in item["signals"][:2]:
            top_signals.append(signal["headline"])
    top_signals = top_signals[:5]

    return {
        "artifact_count": len(parsed_items),
        "signal_count": signal_count,
        "top_signals": top_signals,
        "items": parsed_items,
    }


def _parse_text_artifact(path: Path, source_type: str, label: str, command: str | None = None) -> dict[str, Any]:
    payload = {
        "source_type": source_type,
        "label": label,
        "path": str(path),
        "command": command,
        "signals": [],
    }
    if not path.exists() or not path.is_file():
        return payload

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return payload

    text = text[:50000]
    signals = []

    python_signal = _parse_python_traceback(text)
    if python_signal:
        signals.append(python_signal)

    node_signal = _parse_node_stack(text)
    if node_signal:
        signals.append(node_signal)

    generic_signal = _parse_generic_error_signal(text)
    if generic_signal:
        signals.append(generic_signal)

    payload["signals"] = _dedupe_signals(signals)
    return payload


def _parse_python_traceback(text: str) -> dict[str, Any] | None:
    if "Traceback (most recent call last):" not in text:
        return None
    lines = text.splitlines()
    frames: list[str] = []
    exception_type = "PythonError"
    message = ""
    collecting = False
    for line in lines:
        if line.startswith("Traceback (most recent call last):"):
            collecting = True
            continue
        if not collecting:
            continue
        stripped = line.strip()
        frame_match = re.search(r'File "([^"]+)", line (\d+), in (.+)', stripped)
        if frame_match:
            frames.append(f"{frame_match.group(1)}:{frame_match.group(2)} in {frame_match.group(3)}")
            continue
        if stripped and ":" in stripped:
            exception_type, _, message = stripped.partition(":")
            break
    if not frames and not message:
        return None
    headline = f"{exception_type.strip()}: {message.strip()}".strip(": ").strip()
    return {
        "parser": "python_traceback",
        "headline": headline or exception_type,
        "exception_type": exception_type.strip(),
        "message": message.strip(),
        "frames": frames[:6],
    }


def _parse_node_stack(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    error_line = None
    frames: list[str] = []
    for line in lines:
        stripped = line.strip()
        if error_line is None and re.search(r"(Error|Exception):", stripped):
            error_line = stripped
            continue
        if error_line and stripped.startswith("at "):
            frames.append(stripped)
    if not error_line:
        return None
    return {
        "parser": "node_stack",
        "headline": error_line,
        "frames": frames[:6],
    }


def _parse_generic_error_signal(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    matches = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in ["error", "exception", "traceback", "failed", "fatal"]):
            matches.append(stripped)
    if not matches:
        return None
    return {
        "parser": "generic_error",
        "headline": matches[0],
        "lines": matches[:5],
    }


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        key = (str(signal.get("parser")), str(signal.get("headline")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
    return deduped

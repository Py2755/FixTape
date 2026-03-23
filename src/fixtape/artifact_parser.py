from __future__ import annotations

import re
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "http",
    "https",
    "error",
    "exception",
    "failed",
    "fatal",
    "traceback",
}


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
                elif file_key == "stderr_file":
                    inline_signal = _parse_inline_command_failure(event)
                    if inline_signal:
                        parsed_items.append(
                            {
                                "source_type": "command_event",
                                "label": "command_event",
                                "path": None,
                                "command": str(event.get("command") or ""),
                                "signals": [inline_signal],
                            }
                        )

    parsed_items = [item for item in parsed_items if item["signals"]]
    normalized = _normalize_parsed_items(parsed_items)

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
        "fingerprints": normalized["fingerprints"],
        "exception_types": normalized["exception_types"],
        "families": normalized["families"],
        "status_codes": normalized["status_codes"],
        "file_hints": normalized["file_hints"],
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

    for parser in (
        _parse_python_traceback,
        _parse_node_stack,
        _parse_java_stack,
        _parse_http_failure,
        _parse_sql_failure,
        _parse_pytest_failure,
        _parse_generic_error_signal,
    ):
        signal = parser(text)
        if signal:
            signals.append(_finalize_signal(signal))

    payload["signals"] = _dedupe_signals(signals)
    return payload


def _parse_inline_command_failure(event: dict[str, Any]) -> dict[str, Any] | None:
    command = str(event.get("command") or "").strip()
    exit_code = event.get("exit_code")
    if not command or exit_code in (None, 0):
        return None
    return _finalize_signal(
        {
            "parser": "command_failure",
            "family": "process_failure",
            "headline": f"Command failed with exit code {exit_code}: {command}",
            "message": f"exit code {exit_code}",
            "command": command,
            "exception_type": "CommandFailure",
        }
    )


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
        "family": "python_exception",
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
        if error_line is None and re.search(r"^(?:\w+)?(?:Error|Exception):", stripped):
            error_line = stripped
            continue
        if error_line and stripped.startswith("at "):
            frames.append(stripped)
    if not error_line:
        return None
    exception_type, message = _split_exception_line(error_line)
    return {
        "parser": "node_stack",
        "family": "node_exception",
        "headline": error_line,
        "exception_type": exception_type,
        "message": message,
        "frames": frames[:6],
    }


def _parse_java_stack(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    error_line = None
    frames: list[str] = []
    for line in lines:
        stripped = line.strip()
        if error_line is None and re.match(r"^(?:[\w$.]+\.)?[\w$]*(Exception|Error):", stripped):
            error_line = stripped
            continue
        if error_line and stripped.startswith("at "):
            frames.append(stripped)
    if not error_line:
        return None
    exception_type, message = _split_exception_line(error_line)
    return {
        "parser": "java_stack",
        "family": "java_exception",
        "headline": error_line,
        "exception_type": exception_type,
        "message": message,
        "frames": frames[:6],
    }


def _parse_http_failure(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    status_code = None
    headline = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = re.search(r"\bHTTP\s+(4\d{2}|5\d{2})\b", stripped, re.IGNORECASE)
        if not match:
            match = re.search(r"\bstatus(?:\s+code)?[=: ]+(4\d{2}|5\d{2})\b", stripped, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(4\d{2}|5\d{2})\b", stripped)
            if match and "http" not in stripped.lower() and "status" not in stripped.lower():
                match = None
        if match:
            status_code = match.group(1)
            headline = stripped
            break

    if not status_code or not headline:
        return None
    return {
        "parser": "http_failure",
        "family": "http_failure",
        "headline": headline,
        "status_code": int(status_code),
        "message": headline,
        "exception_type": f"HTTP {status_code}",
    }


def _parse_sql_failure(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in ["sqlstate", "syntax error at or near", "duplicate key value", "constraint failed"]):
            return {
                "parser": "sql_failure",
                "family": "sql_failure",
                "headline": stripped,
                "message": stripped,
                "exception_type": "SqlError",
            }
    return None


def _parse_pytest_failure(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("E       "):
            headline = stripped[8:].strip()
            context = lines[max(0, index - 1)].strip() if index > 0 else ""
            return {
                "parser": "pytest_failure",
                "family": "test_failure",
                "headline": headline or "pytest failure",
                "message": headline,
                "context": context,
                "exception_type": _split_exception_line(headline)[0] if ":" in headline else "AssertionError",
            }
    return None


def _parse_generic_error_signal(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    matches = []
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) > 240:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in ["error", "exception", "traceback", "failed", "fatal", "panic"]):
            matches.append(stripped)
    if not matches:
        return None
    headline = matches[0]
    return {
        "parser": "generic_error",
        "family": "generic_failure",
        "headline": headline,
        "lines": matches[:5],
        "message": headline,
        "exception_type": _split_exception_line(headline)[0] if ":" in headline else "GenericFailure",
    }


def _split_exception_line(line: str) -> tuple[str, str]:
    if ":" not in line:
        return line.strip(), ""
    exception_type, _, message = line.partition(":")
    return exception_type.strip(), message.strip()


def _finalize_signal(signal: dict[str, Any]) -> dict[str, Any]:
    frames = [str(frame) for frame in signal.get("frames") or [] if str(frame).strip()]
    exception_type = str(signal.get("exception_type") or "").strip()
    message = str(signal.get("message") or signal.get("headline") or "").strip()
    family = str(signal.get("family") or "generic_failure")
    fingerprint = _build_fingerprint(
        parser=str(signal.get("parser") or "generic_error"),
        family=family,
        exception_type=exception_type,
        message=message,
        frames=frames,
        status_code=signal.get("status_code"),
    )
    file_hints = _extract_file_hints(frames)
    keywords = _extract_keywords(" ".join([signal.get("headline", ""), message, *frames]))
    finalized = dict(signal)
    finalized["frames"] = frames[:6]
    finalized["family"] = family
    finalized["fingerprint"] = fingerprint
    finalized["file_hints"] = file_hints[:6]
    finalized["keywords"] = keywords[:10]
    return finalized


def _build_fingerprint(
    parser: str,
    family: str,
    exception_type: str,
    message: str,
    frames: list[str],
    status_code: Any = None,
) -> str:
    top_frame = frames[0] if frames else ""
    top_file = _extract_file_hints([top_frame])[0] if top_frame and _extract_file_hints([top_frame]) else ""
    normalized_message = _normalize_text_for_fingerprint(message)
    parts = [family or parser]
    if exception_type:
        parts.append(exception_type.lower())
    elif status_code:
        parts.append(f"status-{status_code}")
    if normalized_message:
        parts.append(normalized_message)
    if top_file:
        parts.append(top_file.lower())
    return "|".join(parts[:4])


def _normalize_text_for_fingerprint(text: str, max_parts: int = 4) -> str:
    tokens = []
    for raw in TOKEN_RE.findall(text.lower()):
        if raw.isdigit():
            continue
        if raw in STOPWORDS:
            continue
        normalized = re.sub(r"\d+", "#", raw)
        if normalized and normalized not in tokens:
            tokens.append(normalized)
        if len(tokens) >= max_parts:
            break
    return "-".join(tokens)


def _extract_keywords(text: str, max_items: int = 8) -> list[str]:
    keywords: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        if len(raw) < 3 or raw in STOPWORDS:
            continue
        normalized = re.sub(r"\d+", "#", raw)
        if normalized not in keywords:
            keywords.append(normalized)
        if len(keywords) >= max_items:
            break
    return keywords


def _extract_file_hints(frames: list[str]) -> list[str]:
    hints: list[str] = []
    for frame in frames:
        matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|java|go|rb|php|sql))", frame)
        for match in matches:
            if match not in hints:
                hints.append(match)
    return hints


def _normalize_parsed_items(parsed_items: list[dict[str, Any]]) -> dict[str, list[Any]]:
    fingerprints: list[str] = []
    exception_types: list[str] = []
    families: list[str] = []
    status_codes: list[int] = []
    file_hints: list[str] = []

    for item in parsed_items:
        for signal in item["signals"]:
            fingerprint = signal.get("fingerprint")
            if fingerprint and fingerprint not in fingerprints:
                fingerprints.append(str(fingerprint))
            exception_type = signal.get("exception_type")
            if exception_type and exception_type not in exception_types:
                exception_types.append(str(exception_type))
            family = signal.get("family")
            if family and family not in families:
                families.append(str(family))
            status_code = signal.get("status_code")
            if isinstance(status_code, int) and status_code not in status_codes:
                status_codes.append(status_code)
            for hint in signal.get("file_hints") or []:
                if hint not in file_hints:
                    file_hints.append(str(hint))

    return {
        "fingerprints": fingerprints[:12],
        "exception_types": exception_types[:12],
        "families": families[:12],
        "status_codes": status_codes[:12],
        "file_hints": file_hints[:12],
    }


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        key = (str(signal.get("parser")), str(signal.get("fingerprint") or signal.get("headline")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
    return deduped

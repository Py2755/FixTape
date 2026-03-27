from __future__ import annotations

import argparse

from fixtape.session_store import NoActiveSessionError, SessionStore
from fixtape.shell_integration import render_shell_init
from fixtape.utils import format_bytes


def _print(msg: str) -> None:
    print(msg)


def handle_shell_init(store: SessionStore, args: argparse.Namespace) -> int:
    _print(render_shell_init(args.shell, mode=args.mode))
    return 0


def handle_record_shell_command(store: SessionStore, args: argparse.Namespace) -> int:
    event = store.record_pre_session_command(
        command=args.command_text,
        exit_code=args.exit_code,
        shell=args.shell,
        cwd=args.cwd,
        captured_via=args.captured_via,
    )
    try:
        _, session_dir = store.load_session()
    except NoActiveSessionError:
        return 0
    store.promote_buffer_entry(session_dir, event, source="shell_hook")
    return 0


def handle_doctor(store: SessionStore, args: argparse.Namespace) -> int:
    status = store.recorder_status(window=args.window)
    status["suggestion"] = store.suggest_session_start(window=args.window or "20m", cooldown="")
    _print("Flight recorder:")
    _print(f"Retention window: {status['retention_window']}")
    _print(f"Buffered commands: {status['entry_count']}")
    _print(f"Output bytes: {status.get('output_bytes_human') or format_bytes(status['output_bytes'])}")
    _print(f"Buffer budget: {status.get('max_bytes_human') or format_bytes(status['max_bytes'])}")
    if status["newest_timestamp"]:
        _print(f"Newest command: {status['newest_timestamp']}")
    if not status["recent"]:
        _print("Recent commands: none")
        if status.get("suggestion"):
            _print("Suggestion:")
            _print(f"  {status['suggestion']['command_kickoff']}")
        return 0
    _print("Recent commands:")
    for item in status["recent"]:
        marker = "output" if item["has_output"] else "history"
        _print(f"  {item['timestamp']} | exit={item['exit_code']} | {marker} | {item['command']}")
    suggestion = status.get("suggestion")
    if suggestion:
        _print("Suggestion:")
        _print(f"  incident type: {suggestion['incident_type_label']}")
        _print(f"  confidence: {suggestion['confidence']} (score={suggestion['score']})")
        _print(f"  reason: {suggestion['reason']}")
        if suggestion.get("top_signal"):
            _print(f"  top signal: {suggestion['top_signal']}")
        if suggestion.get("recommended_first_move"):
            _print(f"  first move: {suggestion['recommended_first_move']}")
        if suggestion.get("entry_point"):
            _print(f"  entry point: {suggestion['entry_point']}")
        if suggestion.get("capture_first"):
            _print(f"  capture first: {', '.join(suggestion['capture_first'])}")
        _print(f"  recommended: {suggestion['recommended_mode']}")
        _print(f"  start: {suggestion['command_start']}")
        _print(f"  kickoff: {suggestion['command_kickoff']}")
    return 0


def handle_promote(store: SessionStore, args: argparse.Namespace) -> int:
    session, session_dir = store.load_session()
    result = store.include_recent_buffer(session_dir, args.include_last, source="promote")
    _print(f"Promoted buffered commands into session: {session['id']}")
    _print(f"Imported: {result['count']} from the last {args.include_last}")
    return 0


def handle_suggest_start(store: SessionStore, args: argparse.Namespace) -> int:
    suggestion = store.suggest_session_start(
        window=args.window,
        cooldown=args.cooldown if args.shell_notify else "",
        mark_seen=args.shell_notify,
    )
    if not suggestion:
        return 0
    if args.shell_notify:
        _print(
            "FixTape: "
            f"{suggestion['incident_type_label']} detected. "
            f"Suggested: {suggestion['recommended_command']}"
        )
        return 0
    _print("Suggested FixTape session start:")
    _print(f"Incident type: {suggestion['incident_type_label']}")
    _print(f"Confidence: {suggestion['confidence']} (score={suggestion['score']})")
    _print(f"Reason: {suggestion['reason']}")
    if suggestion["reasons"]:
        _print(f"Signals: {', '.join(suggestion['reasons'])}")
    if suggestion.get("top_signal"):
        _print(f"Top signal: {suggestion['top_signal']}")
    if suggestion.get("recommended_first_move"):
        _print(f"First move: {suggestion['recommended_first_move']}")
    if suggestion.get("entry_point"):
        _print(f"Entry point: {suggestion['entry_point']}")
    if suggestion.get("capture_first"):
        _print(f"Capture first: {', '.join(suggestion['capture_first'])}")
    if suggestion.get("playbook"):
        _print(f"Playbook: {suggestion['playbook']['label']}")
    if suggestion.get("hotspot"):
        _print(f"Hotspot: {suggestion['hotspot']['label']}")
    _print(f"Recommended mode: {suggestion['recommended_mode']}")
    _print(f"Recommended: {suggestion['recommended_command']}")
    _print(f"Start: {suggestion['command_start']}")
    _print(f"Kickoff: {suggestion['command_kickoff']}")
    return 0

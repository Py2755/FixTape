from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from fixtape.artifacts import copy_artifact
from fixtape.artifact_parser import build_parsed_artifacts
from fixtape.cli.parser import VALID_ARTIFACT_KINDS
from fixtape.generators.digest import build_session_digest, generate_session_digest
from fixtape.generators.repro import generate_repro_script
from fixtape.generators.summary import generate_summary
from fixtape.generators.todo import build_regression_draft, generate_regression_todo
from fixtape.generators.handoff import generate_handoff
from fixtape.runner import run_command, capture_command
from fixtape.session_store import FixTapeError, NoActiveSessionError, SessionStore
from fixtape.utils import iso_now, write_json


def _print(msg: str) -> None:
    print(msg)


def handle_start(store: SessionStore, args: argparse.Namespace) -> int:
    session_dir = store.start_session(args.title, args.tags, include_last=args.include_last)
    _print(f"Started FixTape session: {session_dir.name}")
    _print(f"Session directory: {session_dir}")
    if args.include_last:
        import_result = store.include_recent_buffer(session_dir, args.include_last, source="start")
        _print(f"Imported buffered commands: {import_result['count']} from the last {args.include_last}")
    return 0


def handle_status(store: SessionStore, args: argparse.Namespace) -> int:
    session, session_dir = store.load_session()
    counts = store.session_counts(session_dir)
    _print(f"Active session: {session['title']}")
    _print(f"Session ID: {session['id']}")
    _print(f"Created: {session['created_at']}")
    _print(f"Notes: {counts['notes']}")
    _print(f"Commands: {counts['commands']}")
    _print(f"Artifacts: {counts['artifacts']}")
    _print(f"Snapshots: {counts['snapshots']}")
    if session.get("refs"):
        _print(f"Refs: {', '.join(session['refs'])}")
    if session.get("initial_git_state"):
        state = session["initial_git_state"]
        _print(f"Git branch: {state.get('branch') or 'unknown'}")
        _print(f"Git dirty: {state.get('dirty')}")
    return 0


def handle_note(store: SessionStore, args: argparse.Namespace) -> int:
    store.add_note(args.text)
    _print("Note captured.")
    return 0


def handle_link(store: SessionStore, args: argparse.Namespace) -> int:
    if args.kind == "current-commit":
        ref = store.current_commit_ref()
    else:
        if not args.value:
            raise FixTapeError(f"Reference value is required for kind: {args.kind}")
        ref_value = args.value.strip()
        if not ref_value:
            raise FixTapeError("Reference value cannot be empty.")
        ref = ref_value if args.kind == "other" else f"{args.kind}:{ref_value}"

    refs = store.add_refs([ref])
    _print(f"Linked ref: {ref}")
    _print(f"Current refs: {', '.join(refs)}")
    return 0


def handle_refs(store: SessionStore, args: argparse.Namespace) -> int:
    session = store.resolve_session_for_refs(args.session_id)
    refs = session.get("refs") or []
    if not refs:
        _print("No refs linked.")
        return 0
    for ref in refs:
        _print(ref)
    return 0


def handle_run(store: SessionStore, args: argparse.Namespace) -> int:
    session, session_dir = store.load_session()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        raise FixTapeError("No command provided to fixtape run.")

    counts = store.session_counts(session_dir)
    index = counts["commands"] + 1
    commands_dir = session_dir / "commands"
    stdout_path = commands_dir / f"command_{index:03d}_stdout.txt"
    stderr_path = commands_dir / f"command_{index:03d}_stderr.txt"

    started = time.perf_counter()
    started_at = iso_now()
    result = run_command(cmd, Path(session["cwd"]), stdout_path, stderr_path)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    event = {
        "type": "command_ran",
        "timestamp": started_at,
        "duration_ms": duration_ms,
        "repro": bool(args.repro),
        **result,
    }
    store.add_command_event(event)
    _print(f"Command captured with exit code {result['exit_code']}.")
    return int(result["exit_code"])


def handle_capture(store: SessionStore, args: argparse.Namespace) -> int:
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        raise FixTapeError("No command provided to fixtape capture.")

    started = time.perf_counter()
    started_at = iso_now()
    result = capture_command(cmd, store.cwd)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    event = store.record_pre_session_command(
        command=str(result["command"]),
        exit_code=int(result["exit_code"]),
        shell="fixtape",
        cwd=str(store.cwd),
        timestamp=started_at,
        duration_ms=duration_ms,
        args=list(cmd),
        repro=bool(args.repro),
        stdout_text=str(result["stdout_text"]),
        stderr_text=str(result["stderr_text"]),
        captured_via="fixtape_capture",
    )
    try:
        _, session_dir = store.load_session()
    except NoActiveSessionError:
        session_dir = None
    if session_dir is not None:
        store.promote_buffer_entry(session_dir, event, source="capture")
    if result["stdout_text"]:
        sys.stdout.write(str(result["stdout_text"]))
    if result["stderr_text"]:
        sys.stderr.write(str(result["stderr_text"]))
    _print(f"Recorded command with exit code {result['exit_code']}.")
    return int(result["exit_code"])


def handle_attach(store: SessionStore, args: argparse.Namespace) -> int:
    kind = args.kind.lower()
    if kind not in VALID_ARTIFACT_KINDS:
        raise FixTapeError(f"Unsupported artifact kind: {kind}")
    _, session_dir = store.load_session()
    artifact = copy_artifact(Path(args.path), session_dir / "artifacts", kind)
    store.add_artifact_event(
        {
            "type": "artifact_attached",
            "timestamp": iso_now(),
            **artifact,
        }
    )
    _print(f"Attached artifact: {artifact['filename']}")
    return 0


def handle_snapshot(store: SessionStore, args: argparse.Namespace) -> int:
    snapshot = store.create_snapshot()
    _print(f"Snapshot captured for branch {snapshot.get('branch') or 'unknown'}.")
    return 0


def handle_finish(store: SessionStore, args: argparse.Namespace) -> int:
    session, session_dir, events = store.finalize_session(args.verdict, args.summary, args.refs, args.include_last)
    generated_dir = session_dir / "generated"
    parsed_artifacts = build_parsed_artifacts(events)
    write_json(generated_dir / "parsed-artifacts.json", parsed_artifacts)
    generate_summary(generated_dir / "debug-summary.md", session, events, parsed_artifacts=parsed_artifacts)
    script_name = "repro.ps1" if sys.platform.startswith("win") else "repro.sh"
    generate_repro_script(generated_dir / script_name, events)
    generate_regression_todo(generated_dir / "regression-test.todo.md", session, events)
    write_json(generated_dir / "regression-draft.json", build_regression_draft(session, events))
    generate_handoff(generated_dir / "handoff.md", session, events, parsed_artifacts=parsed_artifacts)
    digest_payload = build_session_digest(session, events, parsed_artifacts)
    write_json(generated_dir / "session-digest.json", digest_payload)
    generate_session_digest(generated_dir / "session-digest.md", digest_payload)
    write_json(generated_dir / "timeline.json", events)
    store.refresh_session_index(session_dir)
    _print(f"Session finished: {session_dir.name}")
    _print(f"Generated summary: {generated_dir / 'debug-summary.md'}")
    if args.include_last:
        _print(f"Included buffered commands from the last {args.include_last}.")
    return 0


def handle_export(store: SessionStore, args: argparse.Namespace) -> int:
    destination = store.export_session(Path(args.destination))
    _print(f"Session exported to: {destination}")
    return 0

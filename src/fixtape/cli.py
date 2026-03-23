from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from fixtape.artifacts import copy_artifact
from fixtape.generators.repro import generate_repro_script
from fixtape.generators.summary import generate_summary
from fixtape.generators.todo import generate_regression_todo
from fixtape.generators.handoff import generate_handoff
from fixtape.runner import run_command
from fixtape.shell_integration import render_shell_init
from fixtape.session_store import (
    ActiveSessionExistsError,
    FixTapeError,
    NoActiveSessionError,
    SessionStore,
)
from fixtape.utils import iso_now, write_json

VALID_VERDICTS = {"fixed", "unresolved", "handoff", "needs-more-data"}
VALID_ARTIFACT_KINDS = {"trace", "log", "payload", "query", "screenshot", "config", "note", "other"}
VALID_SEARCH_FIELDS = {"title", "summary", "notes", "commands", "artifacts"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fixtape", description="Turn debugging sessions into reusable artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start a new FixTape session.")
    start_parser.add_argument("title", help="Short title for the debugging session.")
    start_parser.add_argument("--tag", action="append", default=[], dest="tags", help="Optional tag.")

    list_parser = subparsers.add_parser("list", help="List recent FixTape sessions.")
    list_parser.add_argument("--limit", type=int, default=10, help="Maximum number of sessions to show.")

    show_parser = subparsers.add_parser("show", help="Show a finished session by ID or the last session.")
    show_parser.add_argument("session_id", nargs="?", default=None, help="Optional session ID.")

    search_parser = subparsers.add_parser("search", help="Search across recent FixTape sessions.")
    search_parser.add_argument("query", help="Text query to search for.")
    search_parser.add_argument("--limit", type=int, default=10, help="Maximum number of matches to show.")
    search_parser.add_argument(
        "--field",
        action="append",
        choices=sorted(VALID_SEARCH_FIELDS),
        default=[],
        help="Restrict search to one or more fields.",
    )

    shell_parser = subparsers.add_parser("shell-init", help="Print shell helper functions for faster FixTape usage.")
    shell_parser.add_argument("shell", choices=["powershell", "pwsh", "bash", "zsh", "sh"], help="Shell type.")
    shell_parser.add_argument(
        "--mode",
        choices=["helpers", "hooks", "all"],
        default="all",
        help="Choose whether to print helper wrappers, command hooks, or both.",
    )

    subparsers.add_parser("status", help="Show active session status.")

    note_parser = subparsers.add_parser("note", help="Add a note to the active session.")
    note_parser.add_argument("text", help="Time-stamped debugging note.")

    run_parser = subparsers.add_parser("run", help="Run and capture a command.")
    run_parser.add_argument("--repro", action="store_true", help="Mark the command as reproducible.")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute.")

    attach_parser = subparsers.add_parser("attach", help="Attach an evidence file to the active session.")
    attach_parser.add_argument("kind", help="Artifact kind.")
    attach_parser.add_argument("path", help="Path to the file to attach.")

    subparsers.add_parser("snapshot", help="Capture a Git snapshot for the active session.")

    finish_parser = subparsers.add_parser("finish", help="Finish the active session and generate outputs.")
    finish_parser.add_argument("--verdict", required=True, choices=sorted(VALID_VERDICTS))
    finish_parser.add_argument("--summary", default=None, help="Optional closing summary.")
    finish_parser.add_argument("--ref", action="append", default=[], dest="refs", help="Related ref such as ticket:PAY-123 or commit:abc123.")

    export_parser = subparsers.add_parser("export", help="Zip the active session to a destination file.")
    export_parser.add_argument("destination", help="Destination zip path.")

    record_parser = subparsers.add_parser("record-shell-command", help=argparse.SUPPRESS)
    record_parser.add_argument("--command", required=True, dest="command_text", help=argparse.SUPPRESS)
    record_parser.add_argument("--exit-code", required=True, type=int, help=argparse.SUPPRESS)
    record_parser.add_argument("--shell", default="unknown", help=argparse.SUPPRESS)
    record_parser.add_argument("--cwd", default=None, help=argparse.SUPPRESS)

    return parser


def _command_args(args: list[str]) -> list[str]:
    return args[1:] if args and args[0] == "--" else args


def _print(msg: str) -> None:
    print(msg)


def handle_start(store: SessionStore, args: argparse.Namespace) -> int:
    session_dir = store.start_session(args.title, args.tags)
    _print(f"Started FixTape session: {session_dir.name}")
    _print(f"Session directory: {session_dir}")
    return 0


def handle_list(store: SessionStore, args: argparse.Namespace) -> int:
    sessions = store.list_sessions(limit=max(1, args.limit))
    if not sessions:
        _print("No FixTape sessions found yet.")
        return 0
    for session in sessions:
        verdict = session.get("verdict") or "active"
        _print(f"{session['id']} | {session['created_at']} | {verdict} | {session['title']}")
    return 0


def handle_show(store: SessionStore, args: argparse.Namespace) -> int:
    if args.session_id:
        session, session_dir = store.load_session_by_id(args.session_id)
    else:
        session_dir = store.get_last_session_dir()
        session, session_dir = store.load_session_from_dir(session_dir)

    generated_dir = session_dir / "generated"
    _print(f"Session: {session['title']}")
    _print(f"Session ID: {session['id']}")
    _print(f"Created: {session['created_at']}")
    _print(f"Finished: {session.get('finished_at') or 'active'}")
    _print(f"Verdict: {session.get('verdict') or 'n/a'}")
    _print(f"Directory: {session_dir}")
    _print(f"Summary: {generated_dir / 'debug-summary.md'}")
    _print(f"Timeline: {generated_dir / 'timeline.json'}")
    return 0


def handle_search(store: SessionStore, args: argparse.Namespace) -> int:
    fields = set(args.field) if args.field else None
    matches = store.search_sessions(args.query, fields=fields, limit=max(1, args.limit))
    if not matches:
        _print(f"No FixTape sessions matched: {args.query}")
        return 0
    for match in matches:
        session = match["session"]
        fields = ", ".join(match["hit_fields"])
        _print(
            f"{session['id']} | score={match['score']} | {session.get('verdict') or 'active'} | {fields} | {session['title']}"
        )
        for snippet in match["snippets"]:
            _print(f"  {snippet}")
    return 0


def handle_shell_init(store: SessionStore, args: argparse.Namespace) -> int:
    _print(render_shell_init(args.shell, mode=args.mode))
    return 0


def handle_record_shell_command(store: SessionStore, args: argparse.Namespace) -> int:
    try:
        store.load_session()
    except NoActiveSessionError:
        return 0

    store.add_command_event(
        {
            "type": "command_ran",
            "timestamp": iso_now(),
            "duration_ms": None,
            "repro": False,
            "command": args.command_text,
            "args": None,
            "exit_code": args.exit_code,
            "stdout_file": None,
            "stderr_file": None,
            "stdout_sha256": None,
            "stderr_sha256": None,
            "captured_via": "shell_hook",
            "shell": args.shell,
            "cwd": args.cwd,
        }
    )
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
    if session.get("initial_git_state"):
        state = session["initial_git_state"]
        _print(f"Git branch: {state.get('branch') or 'unknown'}")
        _print(f"Git dirty: {state.get('dirty')}")
    return 0


def handle_note(store: SessionStore, args: argparse.Namespace) -> int:
    store.add_note(args.text)
    _print("Note captured.")
    return 0


def handle_run(store: SessionStore, args: argparse.Namespace) -> int:
    session, session_dir = store.load_session()
    cmd = _command_args(args.cmd)
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
    session, session_dir, events = store.finalize_session(args.verdict, args.summary, args.refs)
    generated_dir = session_dir / "generated"
    generate_summary(generated_dir / "debug-summary.md", session, events)
    script_name = "repro.ps1" if sys.platform.startswith("win") else "repro.sh"
    generate_repro_script(generated_dir / script_name, events)
    generate_regression_todo(generated_dir / "regression-test.todo.md", session, events)
    generate_handoff(generated_dir / "handoff.md", session, events)
    write_json(generated_dir / "timeline.json", events)
    _print(f"Session finished: {session_dir.name}")
    _print(f"Generated summary: {generated_dir / 'debug-summary.md'}")
    return 0


def handle_export(store: SessionStore, args: argparse.Namespace) -> int:
    destination = store.export_session(Path(args.destination))
    _print(f"Session exported to: {destination}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SessionStore()

    handlers = {
        "start": handle_start,
        "list": handle_list,
        "show": handle_show,
        "search": handle_search,
        "shell-init": handle_shell_init,
        "record-shell-command": handle_record_shell_command,
        "status": handle_status,
        "note": handle_note,
        "run": handle_run,
        "attach": handle_attach,
        "snapshot": handle_snapshot,
        "finish": handle_finish,
        "export": handle_export,
    }

    try:
        return handlers[args.command](store, args)
    except ActiveSessionExistsError as exc:
        parser.exit(2, f"error: {exc}\n")
    except NoActiveSessionError as exc:
        parser.exit(2, f"error: {exc}\n")
    except FileNotFoundError as exc:
        parser.exit(2, f"error: {exc}\n")
    except FixTapeError as exc:
        parser.exit(2, f"error: {exc}\n")

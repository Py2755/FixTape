from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from fixtape.artifacts import copy_artifact
from fixtape.artifact_parser import build_parsed_artifacts
from fixtape.generators.digest import build_session_digest, generate_session_digest
from fixtape.generators.kickoff import generate_incident_kickoff
from fixtape.generators.repro import generate_repro_script
from fixtape.generators.summary import generate_summary
from fixtape.generators.todo import build_regression_draft, generate_regression_todo
from fixtape.generators.handoff import generate_handoff
from fixtape.runner import capture_command, run_command
from fixtape.shell_integration import render_shell_init
from fixtape.session_store import (
    ActiveSessionExistsError,
    FixTapeError,
    NoActiveSessionError,
    SessionStore,
)
from fixtape.utils import format_bytes, iso_now, write_json

VALID_VERDICTS = {"fixed", "unresolved", "handoff", "needs-more-data"}
VALID_ARTIFACT_KINDS = {"trace", "log", "payload", "query", "screenshot", "config", "note", "other"}
VALID_SEARCH_FIELDS = {"title", "summary", "notes", "commands", "artifacts", "refs", "signals"}
LINK_KINDS = {"ticket", "issue", "commit", "pr", "branch", "doc", "other", "current-commit"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fixtape", description="Turn debugging sessions into reusable artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start a new FixTape session.")
    start_parser.add_argument("title", help="Short title for the debugging session.")
    start_parser.add_argument("--tag", action="append", default=[], dest="tags", help="Optional tag.")
    start_parser.add_argument("--include-last", default=None, help="Import buffered pre-session commands such as 40m or 90s.")

    list_parser = subparsers.add_parser("list", help="List recent FixTape sessions.")
    list_parser.add_argument("--limit", type=int, default=10, help="Maximum number of sessions to show.")

    subparsers.add_parser("reindex", help="Rebuild the cross-session FixTape index.")

    show_parser = subparsers.add_parser("show", help="Show a finished session by ID or the last session.")
    show_parser.add_argument("session_id", nargs="?", default=None, help="Optional session ID.")

    digest_parser = subparsers.add_parser("digest", help="Show the compact digest for the current, latest, or specified session.")
    digest_parser.add_argument("session_id", nargs="?", default=None, help="Optional FixTape session ID.")

    similar_parser = subparsers.add_parser("similar", help="Show similar sessions for the current, latest, or specified session.")
    similar_parser.add_argument("session_id", nargs="?", default=None, help="Optional FixTape session ID.")
    similar_parser.add_argument("--limit", type=int, default=5, help="Maximum number of similar sessions to show.")

    patterns_parser = subparsers.add_parser("patterns", help="Show recurring failure patterns across sessions.")
    patterns_parser.add_argument("--limit", type=int, default=5, help="Maximum number of recurring patterns to show.")

    clusters_parser = subparsers.add_parser("clusters", help="Show connected incident clusters across session history.")
    clusters_parser.add_argument("--limit", type=int, default=5, help="Maximum number of clusters to show.")
    clusters_parser.add_argument("--min-size", type=int, default=2, dest="min_size", help="Minimum sessions required for a cluster.")

    hotspots_parser = subparsers.add_parser("hotspots", help="Show recurring failure hotspots across session history.")
    hotspots_parser.add_argument("--limit", type=int, default=8, help="Maximum number of hotspots to show.")
    hotspots_parser.add_argument(
        "--kind",
        choices=["all", "family", "exception", "file", "status", "fingerprint"],
        default="all",
        help="Restrict hotspots to one dimension.",
    )

    lenses_parser = subparsers.add_parser("lenses", help="Show root-cause lenses across session history.")
    lenses_parser.add_argument("--limit", type=int, default=5, help="Maximum number of items to show per lens.")

    regressions_parser = subparsers.add_parser("regressions", help="Show recurring regression memory across historical sessions.")
    regressions_parser.add_argument("--limit", type=int, default=6, help="Maximum number of regression memories to show.")

    outcomes_parser = subparsers.add_parser("outcomes", help="Show fix outcome analytics across session history.")
    outcomes_parser.add_argument("--limit", type=int, default=6, help="Maximum number of family rows to show.")

    playbooks_parser = subparsers.add_parser("playbooks", help="Show repeatable troubleshooting playbooks across session history.")
    playbooks_parser.add_argument("--limit", type=int, default=5, help="Maximum number of playbooks to show.")

    recipes_parser = subparsers.add_parser("recipes", help="Show concrete fix recipes for repeated failure buckets.")
    recipes_parser.add_argument("--limit", type=int, default=5, help="Maximum number of recipes to show.")

    triage_parser = subparsers.add_parser("triage", help="Suggest the best historical playbook and recipe for a current signal.")
    triage_parser.add_argument("query", help="Current incident signal, exception, or short description.")
    triage_parser.add_argument("--limit", type=int, default=3, help="Maximum number of supporting matches to show.")

    kickoff_parser = subparsers.add_parser("kickoff", help="Start a new session with a generated incident kickoff bundle from history.")
    kickoff_parser.add_argument("title", help="Title for the new FixTape session.")
    kickoff_parser.add_argument("--query", required=True, help="Current incident signal used for triage.")
    kickoff_parser.add_argument("--tag", action="append", default=[], dest="tags", help="Optional tag.")
    kickoff_parser.add_argument("--include-last", default=None, help="Import buffered pre-session commands such as 40m or 90s.")

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

    doctor_parser = subparsers.add_parser("doctor", help="Show zero-touch flight-recorder status and recent buffered commands.")
    doctor_parser.add_argument("--window", default=None, help="Optional time window such as 40m or 2h.")

    promote_parser = subparsers.add_parser("promote", help="Import recent pre-session commands into the active session.")
    promote_parser.add_argument("--include-last", required=True, help="Import buffered commands such as 40m or 90s.")

    note_parser = subparsers.add_parser("note", help="Add a note to the active session.")
    note_parser.add_argument("text", help="Time-stamped debugging note.")

    link_parser = subparsers.add_parser("link", help="Link a ticket, issue, commit, or other ref to the current or latest session.")
    link_parser.add_argument("kind", choices=sorted(LINK_KINDS), help="Reference kind.")
    link_parser.add_argument("value", nargs="?", default=None, help="Reference value. Omit only for current-commit.")

    refs_parser = subparsers.add_parser("refs", help="Show linked refs for the current, latest, or specified session.")
    refs_parser.add_argument("session_id", nargs="?", default=None, help="Optional FixTape session ID.")

    run_parser = subparsers.add_parser("run", help="Run and capture a command.")
    run_parser.add_argument("--repro", action="store_true", help="Mark the command as reproducible.")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute.")

    capture_parser = subparsers.add_parser("capture", help="Run a command and record it in the pre-session flight recorder.")
    capture_parser.add_argument("--repro", action="store_true", help="Mark the command as reproducible.")
    capture_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute.")

    attach_parser = subparsers.add_parser("attach", help="Attach an evidence file to the active session.")
    attach_parser.add_argument("kind", help="Artifact kind.")
    attach_parser.add_argument("path", help="Path to the file to attach.")

    subparsers.add_parser("snapshot", help="Capture a Git snapshot for the active session.")

    finish_parser = subparsers.add_parser("finish", help="Finish the active session and generate outputs.")
    finish_parser.add_argument("--verdict", required=True, choices=sorted(VALID_VERDICTS))
    finish_parser.add_argument("--summary", default=None, help="Optional closing summary.")
    finish_parser.add_argument("--ref", action="append", default=[], dest="refs", help="Related ref such as ticket:PAY-123 or commit:abc123.")
    finish_parser.add_argument("--include-last", default=None, help="Import buffered pre-session commands such as 40m or 90s before finishing.")

    export_parser = subparsers.add_parser("export", help="Zip the active session to a destination file.")
    export_parser.add_argument("destination", help="Destination zip path.")

    record_parser = subparsers.add_parser("record-shell-command", help=argparse.SUPPRESS)
    record_parser.add_argument("--command", required=True, dest="command_text", help=argparse.SUPPRESS)
    record_parser.add_argument("--exit-code", required=True, type=int, help=argparse.SUPPRESS)
    record_parser.add_argument("--shell", default="unknown", help=argparse.SUPPRESS)
    record_parser.add_argument("--cwd", default=None, help=argparse.SUPPRESS)
    record_parser.add_argument("--captured-via", default="shell_hook", help=argparse.SUPPRESS)

    return parser


def _command_args(args: list[str]) -> list[str]:
    return args[1:] if args and args[0] == "--" else args


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


def handle_list(store: SessionStore, args: argparse.Namespace) -> int:
    sessions = store.list_sessions(limit=max(1, args.limit))
    if not sessions:
        _print("No FixTape sessions found yet.")
        return 0
    for session in sessions:
        verdict = "active" if session.get("is_active") else (session.get("verdict") or "n/a")
        _print(f"{session['id']} | {session['created_at']} | {verdict} | {session['title']}")
    return 0


def handle_reindex(store: SessionStore, args: argparse.Namespace) -> int:
    count = store.reindex_sessions()
    _print(f"Rebuilt FixTape index for {count} session(s).")
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
    if session.get("refs"):
        _print(f"Refs: {', '.join(session['refs'])}")
    _print(f"Directory: {session_dir}")
    _print(f"Summary: {generated_dir / 'debug-summary.md'}")
    _print(f"Timeline: {generated_dir / 'timeline.json'}")
    similar = store.find_similar_sessions(session["id"], limit=3)
    if similar:
        _print("Similar sessions:")
        for match in similar:
            candidate = match["session"]
            _print(f"  - {candidate['id']} | score={match['score']} | {candidate['title']}")
    return 0


def handle_digest(store: SessionStore, args: argparse.Namespace) -> int:
    if args.session_id:
        session, session_dir = store.load_session_by_id(args.session_id)
    else:
        session_dir = store.get_preferred_session_dir()
        session, session_dir = store.load_session_from_dir(session_dir)
    digest_payload = store.load_or_build_digest(session_dir, session)
    _print(f"Session digest: {session['title']}")
    _print(f"Summary: {digest_payload.get('summary_line') or 'n/a'}")
    if digest_payload.get("failure_family"):
        _print(f"Failure family: {digest_payload['failure_family']}")
    if digest_payload.get("exception_type"):
        _print(f"Exception: {digest_payload['exception_type']}")
    if digest_payload.get("likely_area"):
        _print(f"Likely area: {digest_payload['likely_area']}")
    if digest_payload.get("root_cause_hint"):
        _print(f"Root-cause hint: {digest_payload['root_cause_hint']}")
    if digest_payload.get("repro_command"):
        _print(f"Repro command: {digest_payload['repro_command']}")
    if digest_payload.get("next_step"):
        _print(f"Next step: {digest_payload['next_step']}")
    return 0


def handle_similar(store: SessionStore, args: argparse.Namespace) -> int:
    matches = store.find_similar_sessions(args.session_id, limit=max(1, args.limit))
    if not matches:
        _print("No similar FixTape sessions found.")
        return 0
    for match in matches:
        session = match["session"]
        _print(f"{session['id']} | score={match['score']} | {session.get('verdict') or 'active'} | {session['title']}")
        for reason in match["reasons"]:
            _print(f"  reason: {reason}")
    return 0


def handle_patterns(store: SessionStore, args: argparse.Namespace) -> int:
    patterns = store.recurring_patterns(limit=max(1, args.limit))
    if not patterns:
        _print("No recurring failure patterns detected yet.")
        return 0
    for pattern in patterns:
        _print(f"{pattern['count']} sessions | {pattern['headline']}")
        _print(f"  fingerprint: {pattern['fingerprint']}")
        if pattern["exception_types"]:
            _print(f"  exceptions: {', '.join(pattern['exception_types'])}")
        if pattern["file_hints"]:
            _print(f"  files: {', '.join(pattern['file_hints'])}")
        if pattern["titles"]:
            _print(f"  examples: {', '.join(pattern['titles'])}")
    return 0


def handle_clusters(store: SessionStore, args: argparse.Namespace) -> int:
    clusters = store.incident_clusters(limit=max(1, args.limit), min_size=max(2, args.min_size))
    if not clusters:
        _print("No incident clusters detected yet.")
        return 0
    for cluster in clusters:
        _print(f"{cluster['count']} sessions | open={cluster['open_count']} | {cluster['lead']}")
        if cluster["families"]:
            _print(f"  families: {', '.join(cluster['families'])}")
        if cluster["exceptions"]:
            _print(f"  exceptions: {', '.join(cluster['exceptions'])}")
        if cluster["files"]:
            _print(f"  files: {', '.join(cluster['files'])}")
        if cluster["titles"]:
            _print(f"  examples: {', '.join(cluster['titles'])}")
    return 0


def handle_hotspots(store: SessionStore, args: argparse.Namespace) -> int:
    hotspots = store.hotspots(limit=max(1, args.limit), kind=args.kind)
    if not hotspots:
        _print("No recurring hotspots detected yet.")
        return 0
    for hotspot in hotspots:
        _print(f"{hotspot['kind']} | {hotspot['count']} sessions | open={hotspot['open_count']} | {hotspot['label']}")
        if hotspot["families"]:
            _print(f"  families: {', '.join(hotspot['families'])}")
        if hotspot["examples"]:
            _print(f"  examples: {', '.join(hotspot['examples'])}")
        if hotspot["headlines"]:
            _print(f"  signals: {', '.join(hotspot['headlines'])}")
    return 0


def handle_lenses(store: SessionStore, args: argparse.Namespace) -> int:
    lenses = store.root_cause_lenses(limit=max(1, args.limit))
    if not any(lenses.values()):
        _print("No root-cause lenses detected yet.")
        return 0

    _print("Family lenses:")
    if lenses["families"]:
        for item in lenses["families"]:
            _print(f"  {item['label']} | {item['count']} sessions | open={item['open_count']} | next={item['next_step']}")
    else:
        _print("  none")

    _print("Area lenses:")
    if lenses["areas"]:
        for item in lenses["areas"]:
            _print(f"  {item['label']} | {item['count']} sessions | open={item['open_count']} | families={', '.join(item['families'])}")
    else:
        _print("  none")

    _print("Digest lenses:")
    if lenses["digests"]:
        for item in lenses["digests"]:
            _print(f"  {item['label']} | {item['count']} sessions | next={item['next_step']}")
    else:
        _print("  none")
    return 0


def handle_regressions(store: SessionStore, args: argparse.Namespace) -> int:
    memories = store.regression_memory(limit=max(1, args.limit))
    if not memories:
        _print("No recurring regression memories detected yet.")
        return 0
    for item in memories:
        _print(f"{item['count']} sessions | fixed={item['fixed_count']} | open={item['open_count']} | {item['label']}")
        _print(f"  test: {item['test_name']}")
        _print(f"  entry: {item['entry_point']}")
        if item["fixtures"]:
            _print(f"  fixtures: {', '.join(item['fixtures'])}")
        if item["areas"]:
            _print(f"  areas: {', '.join(item['areas'])}")
        if item["examples"]:
            _print(f"  examples: {', '.join(item['examples'])}")
    return 0


def handle_outcomes(store: SessionStore, args: argparse.Namespace) -> int:
    analytics = store.outcome_analytics(limit=max(1, args.limit))
    if analytics["total_sessions"] == 0:
        _print("No outcome analytics available yet.")
        return 0
    _print(
        "Totals: "
        f"sessions={analytics['total_sessions']} "
        f"fixed={analytics['fixed_rate']}% "
        f"repro-ready={analytics['repro_ready_rate']}% "
        f"regression-ready={analytics['regression_ready_rate']}%"
    )
    if analytics["verdicts"]:
        verdicts = ", ".join(f"{key}={value}" for key, value in sorted(analytics["verdicts"].items()))
        _print(f"Verdicts: {verdicts}")
    for item in analytics["families"]:
        _print(
            f"{item['label']} | count={item['count']} | fixed={item['fixed_rate']}% | "
            f"open={item['open_rate']}% | repro={item['repro_rate']}% | regression={item['regression_rate']}%"
        )
        if item["examples"]:
            _print(f"  examples: {', '.join(item['examples'])}")
    return 0


def handle_playbooks(store: SessionStore, args: argparse.Namespace) -> int:
    playbooks = store.playbooks(limit=max(1, args.limit))
    if not playbooks:
        _print("No repeatable playbooks detected yet.")
        return 0
    for item in playbooks:
        _print(f"{item['label']} | {item['count']} sessions | open={item['open_count']}")
        _print(f"  start: {item['starter_step']}")
        _print(f"  entry: {item['entry_point']}")
        if item["artifacts"]:
            _print(f"  artifacts: {', '.join(item['artifacts'])}")
        if item["areas"]:
            _print(f"  areas: {', '.join(item['areas'])}")
        if item["refs"]:
            _print(f"  refs: {', '.join(item['refs'])}")
        if item["examples"]:
            _print(f"  examples: {', '.join(item['examples'])}")
    return 0


def handle_recipes(store: SessionStore, args: argparse.Namespace) -> int:
    recipes = store.fix_recipes(limit=max(1, args.limit))
    if not recipes:
        _print("No repeated fix recipes detected yet.")
        return 0
    for item in recipes:
        _print(f"{item['count']} sessions | {item['label']}")
        _print(f"  trigger: {item['trigger']}")
        _print(f"  area: {item['area']}")
        _print(f"  entry: {item['entry_point']}")
        _print(f"  repro: {item['repro_command']}")
        _print(f"  next: {item['next_step']}")
        if item["artifact_kinds"]:
            _print(f"  capture: {', '.join(item['artifact_kinds'])}")
        if item["examples"]:
            _print(f"  examples: {', '.join(item['examples'])}")
    return 0


def handle_triage(store: SessionStore, args: argparse.Namespace) -> int:
    payload = store.triage(args.query, limit=max(1, args.limit))
    _print(f"Triage query: {payload['query']}")
    _print(f"Recommended first move: {payload['starter_step']}")
    _print(f"Entry point: {payload['entry_point']}")
    _print(f"Repro command: {payload['repro_command']}")
    if payload["artifact_kinds"]:
        _print(f"Capture first: {', '.join(payload['artifact_kinds'])}")
    if payload["areas"]:
        _print(f"Check areas: {', '.join(payload['areas'])}")
    if payload["playbook"]:
        _print(f"Playbook: {payload['playbook']['label']}")
    if payload["recipe"]:
        _print(f"Recipe: {payload['recipe']['label']}")
    if payload["sessions"]:
        _print("Historical matches:")
        for session in payload["sessions"]:
            _print(f"  {session['id']} | score={session['score']} | {session['verdict']} | {session['title']}")
    return 0


def handle_kickoff(store: SessionStore, args: argparse.Namespace) -> int:
    session_dir = store.start_session(args.title, args.tags, include_last=args.include_last)
    session, session_dir = store.load_session_from_dir(session_dir)
    generated_dir = session_dir / "generated"
    triage_payload = store.triage(args.query, limit=3)
    kickoff_payload = {
        "title": session["title"],
        "session_id": session["id"],
        "query": triage_payload["query"],
        "starter_step": triage_payload["starter_step"],
        "entry_point": triage_payload["entry_point"],
        "repro_command": triage_payload["repro_command"],
        "artifact_kinds": triage_payload["artifact_kinds"],
        "areas": triage_payload["areas"],
        "sessions": triage_payload["sessions"],
        "playbook": triage_payload["playbook"],
        "recipe": triage_payload["recipe"],
        "reasons": triage_payload["reasons"],
    }
    write_json(generated_dir / "incident-kickoff.json", kickoff_payload)
    generate_incident_kickoff(generated_dir / "incident-kickoff.md", kickoff_payload)
    _print(f"Started FixTape session: {session_dir.name}")
    _print(f"Kickoff bundle: {generated_dir / 'incident-kickoff.md'}")
    if args.include_last:
        imported = store.include_recent_buffer(session_dir, args.include_last, source="kickoff")
        _print(f"Imported buffered commands: {imported['count']} from the last {args.include_last}")
    _print(f"Recommended first move: {triage_payload['starter_step']}")
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


def handle_doctor(store: SessionStore, args: argparse.Namespace) -> int:
    status = store.recorder_status(window=args.window)
    _print("Flight recorder:")
    _print(f"Retention window: {status['retention_window']}")
    _print(f"Buffered commands: {status['entry_count']}")
    _print(f"Output bytes: {status.get('output_bytes_human') or format_bytes(status['output_bytes'])}")
    _print(f"Buffer budget: {status.get('max_bytes_human') or format_bytes(status['max_bytes'])}")
    if status["newest_timestamp"]:
        _print(f"Newest command: {status['newest_timestamp']}")
    if not status["recent"]:
        _print("Recent commands: none")
        return 0
    _print("Recent commands:")
    for item in status["recent"]:
        marker = "output" if item["has_output"] else "history"
        _print(f"  {item['timestamp']} | exit={item['exit_code']} | {marker} | {item['command']}")
    return 0


def handle_promote(store: SessionStore, args: argparse.Namespace) -> int:
    session, session_dir = store.load_session()
    result = store.include_recent_buffer(session_dir, args.include_last, source="promote")
    _print(f"Promoted buffered commands into session: {session['id']}")
    _print(f"Imported: {result['count']} from the last {args.include_last}")
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


def handle_capture(store: SessionStore, args: argparse.Namespace) -> int:
    cmd = _command_args(args.cmd)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SessionStore()

    handlers = {
        "start": handle_start,
        "list": handle_list,
        "reindex": handle_reindex,
        "show": handle_show,
        "digest": handle_digest,
        "similar": handle_similar,
        "patterns": handle_patterns,
        "clusters": handle_clusters,
        "hotspots": handle_hotspots,
        "lenses": handle_lenses,
        "regressions": handle_regressions,
        "outcomes": handle_outcomes,
        "playbooks": handle_playbooks,
        "recipes": handle_recipes,
        "triage": handle_triage,
        "kickoff": handle_kickoff,
        "search": handle_search,
        "shell-init": handle_shell_init,
        "record-shell-command": handle_record_shell_command,
        "status": handle_status,
        "doctor": handle_doctor,
        "promote": handle_promote,
        "note": handle_note,
        "link": handle_link,
        "refs": handle_refs,
        "run": handle_run,
        "capture": handle_capture,
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

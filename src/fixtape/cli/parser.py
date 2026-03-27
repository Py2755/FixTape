from __future__ import annotations

import argparse

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

    suggest_parser = subparsers.add_parser("suggest-start", help="Suggest starting a FixTape session from recent failure activity.")
    suggest_parser.add_argument("--window", default="20m", help="Time window to analyze, such as 20m or 1h.")
    suggest_parser.add_argument("--cooldown", default="15m", help="Suppress duplicate shell suggestions for this long.")
    suggest_parser.add_argument("--shell-notify", action="store_true", help=argparse.SUPPRESS)

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

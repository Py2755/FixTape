from __future__ import annotations

from fixtape.cli.parser import build_parser
from fixtape.cli.handlers_session import (
    handle_start,
    handle_status,
    handle_note,
    handle_link,
    handle_refs,
    handle_run,
    handle_capture,
    handle_attach,
    handle_snapshot,
    handle_finish,
    handle_export,
)
from fixtape.cli.handlers_analysis import (
    handle_list,
    handle_reindex,
    handle_show,
    handle_digest,
    handle_similar,
    handle_patterns,
    handle_clusters,
    handle_hotspots,
    handle_lenses,
    handle_regressions,
    handle_outcomes,
    handle_playbooks,
    handle_recipes,
    handle_triage,
    handle_kickoff,
    handle_search,
)
from fixtape.cli.handlers_recorder import (
    handle_shell_init,
    handle_record_shell_command,
    handle_doctor,
    handle_suggest_start,
    handle_promote,
)
from fixtape.session_store import (
    ActiveSessionExistsError,
    FixTapeError,
    NoActiveSessionError,
    SessionStore,
)


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
        "suggest-start": handle_suggest_start,
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

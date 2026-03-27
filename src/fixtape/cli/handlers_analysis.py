from __future__ import annotations

import argparse

from fixtape.generators.kickoff import generate_incident_kickoff
from fixtape.session_store import SessionStore
from fixtape.utils import write_json


def _print(msg: str) -> None:
    print(msg)


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
        fields_str = ", ".join(match["hit_fields"])
        _print(
            f"{session['id']} | score={match['score']} | {session.get('verdict') or 'active'} | {fields_str} | {session['title']}"
        )
        for snippet in match["snippets"]:
            _print(f"  {snippet}")
    return 0

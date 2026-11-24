"""Offline image-clean trial for SMALL, independent, fully indexed conversations.

Not a replacement for doctor clean. Keep every Codex client closed until this
command completes. After interruption, use --recover before reopening Codex.
"""

import argparse
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from codex_session_clean_probe import inspect_positions, run_probe
from codex_session_image_projection import (
    apply_projected_images,
    plan_projected_images,
    verify_projected_images,
)
from codex_session_image_transaction import (
    JOURNAL_NAME,
    TRANSACTION_PREFIX,
    copy_verified_file,
    database_state,
    fsync_directory,
    load_journal,
    publish_verified_file,
    recover_transaction_locked,
    require_no_pending_transactions,
    write_journal,
)
from codex_session_lineage import session_root
from codex_session_projection import (
    HISTORY_DATABASE_NAME,
    apply_projection_plan,
    backup_history_database,
    connect_history,
    projection_plan_from_positions,
    projection_rows,
    rollout_identifier,
    validate_projection_schema,
)
from codex_session_storage import (
    offline_session_lock,
    require_closed,
    require_codex_stopped,
    sha256_file,
)


def prepare_trial(session):
    home = session_root(session).parent
    database = home / HISTORY_DATABASE_NAME
    identifier = rollout_identifier(session)
    require_no_pending_transactions(home)
    require_closed(session)
    require_closed(database)
    with closing(connect_history(database)) as reader:
        _, checkpoint = projection_rows(reader, identifier)
        positions = inspect_positions(session)
        if checkpoint != (max(positions), session.stat().st_size):
            raise ValueError("Trial requires a fully indexed rollout; reopen/close Codex before retrying")
    proof = run_probe(session)
    output = Path(proof["output_home"])
    cleaned = output / "sessions" / session.name
    with closing(connect_history(database)) as reader:
        reader.execute("BEGIN")
        old_database = database_state(reader, identifier)
        turns, checkpoint = projection_rows(reader, identifier)
        plan = projection_plan_from_positions(session, turns, checkpoint, inspect_positions(cleaned))
        snapshots, updates = plan_projected_images(reader, identifier, positions)
    with closing(connect_history(output / HISTORY_DATABASE_NAME)) as reader:
        new_database = database_state(reader, identifier)
        verify_projected_images(reader, identifier, snapshots, updates)
    if sha256_file(session) != proof["source_sha256"]:
        raise RuntimeError("Source changed after the isolated proof")
    backup = backup_history_database(database, [plan])
    directory = backup.parent / (TRANSACTION_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(mode=0o700)
    fsync_directory(directory.parent)
    original_hash, cleaned_hash = proof["source_sha256"], sha256_file(cleaned)
    if original_hash == cleaned_hash:
        raise ValueError("Trial found no rollout changes")
    copy_verified_file(session, directory / "original.jsonl", original_hash)
    copy_verified_file(cleaned, directory / "cleaned.jsonl", cleaned_hash)
    journal = {"version": 1, "status": "prepared", "session": str(session), "identifier": identifier,
               "old_sha256": original_hash, "new_sha256": cleaned_hash,
               "old_database": old_database, "new_database": new_database,
               "database_backup": str(backup)}
    path = directory / JOURNAL_NAME
    write_journal(path, journal)
    print(f"recovery_journal: {path}", flush=True)
    return path, journal, plan, updates


def commit_trial(path, journal, plan, updates):
    session = Path(journal["session"])
    database = session_root(session).parent / HISTORY_DATABASE_NAME
    with closing(connect_history(database, writable=True)) as writer:
        writer.execute("PRAGMA synchronous=FULL")
        writer.execute("BEGIN IMMEDIATE")
        try:
            validate_projection_schema(writer)
            for table in ("thread_items", "thread_realtime_items"):
                if writer.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchone():
                    raise ValueError(f"Unsupported trigger on {table}")
            if database_state(writer, journal["identifier"]) != journal["old_database"]:
                raise RuntimeError("Projected conversation changed after planning")
            apply_projection_plan(writer, [plan])
            apply_projected_images(writer, updates)
            if database_state(writer, journal["identifier"]) != journal["new_database"]:
                raise RuntimeError("Transaction differs from the isolated proof")
            publish_verified_file(path.parent / "cleaned.jsonl", session,
                                  journal["new_sha256"], journal["old_sha256"])
            require_codex_stopped()
            writer.commit()
        except BaseException:
            writer.rollback()
            raise


def run_trial(session):
    session = Path(session).absolute()
    if session.resolve() != session:
        raise ValueError("Use the canonical session path, not a symlink")
    home = session_root(session).parent
    with offline_session_lock([home, session_root(session)]):
        path, journal, plan, updates = prepare_trial(session)
        try:
            commit_trial(path, journal, plan, updates)
        except BaseException:
            result = recover_transaction_locked(path)
            print(f"failure_recovery: {result}; journal: {path}", flush=True)
            raise
        result = recover_transaction_locked(path)
        if result != "applied":
            raise RuntimeError(f"Expected applied transaction, found {result}")
    print(json.dumps({"result": result, "images_removed_from_index": len(updates),
                      "messages_deleted": 0, "native_ui_verified": False, "journal": str(path)}), flush=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session", type=Path)
    mode.add_argument("--recover", type=Path)
    parser.add_argument("--apply", action="store_true", help="Required explicit write confirmation")
    arguments = parser.parse_args()
    if not arguments.apply:
        parser.error("--apply is required; use codex_session_clean_probe.py for an isolated test")
    if arguments.session:
        run_trial(arguments.session)
    else:
        path = arguments.recover.absolute()
        session = Path(load_journal(path)["session"])
        with offline_session_lock([session_root(session).parent, session_root(session)]):
            print("recovery_result:", recover_transaction_locked(path))


if __name__ == "__main__":
    main()

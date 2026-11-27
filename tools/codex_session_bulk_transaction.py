"""Offline, journaled multi-rollout publication with targeted crash recovery.

File renames and SQLite commit are not jointly atomic. Recovery restores changed
rollouts when SQLite rolled back, or verifies all committed files. It never
restores an older full DB over newer conversations. Native clients must stay off.
"""

import json
import shlex
import shutil
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from codex_session_bulk_images import (
    history_database_digest,
    plan_home_images,
    stage_home_images,
    stage_projected_images,
    validate_bulk_schema,
)
from codex_session_history_repair import (
    ROLLOUT_DIRECTORIES,
    home_rollout_paths,
    require_home_plan_unchanged,
)
from codex_session_image_projection import apply_projected_images
from codex_session_image_transaction import (
    copy_verified_file,
    fsync_directory,
    publish_verified_file,
    write_journal,
)
from codex_session_projection import (
    HISTORY_DATABASE_NAME,
    apply_projection_plan,
    backup_history_database,
    connect_history,
    projection_plan_changed,
)
from codex_session_storage import (
    file_signature,
    offline_session_lock,
    require_closed,
    require_codex_stopped,
    require_no_unfinished_image_cleanup,
    sha256_file,
)
from tqdm import tqdm

JOURNAL_NAME = "bulk-transaction.json"
DIRECTORY_PREFIX = "bulk-image-clean-"
DISK_RESERVE_BYTES = 64 * 1024 * 1024
FINAL_STATUSES = {"applied", "rolled_back"}


def maintenance_roots(home):
    return [home, *(home / name for name in ROLLOUT_DIRECTORIES if (home / name).is_dir())]


def load_bulk_journal(path):
    file_signature(path)
    journal = json.loads(path.read_text())
    if journal["version"] != 1 or journal["status"] not in {"prepared", *FINAL_STATUSES}:
        raise ValueError("Unsupported bulk transaction journal")
    home = Path(journal["home"])
    if not home.is_absolute() or home.resolve(strict=True) != home:
        raise ValueError("Journal home is not a canonical directory")
    if path.parent.parent != home / "session_maintenance_backups" or not path.parent.name.startswith(DIRECTORY_PREFIX):
        raise ValueError("Journal is outside its private maintenance directory")
    if path.resolve(strict=True) != path:
        raise ValueError("Symlink transaction journal is forbidden")
    seen = set()
    for item in journal["files"]:
        source = Path(item["path"])
        if source in seen or source.resolve(strict=True) != source or not any(source.is_relative_to(home / folder) for folder in ROLLOUT_DIRECTORIES):
            raise ValueError("Invalid or duplicate journal rollout path")
        seen.add(source)
        if item["changed"]:
            for key in ("staged", "backup"):
                if Path(item[key]).name != item[key]:
                    raise ValueError("Journal artifacts must be direct children of its directory")
    return journal


def verify_rollout_hashes(home, files, expected_state=None):
    if set(home_rollout_paths(home)) != {Path(item["path"]) for item in files}:
        raise RuntimeError("Rollout inventory changed; refusing automatic recovery/publication")
    observed = {}
    for item in tqdm(files, total=len(files), desc="Verify rollout fingerprints", unit="file", mininterval=1):
        source = Path(item["path"])
        file_signature(source)
        actual = sha256_file(source)
        permitted = {item["old_sha256"], item["new_sha256"]} if expected_state is None else {item[expected_state + "_sha256"]}
        if actual not in permitted:
            raise RuntimeError(f"Rollout contains unexpected/newer data; refusing overwrite: {source}")
        observed[str(source)] = actual
    return observed


def recover_bulk_locked(path):
    journal = load_bulk_journal(path)
    home = Path(journal["home"])
    database = home / HISTORY_DATABASE_NAME
    require_codex_stopped()
    require_closed(database)
    with closing(connect_history(database, writable=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            validate_bulk_schema(connection)
            actual_database = history_database_digest(connection, "Recover")
            database_changed = journal["old_database_digest"] != journal["new_database_digest"]
            if actual_database == journal["new_database_digest"] and (database_changed or journal["status"] == "applied"):
                verify_rollout_hashes(home, journal["files"], "new")
                status = "applied"
            elif actual_database == journal["old_database_digest"]:
                observed = verify_rollout_hashes(home, journal["files"])
                changed = [item for item in journal["files"] if item["changed"]]
                # Check every backup before restoring the first file.
                for item in tqdm(changed, total=len(changed), desc="Verify recovery backups", unit="file"):
                    backup = path.parent / item["backup"]
                    file_signature(backup)
                    if sha256_file(backup) != item["old_sha256"]:
                        raise RuntimeError(f"Backup hash mismatch: {backup}")
                for item in tqdm(changed, total=len(changed), desc="Restore rolled-back files", unit="file"):
                    if observed[item["path"]] != item["old_sha256"]:
                        publish_verified_file(path.parent / item["backup"], Path(item["path"]), item["old_sha256"], item["new_sha256"])
                verify_rollout_hashes(home, journal["files"], "old")
                status = "rolled_back"
            else:
                raise RuntimeError("History DB contains newer/unknown data; automatic recovery refused")
            require_codex_stopped()
            journal["status"] = status
            write_journal(path, journal)
        finally:
            connection.rollback()
    print("bulk_recovery_result:", status, flush=True)
    return status


def make_work_directory(home, plan, connection):
    changed = [identifier for identifier, entry in plan["inventory"].items()
               if plan["scans"][identifier]["old_hash"] != plan["scans"][identifier]["new_hash"] or entry["path"] in plan["headers"]]
    needed = sum(plan["scans"][identifier]["old_bytes"] + plan["scans"][identifier]["new_bytes"] for identifier in changed)
    database_bytes = connection.execute("PRAGMA page_count").fetchone()[0] * connection.execute("PRAGMA page_size").fetchone()[0]
    # Image-update artifacts can be as large as the DB: reserve this explicitly.
    needed += database_bytes * 2 + DISK_RESERVE_BYTES
    if shutil.disk_usage(home).free < needed:
        raise RuntimeError(f"Insufficient disk space for verified backups/staging: need {needed} bytes")
    parent = home / "session_maintenance_backups"
    if parent.is_symlink():
        raise ValueError("Symlink backup directory is forbidden")
    parent.mkdir(mode=0o700, exist_ok=True)
    directory = parent / (DIRECTORY_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(mode=0o700)
    fsync_directory(parent)
    print("bulk_work_directory:", directory, flush=True)
    return directory


def update_indexed_images(connection, updates_path, expected_updates):
    applied = 0
    with updates_path.open("rb") as stream, tqdm(total=expected_updates, desc="Update indexed images", unit="item", mininterval=1) as progress:
        for raw in stream:
            apply_projected_images(connection, [json.loads(raw)])
            applied += 1
            progress.update(1)
    if applied != expected_updates:
        raise RuntimeError("Indexed image update count changed")


def execute_bulk_locked(home, selected_session=None):
    database = home / HISTORY_DATABASE_NAME
    require_no_unfinished_image_cleanup([home])
    require_closed(database)
    journal_path = None
    summary = None
    try:
        with closing(connect_history(database, writable=True)) as writer:
            writer.execute("PRAGMA synchronous=FULL")
            writer.execute("BEGIN IMMEDIATE")
            try:
                plan = plan_home_images(home, writer, selected_session)
                directory = make_work_directory(home, plan, writer)
                updates_path = directory / "indexed-images.jsonl"
                update_count, indexed_statistics = stage_projected_images(writer, updates_path, plan["cleanup_identifiers"])
                files = stage_home_images(plan, directory)
                changed_files = [item for item in files if item["changed"]]
                summary = {"files_scanned": len(files), "files_changed": len(changed_files),
                           "scope": "session_and_ancestors" if selected_session is not None else "all_home",
                           "selected_session": str(selected_session) if selected_session is not None else None,
                           "image_cleanup_rollouts": [str(plan["inventory"][identifier]["path"])
                                                      for identifier in sorted(plan["cleanup_identifiers"])],
                           "lineage_headers_updated": len(plan["headers"]),
                           "projections_updated": sum(map(projection_plan_changed, plan["projections"])),
                           "indexed_items_changed": update_count, "indexed_image_statistics": indexed_statistics,
                           "saved_rollout_bytes": sum(scan["old_bytes"] - scan["new_bytes"] for scan in plan["scans"].values()),
                           "messages_deleted": 0, "replacement_text_added": False, "native_ui_verified": False}
                print("BULK_CLEAN_PLAN", json.dumps(summary), flush=True)
                if not changed_files and not update_count:
                    writer.rollback()
                    print("already_clean: true", flush=True)
                    return summary
                require_codex_stopped()
                require_home_plan_unchanged(home, plan)
                backup = backup_history_database(database, plan["projections"])
                for item in tqdm(changed_files, total=len(changed_files), desc="Back up changed rollouts", unit="file", mininterval=1):
                    require_closed(Path(item["path"]))
                    copy_verified_file(Path(item["path"]), directory / item["backup"], item["old_sha256"])
                old_digest = history_database_digest(writer, "Before")
                apply_projection_plan(writer, plan["projections"])
                update_indexed_images(writer, updates_path, update_count)
                new_digest = history_database_digest(writer, "After")
                require_home_plan_unchanged(home, plan)
                journal = {"version": 1, "status": "prepared", "home": str(home), "files": files,
                           "old_database_digest": old_digest, "new_database_digest": new_digest,
                           "database_backup": str(backup), "summary": summary}
                journal_path = directory / JOURNAL_NAME
                write_journal(journal_path, journal)
                command = [sys.executable, "-B", str(Path(__file__).with_name("codex_session_clean.py")), "--recover", str(journal_path), "--apply"]
                print("RECOVER_BEFORE_REOPENING_CODEX:", shlex.join(command), flush=True)
                for item in tqdm(changed_files, total=len(changed_files), desc="Publish cleaned rollouts", unit="file", mininterval=1):
                    publish_verified_file(directory / item["staged"], Path(item["path"]), item["new_sha256"], item["old_sha256"])
                verify_rollout_hashes(home, files, "new")
                require_codex_stopped()
                writer.commit()
                # With an unchanged DB, the durable journal is the commit marker.
                # A crash before this marker safely restores the original files.
                if old_digest == new_digest:
                    journal["status"] = "applied"
                    write_journal(journal_path, journal)
            except BaseException:
                writer.rollback()
                raise
    except BaseException:
        if journal_path is not None and journal_path.exists():
            print("failure_recovery:", str(journal_path), flush=True)
            recover_bulk_locked(journal_path)
        raise
    result = recover_bulk_locked(journal_path)
    if result != "applied":
        raise RuntimeError(f"Unexpected bulk transaction result: {result}")
    print("BULK_CLEAN_RESULT", json.dumps({"result": result, "journal": str(journal_path), **summary}), flush=True)
    return summary


def clean_history_home(home):
    home = Path(home).resolve(strict=True)
    with offline_session_lock(maintenance_roots(home)):
        return execute_bulk_locked(home)


def clean_history_session(session):
    session = Path(session).absolute()
    if session.resolve(strict=True) != session:
        raise ValueError(f"Use a canonical session path, not a symlink: {session}")
    history_roots = [parent for parent in session.parents if parent.name in ROLLOUT_DIRECTORIES]
    if len(history_roots) != 1:
        raise ValueError(f"Session must have one unambiguous sessions/archived_sessions root: {session}")
    home = history_roots[0].parent
    with offline_session_lock(maintenance_roots(home)):
        return execute_bulk_locked(home, selected_session=session)


def recover_history_home(journal_path):
    path = Path(journal_path).absolute()
    journal = load_bulk_journal(path)
    home = Path(journal["home"])
    with offline_session_lock(maintenance_roots(home), allow_pending_image_cleanup=True):
        return recover_bulk_locked(path)

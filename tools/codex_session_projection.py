"""Inspect and repair SQLite projection offsets without rewriting messages."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import partial
from pathlib import Path

from tqdm import tqdm

from codex_session_lineage import ROLLOUT_ID_PATTERN, locate_ordinals, read_header, session_root, verify_boundary
from codex_session_storage import file_signature, offline_session_lock, require_closed, require_codex_stopped, require_unchanged

HISTORY_DATABASE_NAME = "thread_history_1.sqlite"
TURN_COLUMNS = ("turn_id", "rollout_ordinal", "rollout_byte_offset", "rollout_end_ordinal", "rollout_end_byte_offset")
STATE_COLUMNS = ("next_rollout_ordinal", "next_rollout_byte_offset")
BACKUP_PAGE_BATCH = 4096
NATIVE_DELETE_TRIGGER = (
    "CREATE TRIGGER thread_realtime_items_projection_cleanup "
    "AFTER DELETE ON thread_history_projection_state BEGIN "
    "DELETE FROM thread_realtime_items WHERE thread_id = OLD.thread_id; END"
)


def connect_history(path, writable=False):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular history database: {path}")
    mode = "rw" if writable else "ro"
    connection = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=0)
    connection.execute("PRAGMA foreign_keys=ON")
    if not writable:
        connection.execute("PRAGMA query_only=ON")
    return connection


def validate_projection_schema(connection):
    for table, required in (
        ("thread_turns", {"thread_id", *TURN_COLUMNS}),
        ("thread_history_projection_state", {"thread_id", *STATE_COLUMNS}),
    ):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not required.issubset(columns):
            raise ValueError(f"Unsupported projection schema: {table}, missing {required - columns}")
        for name, sql in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)):
            if name != "thread_realtime_items_projection_cleanup" or " ".join(sql.split()) != NATIVE_DELETE_TRIGGER:
                raise ValueError(f"Unexpected trigger {name} on {table}; refusing to change offsets")


def rollout_identifier(path):
    match = ROLLOUT_ID_PATTERN.search(path.name)
    if match is None:
        raise ValueError(f"Unrecognized rollout filename: {path}")
    return match.group(1)


def require_no_projection_rewrite(paths):
    for path in map(Path, paths):
        database_path = session_root(path).parent / HISTORY_DATABASE_NAME
        if not database_path.exists():
            continue  # Legacy installations without a projection database.
        with closing(connect_history(database_path)) as connection:
            validate_projection_schema(connection)
            identifier = rollout_identifier(path)
            projected = connection.execute("SELECT 1 FROM thread_history_projection_state WHERE thread_id=?", (identifier,)).fetchone()
            turns = connection.execute("SELECT 1 FROM thread_turns WHERE thread_id=? LIMIT 1", (identifier,)).fetchone()
            if projected or turns:
                raise ValueError(
                    f"Refusing to rewrite an indexed rollout: {path}. "
                    "Changing its bytes invalidates SQLite history offsets. "
                    "Projection-aware cleanup is not implemented; this is not a force-overridable check."
                )


def ancestor_rollouts(session):
    root = session_root(session)
    paths = []
    current = session
    while True:
        if current in paths:
            raise ValueError("History lineage cycle")
        paths.append(current)
        header = read_header(current)
        base = header["record"]["payload"].get("history_base")
        if base is None:
            return paths
        matches = list(root.rglob(f"*{base['thread_id']}.jsonl"))
        if len(matches) != 1:
            raise ValueError(f"Missing or ambiguous source rollout: {base['thread_id']}")
        verify_boundary(matches[0], base["end_byte_offset"], base["end_ordinal_exclusive"])
        current = matches[0]


def projection_rows(connection, identifier):
    turns = connection.execute(
        f"SELECT {','.join(TURN_COLUMNS)} FROM thread_turns WHERE thread_id=? ORDER BY turn_id", (identifier,),
    ).fetchall()
    checkpoint = connection.execute(
        f"SELECT {','.join(STATE_COLUMNS)} FROM thread_history_projection_state WHERE thread_id=?", (identifier,),
    ).fetchone()
    if checkpoint is None:
        raise ValueError(f"Missing projection checkpoint for {identifier}; cannot infer a replacement")
    return turns, checkpoint


def projection_boundary_ordinals(turns, checkpoint):
    if any(type(value) is not int or value < 0 for value in checkpoint):
        raise ValueError("Invalid projection checkpoint")
    wanted = {checkpoint[0]}
    for turn_id, start_ordinal, start_offset, end_ordinal, end_offset in turns:
        if any(type(value) is not int or value < 0 for value in (start_ordinal, start_offset)):
            raise ValueError(f"Unsupported start boundary for {turn_id}")
        if (end_ordinal is None) != (end_offset is None):
            raise ValueError(f"Inconsistent end boundary for {turn_id}")
        wanted.add(start_ordinal)
        if end_ordinal is not None:
            if any(type(value) is not int or value < 0 for value in (end_ordinal, end_offset)) or end_ordinal < start_ordinal:
                raise ValueError(f"Invalid end boundary for {turn_id}")
            wanted.add(end_ordinal + 1)
    return wanted


def projection_plan_from_positions(path, turns, checkpoint, positions):
    new_turns = []
    for turn_id, start_ordinal, start_offset, end_ordinal, end_offset in turns:
        record = positions[start_ordinal]["record"]
        if record is None or record.get("type") != "event_msg" or record["payload"].get("turn_id") != turn_id:
            raise ValueError(f"Turn identity cannot be proved at ordinal {start_ordinal}: {path}, {turn_id}")
        new_end = None if end_ordinal is None else positions[end_ordinal + 1]["offset"]
        new_turns.append((turn_id, start_ordinal, positions[start_ordinal]["offset"], end_ordinal, new_end))
    return {"path": path, "id": rollout_identifier(path), "old_turns": turns, "new_turns": new_turns,
            "old_checkpoint": checkpoint, "new_checkpoint": (checkpoint[0], positions[checkpoint[0]]["offset"])}


def projection_plan_changed(plan):
    return plan["old_turns"] != plan["new_turns"] or plan["old_checkpoint"] != plan["new_checkpoint"]


def prepare_projection_plan(session, connection):
    validate_projection_schema(connection)
    plans = []
    signatures = {}
    paths = ancestor_rollouts(session)
    for path in tqdm(paths, total=len(paths), desc="Planning projection repair", unit="rollout"):
        signatures[path] = file_signature(path)
        turns, checkpoint = projection_rows(connection, rollout_identifier(path))
        positions = locate_ordinals(path, projection_boundary_ordinals(turns, checkpoint))
        plans.append(projection_plan_from_positions(path, turns, checkpoint, positions))
    require_unchanged(signatures)
    return plans, signatures


def print_projection_plan(plans):
    for plan in plans:
        changed = sum(before != after for before, after in zip(plan["old_turns"], plan["new_turns"]))
        print(json.dumps({"rollout": str(plan["path"]), "turns": len(plan["old_turns"]), "turn_offsets_changed": changed,
                          "old_next_byte": plan["old_checkpoint"][1], "new_next_byte": plan["new_checkpoint"][1],
                          "next_ordinal_unchanged": plan["old_checkpoint"][0]}), flush=True)


def update_backup_progress(progress, status, remaining, total):
    progress.total = total
    progress.update(total - remaining - progress.n)


def backup_history_database(database_path, plans):
    directory = database_path.parent / "session_maintenance_backups"
    directory.mkdir(mode=0o700, exist_ok=True)
    destination = directory / ("thread_history_1.before-offset-repair-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".sqlite")
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with closing(connect_history(database_path)) as reader, closing(sqlite3.connect(destination)) as writer:
        pages = reader.execute("PRAGMA page_count").fetchone()[0]
        with tqdm(total=pages, desc="Backing up history DB", unit="page", mininterval=1) as progress:
            reader.backup(writer, pages=BACKUP_PAGE_BATCH, progress=partial(update_backup_progress, progress))
        if writer.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError(f"Backup integrity check failed: {destination}")
        for plan in plans:
            if projection_rows(writer, plan["id"]) != (plan["old_turns"], plan["old_checkpoint"]):
                raise RuntimeError("Backup does not match the pre-repair database snapshot")
    with destination.open("rb") as saved:
        os.fsync(saved.fileno())
    print(f"database_backup: {destination}", flush=True)
    return destination


def apply_projection_plan(connection, plans):
    for plan in plans:
        if projection_rows(connection, plan["id"]) != (plan["old_turns"], plan["old_checkpoint"]):
            raise RuntimeError("Projection changed since planning")
        for before, after in zip(plan["old_turns"], plan["new_turns"]):
            if before == after:
                continue
            changed = connection.execute(
                "UPDATE thread_turns SET rollout_byte_offset=?,rollout_end_byte_offset=? WHERE thread_id=? AND turn_id=?",
                (after[2], after[4], plan["id"], after[0]),
            ).rowcount
            if changed != 1:
                raise RuntimeError("Unexpected turn update count")
        if plan["old_checkpoint"] != plan["new_checkpoint"]:
            changed = connection.execute("UPDATE thread_history_projection_state SET next_rollout_byte_offset=? WHERE thread_id=?", (plan["new_checkpoint"][1], plan["id"])).rowcount
            if changed != 1:
                raise RuntimeError("Unexpected checkpoint update count")
        if projection_rows(connection, plan["id"]) != (plan["new_turns"], plan["new_checkpoint"]):
            raise RuntimeError("Projection read-back failed")


def repair_projection(session, apply_changes=False):
    session = Path(session).absolute()
    root = session_root(session)
    database_path = root.parent / HISTORY_DATABASE_NAME
    if not apply_changes:
        with closing(connect_history(database_path)) as reader:
            reader.execute("BEGIN")
            plans, signatures = prepare_projection_plan(session, reader)
            print_projection_plan(plans)
            return plans
    with offline_session_lock([root.parent, root]):
        require_closed(database_path)
        with closing(connect_history(database_path, writable=True)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            try:
                plans, signatures = prepare_projection_plan(session, writer)
                print_projection_plan(plans)
                if not any(map(projection_plan_changed, plans)):
                    writer.rollback()
                    print("already_correct: true")
                    return plans
                backup_history_database(database_path, plans)
                require_codex_stopped()
                require_unchanged(signatures)
                apply_projection_plan(writer, plans)
                require_codex_stopped()
                require_unchanged(signatures)
                writer.commit()
            except BaseException:
                writer.rollback()
                raise
        with closing(connect_history(database_path)) as reader:
            for plan in plans:
                if projection_rows(reader, plan["id"]) != (plan["new_turns"], plan["new_checkpoint"]):
                    raise RuntimeError("Post-commit projection verification failed")
        print("projection_offsets_repaired: true\nmessages_deleted: 0\nrollout_files_rewritten: 0")
        print("Reopen the conversation in Codex so its native projector reads the newer records.")
        return plans

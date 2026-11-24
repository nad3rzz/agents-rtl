"""Durable recovery for the offline, experimental image-clean transaction.

The JSONL rename and SQLite commit are NOT one atomic operation. Keep Codex
closed until completion or recovery. Never restore the full DB over newer work.
"""

import json
import os
import shutil
from contextlib import closing
from pathlib import Path

from codex_session_image_projection import projected_items
from codex_session_lineage import session_root
from codex_session_projection import (
    HISTORY_DATABASE_NAME,
    connect_history,
    projection_rows,
    rollout_identifier,
)
from codex_session_storage import (
    COPY_CHUNK_BYTES,
    create_staged_file,
    file_signature,
    require_closed,
    require_codex_stopped,
    sha256_file,
)

JOURNAL_NAME = "transaction.json"
TRANSACTION_PREFIX = "image-clean-transaction-"
TERMINAL_STATES = {"applied", "rolled_back"}


def fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_journal(path, journal):
    staged_path = None
    try:
        with create_staged_file(path) as staged:
            staged_path = Path(staged.name)
            staged.write((json.dumps(journal, ensure_ascii=False) + "\n").encode())
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(staged_path, path)
        fsync_directory(path.parent)
    finally:
        if staged_path is not None and staged_path.exists():
            staged_path.unlink()


def copy_verified_file(source, destination, expected_hash):
    file_signature(source)
    with source.open("rb") as reader, destination.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
        writer.flush()
        os.fsync(writer.fileno())
    if sha256_file(source) != expected_hash or sha256_file(destination) != expected_hash:
        raise RuntimeError("File changed while preparing transaction copy")
    fsync_directory(destination.parent)


def publish_verified_file(source, destination, source_hash, destination_hash):
    require_codex_stopped()
    require_closed(destination)
    file_signature(destination)
    if sha256_file(destination) != destination_hash:
        raise RuntimeError("Refusing to overwrite an unexpected rollout")
    staged_path = None
    try:
        with create_staged_file(destination) as staged:
            staged_path = Path(staged.name)
            file_signature(source)
            with source.open("rb") as reader:
                shutil.copyfileobj(reader, staged, COPY_CHUNK_BYTES)
            staged.flush()
            os.fsync(staged.fileno())
        if sha256_file(source) != source_hash or sha256_file(staged_path) != source_hash:
            raise RuntimeError("Transaction source copy has changed")
        require_codex_stopped()
        require_closed(destination)
        if sha256_file(destination) != destination_hash:
            raise RuntimeError("Rollout changed before publication")
        os.replace(staged_path, destination)
        fsync_directory(destination.parent)
        if sha256_file(destination) != source_hash:
            raise RuntimeError("Published rollout hash mismatch")
    finally:
        if staged_path is not None and staged_path.exists():
            staged_path.unlink()


def database_state(connection, identifier):
    turns, checkpoint = projection_rows(connection, identifier)
    return {"turns": [list(row) for row in turns], "checkpoint": list(checkpoint),
            "items": projected_items(connection, identifier)}


def load_journal(path):
    file_signature(path)
    journal = json.loads(path.read_text())
    if journal["version"] != 1 or journal["status"] not in {"prepared", *TERMINAL_STATES}:
        raise ValueError("Unsupported transaction journal")
    source = Path(journal["session"])
    home = session_root(source).parent
    if not source.is_absolute() or source.resolve() != source:
        raise ValueError("Journal source must be a canonical absolute path")
    if path.parent.parent != home / "session_maintenance_backups" or not path.parent.name.startswith(TRANSACTION_PREFIX):
        raise ValueError("Journal is outside its session home's transaction directory")
    if path.parent.resolve() != path.parent or journal["identifier"] != rollout_identifier(source):
        raise ValueError("Journal identity/path mismatch")
    return journal


def require_no_pending_transactions(home):
    directory = home / "session_maintenance_backups"
    for path in sorted(directory.glob(TRANSACTION_PREFIX + "*/" + JOURNAL_NAME)):
        journal = load_journal(path)
        if journal["status"] not in TERMINAL_STATES:
            raise RuntimeError(f"Recover the pending transaction before another apply: {path}")


def recover_transaction_locked(path):
    """Caller holds the home/session offline lock; actual state wins over status."""
    journal = load_journal(path)
    source = Path(journal["session"])
    database = session_root(source).parent / HISTORY_DATABASE_NAME
    require_codex_stopped()
    require_closed(source)
    require_closed(database)
    with closing(connect_history(database, writable=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            current = database_state(connection, journal["identifier"])
            current_hash = sha256_file(source)
            if current == journal["old_database"]:
                if current_hash == journal["new_sha256"]:
                    publish_verified_file(path.parent / "original.jsonl", source,
                                          journal["old_sha256"], journal["new_sha256"])
                elif current_hash != journal["old_sha256"]:
                    raise RuntimeError("Recovery refused: rollout changed after the transaction")
                result = "rolled_back"
            elif current == journal["new_database"] and current_hash == journal["new_sha256"]:
                result = "applied"
            else:
                raise RuntimeError("Recovery refused: DB/file state is not a known transaction boundary")
            journal["status"] = result
            write_journal(path, journal)
        finally:
            connection.rollback()  # Recovery never rewrites the database.
    return result

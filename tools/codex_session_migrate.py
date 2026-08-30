#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime


DESTINATION_CODEX_ROOT = "/home/nad3r/.codex"
SOURCE_CODEX_ROOTS = [
    "/home/nad3r/.codex",
    "/home/nad3r/.codex-vscode",
    "/home/nad3r/.codex-antigravity",
]
SESSION_BUCKET_NAMES = ("sessions", "archived_sessions")
IGNORED_SESSION_FILENAME_MARKERS = (".doctor-bak-", ".restore-bak-", ".doctor-tmp")
SESSION_ID_PATTERN = re.compile(
    r"rollout-.*?-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)
SESSION_DATE_PATTERN = re.compile(r"^rollout-(\d{4})-(\d{2})-(\d{2})T")
OPEN_PROCESS_PATTERNS = (
    "/usr/share/code/code",
    "/usr/share/antigravity/antigravity",
    "codex app-server",
    "agents-rtl-helper-linux",
)


def parse_iso_timestamp(timestamp_value):
    if not timestamp_value:
        return None
    try:
        return datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def session_id_from_filename(session_path):
    match = SESSION_ID_PATTERN.search(os.path.basename(session_path))
    if not match:
        raise RuntimeError("cannot parse session id: " + session_path)
    return match.group(1)


def session_date_parts_from_filename(session_path):
    match = SESSION_DATE_PATTERN.search(os.path.basename(session_path))
    if not match:
        raise RuntimeError("cannot parse session date: " + session_path)
    return match.groups()


def last_jsonl_timestamp(session_path):
    last_timestamp = None
    line_count = 0
    with open(session_path, encoding="utf-8") as session_file:
        for line in session_file:
            if not line.strip():
                continue
            line_count += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed_timestamp = parse_iso_timestamp(row.get("timestamp"))
            if parsed_timestamp is not None:
                last_timestamp = parsed_timestamp
    return last_timestamp, line_count


def iter_session_files(root_path):
    for bucket_name in SESSION_BUCKET_NAMES:
        bucket_path = os.path.join(root_path, bucket_name)
        if not os.path.isdir(bucket_path):
            continue
        for dirpath, dirnames, filenames in os.walk(bucket_path):
            dirnames[:] = [name for name in dirnames if name not in {".tmp", "tmp"}]
            for filename in filenames:
                if not filename.endswith(".jsonl"):
                    continue
                if any(marker in filename for marker in IGNORED_SESSION_FILENAME_MARKERS):
                    continue
                yield root_path, bucket_name, os.path.join(dirpath, filename)


def destination_path_for_session(bucket_name, session_path):
    basename = os.path.basename(session_path)
    if bucket_name == "archived_sessions":
        return os.path.join(DESTINATION_CODEX_ROOT, "archived_sessions", basename)
    year, month, day = session_date_parts_from_filename(session_path)
    return os.path.join(DESTINATION_CODEX_ROOT, "sessions", year, month, day, basename)


def possible_destination_paths_for_session(session_path):
    basename = os.path.basename(session_path)
    year, month, day = session_date_parts_from_filename(session_path)
    return [
        os.path.join(DESTINATION_CODEX_ROOT, "archived_sessions", basename),
        os.path.join(DESTINATION_CODEX_ROOT, "sessions", year, month, day, basename),
    ]


def collect_session_copies():
    sessions_by_id = defaultdict(list)
    for root_path in SOURCE_CODEX_ROOTS:
        for source_root, bucket_name, session_path in iter_session_files(root_path):
            file_stat = os.stat(session_path)
            session_id = session_id_from_filename(session_path)
            last_timestamp, line_count = last_jsonl_timestamp(session_path)
            sessions_by_id[session_id].append(
                {
                    "id": session_id,
                    "root": source_root,
                    "bucket": bucket_name,
                    "path": session_path,
                    "last_timestamp": last_timestamp,
                    "mtime": file_stat.st_mtime,
                    "size": file_stat.st_size,
                    "line_count": line_count,
                }
            )
    return sessions_by_id


def choose_latest_sessions(sessions_by_id):
    chosen_sessions = {}
    for session_id, session_copies in sessions_by_id.items():
        chosen_session = sorted(
            session_copies,
            key=lambda item: (item["last_timestamp"] or 0, item["size"], item["mtime"]),
            reverse=True,
        )[0]
        chosen_session["dest_path"] = destination_path_for_session(chosen_session["bucket"], chosen_session["path"])
        chosen_sessions[session_id] = chosen_session
    return chosen_sessions


def read_session_index_rows():
    rows_by_id = {}
    for root_path in SOURCE_CODEX_ROOTS:
        index_path = os.path.join(root_path, "session_index.jsonl")
        if not os.path.exists(index_path):
            continue
        with open(index_path, encoding="utf-8") as index_file:
            for line in index_file:
                if not line.strip():
                    continue
                row = json.loads(line)
                row_id = row.get("id")
                if not row_id:
                    continue
                row_timestamp = parse_iso_timestamp(row.get("updated_at")) or 0
                current_row = rows_by_id.get(row_id)
                current_timestamp = parse_iso_timestamp(current_row.get("updated_at")) if current_row else -1
                if current_row is None or row_timestamp > (current_timestamp or 0):
                    rows_by_id[row_id] = row
    return rows_by_id


def read_destination_session_index_ids():
    destination_index_path = os.path.join(DESTINATION_CODEX_ROOT, "session_index.jsonl")
    if not os.path.exists(destination_index_path):
        return set()
    destination_ids = set()
    with open(destination_index_path, encoding="utf-8") as index_file:
        for line in index_file:
            if line.strip():
                destination_ids.add(json.loads(line).get("id"))
    return destination_ids


def sqlite_connection_for_readonly(database_path):
    connection = sqlite3.connect("file:" + database_path + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def thread_score(thread_row):
    return thread_row.get("updated_at_ms") or ((thread_row.get("updated_at") or 0) * 1000)


def read_latest_thread_rows(chosen_sessions):
    latest_rows_by_id = {}
    for root_path in SOURCE_CODEX_ROOTS:
        database_path = os.path.join(root_path, "state_5.sqlite")
        if not os.path.exists(database_path):
            continue
        connection = sqlite_connection_for_readonly(database_path)
        try:
            for row in connection.execute("select * from threads"):
                row_dict = dict(row)
                row_id = row_dict["id"]
                if row_id not in chosen_sessions:
                    continue
                current_row = latest_rows_by_id.get(row_id)
                if current_row is None or thread_score(row_dict) > thread_score(current_row):
                    latest_rows_by_id[row_id] = row_dict
        finally:
            connection.close()
    return latest_rows_by_id


def read_destination_thread_rows():
    database_path = os.path.join(DESTINATION_CODEX_ROOT, "state_5.sqlite")
    connection = sqlite_connection_for_readonly(database_path)
    try:
        return {row["id"]: dict(row) for row in connection.execute("select * from threads")}
    finally:
        connection.close()


def build_plan():
    sessions_by_id = collect_session_copies()
    chosen_sessions = choose_latest_sessions(sessions_by_id)
    copy_new_sessions = []
    replace_sessions = []
    already_latest_sessions = []
    duplicate_destination_paths = []

    for session_id, chosen_session in chosen_sessions.items():
        destination_path = chosen_session["dest_path"]
        if not os.path.exists(destination_path):
            copy_new_sessions.append(chosen_session)
        else:
            destination_stat = os.stat(destination_path)
            destination_timestamp, _line_count = last_jsonl_timestamp(destination_path)
            same_file = os.path.abspath(destination_path) == os.path.abspath(chosen_session["path"])
            destination_is_same_content = (
                (destination_timestamp or 0) >= (chosen_session["last_timestamp"] or 0)
                and destination_stat.st_size == chosen_session["size"]
            )
            if same_file or destination_is_same_content:
                already_latest_sessions.append(chosen_session)
            else:
                replace_sessions.append(
                    {
                        "session": chosen_session,
                        "destination_path": destination_path,
                    }
                )
        for possible_destination_path in possible_destination_paths_for_session(chosen_session["path"]):
            if possible_destination_path != destination_path and os.path.exists(possible_destination_path):
                duplicate_destination_paths.append(
                    {
                        "id": session_id,
                        "older_path": possible_destination_path,
                        "chosen_path": destination_path,
                    }
                )

    index_rows_by_id = read_session_index_rows()
    destination_index_ids = read_destination_session_index_ids()
    latest_thread_rows = read_latest_thread_rows(chosen_sessions)
    destination_thread_rows = read_destination_thread_rows()
    insert_thread_rows = []
    update_thread_rows = []
    already_current_thread_rows = []

    for session_id, source_thread_row in latest_thread_rows.items():
        chosen_session = chosen_sessions[session_id]
        destination_thread_row = destination_thread_rows.get(session_id)
        chosen_archived = 1 if chosen_session["bucket"] == "archived_sessions" else 0
        if destination_thread_row is None:
            insert_thread_rows.append({"id": session_id, "row": source_thread_row, "session": chosen_session})
            continue
        row_needs_update = (
            thread_score(source_thread_row) > thread_score(destination_thread_row)
            or destination_thread_row.get("rollout_path") != chosen_session["dest_path"]
            or int(destination_thread_row.get("archived") or 0) != chosen_archived
        )
        if row_needs_update:
            update_thread_rows.append(
                {
                    "id": session_id,
                    "source_row": source_thread_row,
                    "destination_row": destination_thread_row,
                    "session": chosen_session,
                }
            )
        else:
            already_current_thread_rows.append({"id": session_id, "row": source_thread_row, "session": chosen_session})

    return {
        "chosen_sessions": chosen_sessions,
        "copy_new_sessions": copy_new_sessions,
        "replace_sessions": replace_sessions,
        "already_latest_sessions": already_latest_sessions,
        "duplicate_destination_paths": duplicate_destination_paths,
        "index_rows_by_id": index_rows_by_id,
        "index_missing_ids": set(index_rows_by_id) - destination_index_ids,
        "latest_thread_rows": latest_thread_rows,
        "insert_thread_rows": insert_thread_rows,
        "update_thread_rows": update_thread_rows,
        "already_current_thread_rows": already_current_thread_rows,
    }


def backup_path_for(original_path, backup_root):
    relative_path = os.path.relpath(original_path, DESTINATION_CODEX_ROOT)
    return os.path.join(backup_root, relative_path)


def backup_file_if_exists(path, backup_root):
    if not os.path.exists(path):
        return
    backup_path = backup_path_for(path, backup_root)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.copy2(path, backup_path)


def backup_state_files(backup_root):
    for filename in ("state_5.sqlite", "state_5.sqlite-wal", "state_5.sqlite-shm", "session_index.jsonl"):
        backup_file_if_exists(os.path.join(DESTINATION_CODEX_ROOT, filename), backup_root)


def write_merged_session_index(index_rows_by_id, backup_root):
    destination_index_path = os.path.join(DESTINATION_CODEX_ROOT, "session_index.jsonl")
    backup_file_if_exists(destination_index_path, backup_root)
    sorted_rows = sorted(index_rows_by_id.values(), key=lambda row: parse_iso_timestamp(row.get("updated_at")) or 0)
    temporary_path = destination_index_path + ".migration-tmp"
    with open(temporary_path, "w", encoding="utf-8") as index_file:
        for row in sorted_rows:
            index_file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary_path, destination_index_path)


def copy_session_to_destination(chosen_session, backup_root):
    destination_path = chosen_session["dest_path"]
    backup_file_if_exists(destination_path, backup_root)
    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    shutil.copy2(chosen_session["path"], destination_path)


def backup_duplicate_destination_paths(duplicate_destination_paths, backup_root):
    for duplicate_destination in duplicate_destination_paths:
        backup_file_if_exists(duplicate_destination["older_path"], backup_root)


def normalized_thread_row_for_destination(source_row, chosen_session):
    destination_row = dict(source_row)
    destination_row["rollout_path"] = chosen_session["dest_path"]
    destination_row["archived"] = 1 if chosen_session["bucket"] == "archived_sessions" else 0
    return destination_row


def upsert_threads(latest_thread_rows, chosen_sessions):
    destination_database_path = os.path.join(DESTINATION_CODEX_ROOT, "state_5.sqlite")
    connection = sqlite3.connect(destination_database_path)
    try:
        connection.row_factory = sqlite3.Row
        columns = [row[1] for row in connection.execute("pragma table_info(threads)").fetchall()]
        placeholders = ",".join("?" for _column in columns)
        column_list = ",".join(columns)
        update_assignments = ",".join(column + "=excluded." + column for column in columns if column != "id")
        sql = (
            "insert into threads (" + column_list + ") values (" + placeholders + ") "
            "on conflict(id) do update set " + update_assignments
        )
        for session_id, source_row in latest_thread_rows.items():
            destination_row = normalized_thread_row_for_destination(source_row, chosen_sessions[session_id])
            values = [destination_row.get(column) for column in columns]
            connection.execute(sql, values)
        connection.commit()
    finally:
        connection.close()


def open_process_lines():
    result = subprocess.run(["pgrep", "-af", "code|Code|antigravity|Antigravity|codex"], capture_output=True, text=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    matching_lines = []
    for line in lines:
        if os.path.basename(__file__) in line:
            continue
        if any(pattern in line for pattern in OPEN_PROCESS_PATTERNS):
            matching_lines.append(line)
    return matching_lines


def assert_no_open_programs(allow_open_programs):
    matching_lines = open_process_lines()
    if allow_open_programs or not matching_lines:
        return
    print("error: close VS Code, Antigravity, and Codex app-server before apply.", file=sys.stderr)
    print("open_processes:", file=sys.stderr)
    for line in matching_lines[:20]:
        print(line, file=sys.stderr)
    raise SystemExit(2)


def print_plan(plan):
    print("dry_run: true")
    print("jsonl_unique_conversations:", len(plan["chosen_sessions"]))
    print("jsonl_copy_new_to_codex:", len(plan["copy_new_sessions"]))
    print("jsonl_replace_existing_in_codex:", len(plan["replace_sessions"]))
    print("jsonl_already_latest_in_codex:", len(plan["already_latest_sessions"]))
    print("jsonl_duplicate_dest_paths_to_backup:", len(plan["duplicate_destination_paths"]))
    print("session_index_unique_after_merge:", len(plan["index_rows_by_id"]))
    print("session_index_missing_or_new_ids_for_codex:", len(plan["index_missing_ids"]))
    print("state_threads_insert_missing_in_codex:", len(plan["insert_thread_rows"]))
    print("state_threads_update_existing_in_codex:", len(plan["update_thread_rows"]))
    print("state_threads_already_ok:", len(plan["already_current_thread_rows"]))


def apply_plan(plan, allow_open_programs):
    assert_no_open_programs(allow_open_programs)
    backup_root = os.path.join(
        DESTINATION_CODEX_ROOT,
        "session_migration_backups",
        time.strftime("%Y%m%d-%H%M%S"),
    )
    os.makedirs(backup_root, exist_ok=False)
    backup_state_files(backup_root)
    for chosen_session in plan["copy_new_sessions"]:
        copy_session_to_destination(chosen_session, backup_root)
    for replace_action in plan["replace_sessions"]:
        copy_session_to_destination(replace_action["session"], backup_root)
    backup_duplicate_destination_paths(plan["duplicate_destination_paths"], backup_root)
    write_merged_session_index(plan["index_rows_by_id"], backup_root)
    upsert_threads(plan["latest_thread_rows"], plan["chosen_sessions"])
    print("mode: apply")
    print("backup_root:", backup_root)
    print("jsonl_copied_new:", len(plan["copy_new_sessions"]))
    print("jsonl_replaced:", len(plan["replace_sessions"]))
    print("session_index_rows:", len(plan["index_rows_by_id"]))
    print("state_threads_upserted:", len(plan["latest_thread_rows"]))


def main():
    parser = argparse.ArgumentParser(prog="codex-session-migrate")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--allow-open-programs", action="store_true")
    args = parser.parse_args()

    plan = build_plan()
    if args.command in (None, "plan"):
        print_plan(plan)
        return
    if args.command == "apply":
        apply_plan(plan, args.allow_open_programs)
        return
    raise RuntimeError("unknown command: " + args.command)


if __name__ == "__main__":
    main()

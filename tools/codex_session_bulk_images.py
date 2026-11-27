"""Scoped image cleanup with whole-home offset and lineage validation.

Only structured image content is removed. Text (including code containing data
URLs) is preserved. Image-only messages retain their identity and empty content;
no replacement text is inserted.
"""

import hashlib
import json
import os
from collections import defaultdict

from codex_session_history_repair import read_home_inventory
from codex_session_image_projection import ITEM_TABLE_KEYS
from codex_session_lineage import history_links
from codex_session_projection import (
    HISTORY_DATABASE_NAME,
    projection_boundary_ordinals,
    projection_plan_changed,
    projection_plan_from_positions,
    projection_rows,
    validate_projection_schema,
)
from codex_session_repair_lineage import fixed_length_header
from codex_session_storage import require_unchanged
from tqdm import tqdm

REMOVED_IMAGE = object()
PROJECTION_KEYS = {
    "thread_turns": ("thread_id", "turn_id"),
    "thread_history_projection_state": ("thread_id",),
    **ITEM_TABLE_KEYS,
}
DATABASE_FINGERPRINT_KEYS = {**PROJECTION_KEYS, "_sqlx_migrations": ("version",)}


def remove_structured_images(value, statistics):
    if isinstance(value, list):
        retained = []
        for child in value:
            cleaned = remove_structured_images(child, statistics)
            if cleaned is not REMOVED_IMAGE:
                retained.append(cleaned)
        return retained
    if not isinstance(value, dict):
        return value
    kind = value.get("type")
    if kind in ("input_image", "image", "image_url"):
        url = value.get("image_url", value.get("url"))
        valid_url = isinstance(url, str) and bool(url)
        valid_url_object = isinstance(url, dict) and isinstance(url.get("url"), str) and bool(url["url"])
        valid_mcp = (kind == "image" and isinstance(value.get("data"), str) and bool(value["data"])
                     and isinstance(value.get("mimeType"), str) and value["mimeType"].startswith("image/"))
        if not (valid_url or valid_url_object or valid_mcp):
            raise ValueError(f"Incomplete or unsupported structured image: {sorted(value)}")
        statistics["image_parts_removed"] += 1
        return REMOVED_IMAGE
    cleaned = {}
    for key, child in value.items():
        if kind == "user_message" and key in ("images", "local_images"):
            if not isinstance(child, list) or any(not isinstance(image, str) for image in child):
                raise ValueError(f"Unsupported user_message.{key}")
            statistics["image_references_removed"] += len(child)
            cleaned[key] = []
        else:
            result = remove_structured_images(child, statistics)
            if result is REMOVED_IMAGE:
                raise ValueError(f"Image outside a content list at {key}; refusing field removal")
            cleaned[key] = result
    if kind in ("message", "userMessage", "UserMessage") and value.get("content") and cleaned.get("content") == []:
        statistics["image_only_messages_emptied"] += 1
    return cleaned


def image_statistics():
    return {"image_parts_removed": 0, "image_references_removed": 0, "image_only_messages_emptied": 0}


def encode_record(record):
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def boundary_identity(record):
    if record is None:
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise TypeError("Expected a record payload object")
    return {"type": record["type"], "payload": {"turn_id": payload.get("turn_id")}}


def scan_rollout(entry, wanted_ordinals, require_ordinals, destination=None, replacement_header=None, *, clean_images):
    original_hash, cleaned_hash = hashlib.sha256(), hashlib.sha256()
    original_offset = cleaned_offset = 0
    previous_ordinal = None
    original_positions, cleaned_positions = {}, {}
    statistics = image_statistics()
    with entry["path"].open("rb") as source, tqdm(
        total=entry["signature"][2], desc=("Stage " if destination else "Plan ") + entry["path"].name[:27],
        unit="B", unit_scale=True, mininterval=1,
    ) as progress:
        for line_number, raw in enumerate(source, 1):
            if not raw.endswith(b"\n"):
                raise ValueError(f"Incomplete JSONL record: {entry['path']}:{line_number}")
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise TypeError(f"Non-object record: {entry['path']}:{line_number}")
            ordinal = record.get("ordinal")
            if require_ordinals:
                if type(ordinal) is not int or (previous_ordinal is not None and ordinal != previous_ordinal + 1):
                    raise ValueError(f"Non-contiguous native ordinals: {entry['path']}:{line_number}")
                previous_ordinal = ordinal
                if ordinal in wanted_ordinals:
                    identity = boundary_identity(record)
                    original_positions[ordinal] = {"offset": original_offset, "record": identity}
                    cleaned_positions[ordinal] = {"offset": cleaned_offset, "record": identity}
            if line_number == 1:
                if raw != entry["raw"]:
                    raise RuntimeError(f"Header changed: {entry['path']}")
                encoded = raw if replacement_header is None else replacement_header
                if len(encoded) != len(raw):
                    raise ValueError("Lineage header must retain its exact byte length")
            elif clean_images:
                cleaned = remove_structured_images(record, statistics)
                if cleaned is REMOVED_IMAGE:
                    raise ValueError("Cannot delete an entire rollout record")
                encoded = raw if cleaned == record else encode_record(cleaned)
            else:
                encoded = raw
            original_hash.update(raw)
            cleaned_hash.update(encoded)
            original_offset += len(raw)
            cleaned_offset += len(encoded)
            if destination is not None:
                destination.write(encoded)
            progress.update(len(raw))
    if previous_ordinal is not None and previous_ordinal + 1 in wanted_ordinals:
        original_positions[previous_ordinal + 1] = {"offset": original_offset, "record": None}
        cleaned_positions[previous_ordinal + 1] = {"offset": cleaned_offset, "record": None}
    if set(original_positions) != set(wanted_ordinals):
        raise ValueError(f"Missing native boundary ordinals: {entry['path']}")
    require_unchanged({entry["path"]: entry["signature"]})
    return {"old_positions": original_positions, "new_positions": cleaned_positions,
            "old_hash": original_hash.hexdigest(), "new_hash": cleaned_hash.hexdigest(),
            "old_bytes": original_offset, "new_bytes": cleaned_offset, "statistics": statistics}


def validate_bulk_schema(connection):
    validate_projection_schema(connection)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables != {*PROJECTION_KEYS, "_sqlx_migrations"}:
        raise ValueError(f"Unsupported history database tables: {sorted(tables)}")
    for table, keys in ITEM_TABLE_KEYS.items():
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not {*keys, "item_json", "item_type"}.issubset(columns):
            raise ValueError(f"Unsupported projected item columns: {table}")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchone():
            raise ValueError(f"Unsupported trigger on {table}")


def image_cleanup_identifiers(inventory, links, selected_session):
    if selected_session is None:
        return set(inventory)
    identifiers_by_path = {entry["path"]: identifier for identifier, entry in inventory.items()}
    if selected_session not in identifiers_by_path:
        raise ValueError(f"Selected session is not in the history inventory: {selected_session}")
    parents = {identifiers_by_path[link["child"]["path"]]: link["base"]["thread_id"] for link in links}
    selected_identifier = identifiers_by_path[selected_session]
    selected_identifiers = {selected_identifier}
    while selected_identifier in parents:
        selected_identifier = parents[selected_identifier]
        if selected_identifier in selected_identifiers:
            raise ValueError(f"History lineage cycle: {selected_identifier}")
        selected_identifiers.add(selected_identifier)
    return selected_identifiers


def plan_home_images(home, connection, selected_session=None):
    if sorted(path.name for path in home.glob("thread_history*.sqlite")) != [HISTORY_DATABASE_NAME]:
        raise ValueError("Unsupported history database version")
    validate_bulk_schema(connection)
    inventory = read_home_inventory(home)
    for entry in inventory.values():
        if entry["path"].resolve(strict=True) != entry["path"]:
            raise ValueError(f"Use canonical rollout paths; symlink parents are unsupported: {entry['path']}")
    links = history_links(inventory)
    cleanup_identifiers = image_cleanup_identifiers(inventory, links, selected_session)
    wanted = defaultdict(set)
    for link in links:
        wanted[link["base"]["thread_id"]].add(link["base"]["end_ordinal_exclusive"])
    indexed = {row[0] for row in connection.execute("SELECT thread_id FROM thread_history_projection_state")}
    referenced = set(indexed)
    for table in ("thread_turns", *ITEM_TABLE_KEYS):
        referenced.update(row[0] for row in connection.execute(f"SELECT DISTINCT thread_id FROM {table}"))
    if referenced - inventory.keys():
        raise ValueError(f"Indexed histories missing on disk: {sorted(referenced - inventory.keys())}")
    if referenced - indexed:
        raise ValueError(f"History rows missing projection checkpoints: {sorted(referenced - indexed)}")
    projections, scans, boundaries = [], {}, {}
    for identifier, entry in tqdm(inventory.items(), total=len(inventory), desc="Plan conversation images", unit="file", mininterval=1):
        if identifier in indexed:
            turns, checkpoint = projection_rows(connection, identifier)
            wanted[identifier].update(projection_boundary_ordinals(turns, checkpoint))
        require_ordinals = bool(wanted[identifier]) or entry["record"]["payload"].get("history_mode") == "paginated"
        clean_images = identifier in cleanup_identifiers
        result = scan_rollout(entry, wanted[identifier], require_ordinals, clean_images=clean_images)
        scans[identifier] = {**result, "wanted": wanted[identifier], "require_ordinals": require_ordinals,
                             "clean_images": clean_images}
        boundaries[identifier] = result["new_positions"]
        if identifier in indexed:
            original = projection_plan_from_positions(entry["path"], turns, checkpoint, result["old_positions"])
            if projection_plan_changed(original):
                raise ValueError(f"Existing projection offsets are invalid; repair before cleaning: {entry['path']}")
            projections.append(projection_plan_from_positions(entry["path"], turns, checkpoint, result["new_positions"]))
    headers = {}
    for link in links:
        identifier = link["base"]["thread_id"]
        ordinal = link["base"]["end_ordinal_exclusive"]
        if scans[identifier]["old_positions"][ordinal]["offset"] != link["base"]["end_byte_offset"]:
            raise ValueError(f"Existing lineage offset is invalid: {link['child']['path']}")
        new_offset = boundaries[identifier][ordinal]["offset"]
        if new_offset != link["base"]["end_byte_offset"]:
            headers[link["child"]["path"]] = fixed_length_header(link["child"], new_offset)
    return {"inventory": inventory, "signatures": {entry["path"]: entry["signature"] for entry in inventory.values()},
            "scans": scans, "projections": projections, "headers": headers,
            "cleanup_identifiers": cleanup_identifiers}


def stage_home_images(plan, directory):
    files = []
    for identifier, entry in tqdm(plan["inventory"].items(), total=len(plan["inventory"]), desc="Stage changed rollouts", unit="file"):
        scan = plan["scans"][identifier]
        changed = scan["old_hash"] != scan["new_hash"] or entry["path"] in plan["headers"]
        item = {"path": str(entry["path"]), "old_sha256": scan["old_hash"], "new_sha256": scan["old_hash"], "changed": changed}
        if changed:
            staged = directory / (identifier + ".cleaned")
            with staged.open("xb") as destination:
                os.fchmod(destination.fileno(), 0o600)
                result = scan_rollout(entry, scan["wanted"], scan["require_ordinals"], destination,
                                      plan["headers"].get(entry["path"]), clean_images=scan["clean_images"])
                destination.flush()
                os.fsync(destination.fileno())
            if result["old_hash"] != scan["old_hash"] or result["new_positions"] != scan["new_positions"] or result["statistics"] != scan["statistics"]:
                raise RuntimeError(f"Staged cleanup differs from plan: {entry['path']}")
            item.update({"new_sha256": result["new_hash"], "staged": staged.name, "backup": identifier + ".original"})
        files.append(item)
    return files


def history_database_digest(connection, label):
    digest = hashlib.sha256()
    schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    digest.update(encode_record(schema))
    for table, keys in DATABASE_FINGERPRINT_KEYS.items():
        count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        cursor = connection.execute(f"SELECT * FROM {table} ORDER BY {','.join(keys)}")
        digest.update(encode_record([table, [column[0] for column in cursor.description]]))
        for row in tqdm(cursor, total=count, desc=label + " " + table, unit="row", mininterval=1):
            digest.update(encode_record([{"blob_hex": value.hex()} if isinstance(value, bytes) else value for value in row]))
    return digest.hexdigest()


def stage_projected_images(connection, destination, cleanup_identifiers):
    if not cleanup_identifiers:
        raise ValueError("Image cleanup scope must contain at least one rollout")
    parameters = tuple(sorted(cleanup_identifiers))
    scope_clause = " WHERE thread_id IN (" + ",".join("?" for _ in parameters) + ")"
    statistics = image_statistics()
    updates = 0
    with destination.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        for table, keys in ITEM_TABLE_KEYS.items():
            count = connection.execute(f"SELECT count(*) FROM {table}" + scope_clause, parameters).fetchone()[0]
            cursor = connection.execute(
                f"SELECT {','.join(keys)},item_json FROM {table}" + scope_clause + f" ORDER BY {','.join(keys)}", parameters,
            )
            for row in tqdm(cursor, total=count, desc="Plan indexed images " + table, unit="item", mininterval=1):
                original = json.loads(row[-1])
                cleaned = remove_structured_images(original, statistics)
                if cleaned is REMOVED_IMAGE:
                    raise ValueError("Cannot remove an indexed item itself")
                if cleaned != original:
                    if table == "thread_realtime_items":
                        raise ValueError("Unfinished realtime image items found; complete the turn before cleanup")
                    update = {"table": table, "key": dict(zip(keys, row[:-1], strict=True)),
                              "old_json": row[-1], "new_json": json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))}
                    output.write(encode_record(update))
                    updates += 1
        output.flush()
        os.fsync(output.fileno())
    return updates, statistics

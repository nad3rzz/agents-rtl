"""Offline repair of projection offsets and lineage across live and archived files."""

import json
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from tqdm import tqdm

from codex_session_lineage import history_links, locate_ordinals, read_header
from codex_session_projection import (
    HISTORY_DATABASE_NAME, apply_projection_plan, backup_history_database, connect_history,
    projection_boundary_ordinals, projection_plan_changed, projection_plan_from_positions,
    projection_rows, rollout_identifier, validate_projection_schema,
)
from codex_session_repair_lineage import find_backup_evidence, fixed_length_header, stage_header_repair
from codex_session_storage import (
    file_signature, offline_session_lock, replace_verified, require_closed,
    require_codex_stopped, require_unchanged,
)

ROLLOUT_DIRECTORIES = ("sessions", "archived_sessions")


def home_rollout_paths(home):
    if not (home / "sessions").is_dir():
        raise ValueError(f"Missing sessions directory: {home}")
    paths = []
    for name in ROLLOUT_DIRECTORIES:
        directory = home / name
        if directory.is_symlink():
            raise ValueError(f"Symlink rollout directory is unsupported: {directory}")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"Expected rollout directory: {directory}")
        paths.extend(directory.rglob("*.jsonl"))
    return sorted(paths)


def read_home_inventory(home):
    inventory = {}
    paths = home_rollout_paths(home)
    if not paths:
        raise ValueError(f"No rollouts found: {home}")
    for path in tqdm(paths, total=len(paths), desc="Reading all history headers", unit="file", mininterval=1):
        if not path.resolve(strict=True).is_relative_to(home):
            raise ValueError(f"Rollout escapes selected home: {path}")
        identifier = rollout_identifier(path)
        if identifier in inventory:
            raise ValueError(f"Duplicate rollout identifier: {identifier}")
        inventory[identifier] = {"path": path, **read_header(path)}
    return inventory


def require_home_plan_unchanged(home, plan):
    if set(home_rollout_paths(home)) != {entry["path"] for entry in plan["inventory"].values()}:
        raise RuntimeError("Rollout inventory changed during maintenance")
    require_unchanged(plan["signatures"])


def plan_header_repair(link, position, signatures):
    source = link["source"]["path"]
    base = link["base"]
    evidence = find_backup_evidence(source, base["end_byte_offset"], base["end_ordinal_exclusive"], position["record"])
    for item in evidence:
        signatures[item["path"]] = item["signature"]
    child = link["child"]
    return {"path": child["path"], "old_header": child["raw"],
            "new_header": fixed_length_header(child, position["offset"]),
            "source": source, "old_offset": base["end_byte_offset"],
            "new_offset": position["offset"], "ordinal": base["end_ordinal_exclusive"]}


def prepare_home_repair(home, connection):
    if sorted(path.name for path in home.glob("thread_history*.sqlite")) != [HISTORY_DATABASE_NAME]:
        raise ValueError("Unknown history database version; refusing partial repair")
    validate_projection_schema(connection)
    inventory = read_home_inventory(home)
    signatures = {entry["path"]: entry["signature"] for entry in inventory.values()}
    links = history_links(inventory)
    incoming_links = defaultdict(list)
    for link in links:
        incoming_links[link["base"]["thread_id"]].append(link)
    indexed = {row[0] for row in connection.execute("SELECT thread_id FROM thread_history_projection_state")}
    with_turns = {row[0] for row in connection.execute("SELECT DISTINCT thread_id FROM thread_turns")}
    if with_turns - indexed:
        raise ValueError(f"Turn rows without checkpoints: {sorted(with_turns - indexed)}")
    if indexed - inventory.keys():
        raise ValueError(f"Indexed rollouts missing on disk: {sorted(indexed - inventory.keys())}")
    projection_plans = []
    header_repairs = []
    for identifier, entry in tqdm(inventory.items(), total=len(inventory), desc="Planning all history repairs", unit="file", mininterval=1):
        wanted = {link["base"]["end_ordinal_exclusive"] for link in incoming_links[identifier]}
        if identifier in indexed:
            turns, checkpoint = projection_rows(connection, identifier)
            wanted.update(projection_boundary_ordinals(turns, checkpoint))
        if not wanted:
            continue  # Explicitly unindexed files without dependent lineage need no offset repair.
        positions = locate_ordinals(entry["path"], wanted)
        if identifier in indexed:
            projection_plans.append(projection_plan_from_positions(entry["path"], turns, checkpoint, positions))
        for link in incoming_links[identifier]:
            position = positions[link["base"]["end_ordinal_exclusive"]]
            if position["offset"] != link["base"]["end_byte_offset"]:
                header_repairs.append(plan_header_repair(link, position, signatures))
    plan = {"inventory": inventory, "signatures": signatures, "projections": projection_plans,
            "headers": header_repairs, "lineage_links": len(links),
            "unindexed_rollouts": len(inventory) - len(indexed)}
    require_home_plan_unchanged(home, plan)
    return plan


def home_repair_summary(plan):
    return {"rollout_files": len(plan["inventory"]), "indexed_rollouts": len(plan["projections"]),
            "unindexed_rollouts": plan["unindexed_rollouts"], "lineage_links": plan["lineage_links"],
            "projection_repairs": sum(map(projection_plan_changed, plan["projections"])),
            "turn_offset_repairs": sum(sum(before != after for before, after in zip(item["old_turns"], item["new_turns"])) for item in plan["projections"]),
            "lineage_header_repairs": len(plan["headers"])}


def apply_header_repairs(home, plan):
    for repair in tqdm(plan["headers"], total=len(plan["headers"]), desc="Repairing lineage headers", unit="file"):
        require_home_plan_unchanged(home, plan)
        temporary = stage_header_repair(repair)
        try:
            backup = replace_verified(repair["path"], temporary, plan["signatures"], "lineage-repair")
            plan["signatures"][repair["path"]] = file_signature(repair["path"])
            if read_header(repair["path"])["raw"] != repair["new_header"]:
                raise RuntimeError(f"Repaired header read-back failed: {repair['path']}")
            tqdm.write(f"header_backup: {backup}")
        finally:
            if temporary.exists():
                temporary.unlink()


def verify_home_repair(connection, plan):
    for projection in plan["projections"]:
        if projection_rows(connection, projection["id"]) != (projection["new_turns"], projection["new_checkpoint"]):
            raise RuntimeError(f"Projection verification failed: {projection['path']}")
    for repair in plan["headers"]:
        if read_header(repair["path"])["raw"] != repair["new_header"]:
            raise RuntimeError(f"Header verification failed: {repair['path']}")


def repair_history_home(home, apply_changes=False):
    home = Path(home).resolve(strict=True)
    database = home / HISTORY_DATABASE_NAME
    if not apply_changes:
        with closing(connect_history(database)) as reader:
            reader.execute("BEGIN")
            plan = prepare_home_repair(home, reader)
            print("HISTORY_REPAIR_PLAN", json.dumps(home_repair_summary(plan)), flush=True)
            return plan
    roots = [home, *(home / name for name in ROLLOUT_DIRECTORIES if (home / name).exists())]
    with offline_session_lock(roots):
        require_closed(database)
        with closing(connect_history(database, writable=True)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            try:
                plan = prepare_home_repair(home, writer)
                summary = home_repair_summary(plan)
                print("HISTORY_REPAIR_PLAN", json.dumps(summary), flush=True)
                if not summary["projection_repairs"] and not plan["headers"]:
                    writer.rollback()
                    print("already_correct: true", flush=True)
                    return plan
                backup_history_database(database, plan["projections"])
                require_codex_stopped()
                require_home_plan_unchanged(home, plan)
                # Fixed-length, individually atomic headers remain valid if the DB transaction fails.
                # Retry recomputes the plan; it never reapplies successful headers or deletes messages.
                apply_header_repairs(home, plan)
                apply_projection_plan(writer, plan["projections"])
                require_codex_stopped()
                require_home_plan_unchanged(home, plan)
                verify_home_repair(writer, plan)
                writer.commit()
            except BaseException:
                writer.rollback()
                raise
        with closing(connect_history(database)) as reader:
            reader.execute("BEGIN")
            verify_home_repair(reader, plan)
        require_home_plan_unchanged(home, plan)
        print("history_offsets_repaired: true\nmessages_deleted: 0\nmessage_bodies_rewritten: 0", flush=True)
        return plan

"""Clean a small independent indexed test conversation in an isolated copy ONLY.

No --apply option exists. Does not authorize cleaning the real Codex home.
"""

import argparse
import json
import os
import shutil
from contextlib import closing
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from codex_session_doctor import process_clean_records
from codex_session_history_repair import read_home_inventory
from codex_session_image_projection import (
    apply_projected_images,
    inline_images,
    plan_projected_images,
    verify_projected_images,
)
from codex_session_lineage import history_links, read_header, session_root
from codex_session_projection import (
    BACKUP_PAGE_BATCH,
    HISTORY_DATABASE_NAME,
    apply_projection_plan,
    connect_history,
    projection_plan_changed,
    projection_plan_from_positions,
    projection_rows,
    rollout_identifier,
    update_backup_progress,
    validate_projection_schema,
)
from codex_session_storage import file_signature, require_unchanged, sha256_file
from tqdm import tqdm

MAX_PROBE_ROLLOUT_BYTES = 16 * 1024 * 1024
SPACE_RESERVE_BYTES = 64 * 1024 * 1024
PROBE_PARENT = Path(__file__).resolve().parent.parent / "nosync"


def inspect_positions(path):
    signature = file_signature(path)
    if signature[2] > MAX_PROBE_ROLLOUT_BYTES:
        raise ValueError("Probe accepts small test rollouts only (16 MiB maximum)")
    positions = {}
    offset = 0
    previous = -1
    with path.open("rb") as stream, tqdm(total=signature[2], desc="Checking probe records", unit="B", unit_scale=True) as progress:
        for raw in stream:
            if not raw.endswith(b"\n"):
                raise ValueError("Incomplete JSONL record")
            record = json.loads(raw)
            ordinal = record.get("ordinal")
            if type(ordinal) is not int or ordinal != previous + 1:
                raise ValueError("Probe requires an independent rollout with contiguous ordinals from zero")
            positions[ordinal] = {"offset": offset, "record": record}
            previous = ordinal
            offset += len(raw)
            progress.update(len(raw))
    positions[previous + 1] = {"offset": offset, "record": None}
    require_unchanged({path: signature})
    return positions


def textual_messages(positions):
    messages = []
    for position in positions.values():
        record = position["record"]
        if record is not None and record.get("type") == "response_item":
            payload = record["payload"]
            if payload.get("type") == "message":
                messages.append((record["ordinal"], payload.get("role"), payload.get("id"), payload.get("phase"),
                                 [part for part in payload["content"] if part.get("type") != "input_image"]))
    return messages


def copy_history_database(reader, destination):
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with closing(connect_history(destination, writable=True)) as writer:
        pages = reader.execute("PRAGMA page_count").fetchone()[0]
        with tqdm(total=pages, desc="Copying isolated history DB", unit="page") as progress:
            reader.backup(writer, pages=BACKUP_PAGE_BATCH, progress=partial(update_backup_progress, progress))
        if writer.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("Isolated database copy failed verification")


def run_probe(session):
    source = Path(session).absolute()
    original_signature = file_signature(source)
    original_hash = sha256_file(source)
    home = session_root(source).parent
    identifier = rollout_identifier(source)
    header = read_header(source)
    if header["record"]["payload"].get("history_mode") != "paginated":
        raise ValueError("Probe requires an indexed paginated conversation")
    inventory = read_home_inventory(home)
    for link in history_links(inventory):
        if source in (link["source"]["path"], link["child"]["path"]):
            raise ValueError("This first probe requires an independent, unlinked conversation")
    if sorted(path.name for path in home.glob("thread_history*.sqlite")) != [HISTORY_DATABASE_NAME]:
        raise ValueError("Unsupported history database version")
    original_positions = inspect_positions(source)
    database = home / HISTORY_DATABASE_NAME
    with closing(connect_history(database)) as reader:
        reader.execute("BEGIN")
        validate_projection_schema(reader)
        turns, checkpoint = projection_rows(reader, identifier)
        original_plan = projection_plan_from_positions(source, turns, checkpoint, original_positions)
        if projection_plan_changed(original_plan):
            raise ValueError("Source projection already has incorrect offsets; probe refused")
        snapshots, item_updates = plan_projected_images(reader, identifier, original_positions)
        if not item_updates:
            raise ValueError("No proved indexed images to test")
        needed = reader.execute("PRAGMA page_count").fetchone()[0] * reader.execute("PRAGMA page_size").fetchone()[0]
        if not PROBE_PARENT.is_dir() or PROBE_PARENT.is_symlink():
            raise ValueError("Expected an existing non-symlink project nosync directory")
        if shutil.disk_usage(PROBE_PARENT).free < needed + original_signature[2] * 2 + SPACE_RESERVE_BYTES:
            raise RuntimeError("Insufficient space for isolated probe")
        output = PROBE_PARENT / ("image-clean-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        output.mkdir(mode=0o700)
        (output / "sessions").mkdir(mode=0o700)
        copied_session = output / "sessions" / source.name
        with copied_session.open("xb") as destination:
            os.fchmod(destination.fileno(), 0o600)
            stats, original_size, clean_size = process_clean_records(source, len(header["raw"]), destination)
            destination.flush()
            os.fsync(destination.fileno())
        copied_database = output / HISTORY_DATABASE_NAME
        copy_history_database(reader, copied_database)
    require_unchanged({source: original_signature})
    cleaned_positions = inspect_positions(copied_session)
    if set(cleaned_positions) != set(original_positions):
        raise RuntimeError("Cleanup changed record ordinals")
    if textual_messages(original_positions) != textual_messages(cleaned_positions):
        raise RuntimeError("Cleanup changed message text/order/identity")
    if any(inline_images(position["record"]) for position in cleaned_positions.values()):
        raise RuntimeError("Images remain in isolated rollout")
    cleaned_plan = projection_plan_from_positions(copied_session, turns, checkpoint, cleaned_positions)
    with closing(connect_history(copied_database, writable=True)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        try:
            validate_projection_schema(writer)
            for table in ("thread_items", "thread_realtime_items"):
                if writer.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchone():
                    raise ValueError(f"Unsupported trigger on {table}")
            apply_projection_plan(writer, [cleaned_plan])
            apply_projected_images(writer, item_updates)
            verify_projected_images(writer, identifier, snapshots, item_updates)
            writer.commit()
        except BaseException:
            writer.rollback()
            raise
    with closing(connect_history(copied_database)) as reader:
        repaired_turns, repaired_checkpoint = projection_rows(reader, identifier)
        if projection_plan_changed(projection_plan_from_positions(copied_session, repaired_turns, repaired_checkpoint, cleaned_positions)):
            raise RuntimeError("Copied projection remains inconsistent")
        verify_projected_images(reader, identifier, snapshots, item_updates)
    require_unchanged({source: original_signature})
    if sha256_file(source) != original_hash:
        raise RuntimeError("Source changed during isolated probe")
    proof = {"isolated_only": True, "source_unchanged": True, "source_sha256": original_hash,
             "output_home": str(output), "original_bytes": original_size, "clean_bytes": clean_size,
             "saved_bytes": original_size - clean_size, "cleanup_stats": stats,
             "indexed_images_updated": len(item_updates), "turns": len(turns),
             "turn_offsets_updated": sum(old != new for old, new in zip(turns, cleaned_plan["new_turns"], strict=True)),
             "message_text_order_identity_preserved": True, "native_ui_verified": False}
    (output / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print("ISOLATED_CLEAN_PROOF", json.dumps(proof), flush=True)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    arguments = parser.parse_args()
    run_probe(arguments.session)


if __name__ == "__main__":
    main()

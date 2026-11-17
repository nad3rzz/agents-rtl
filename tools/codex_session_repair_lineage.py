#!/usr/bin/env python3
"""Repair proven history offsets only; retain every body byte and new message."""

import argparse
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

from tqdm import tqdm

from codex_session_lineage import (
    history_links, locate_ordinals, read_inventory,
    protected_prefixes, require_inventory_unchanged, verify_boundary,
)
from codex_session_storage import (
    COPY_CHUNK_BYTES, create_staged_file, file_signature, offline_session_lock,
    replace_verified, require_unchanged,
)


def find_backup_evidence(source, old_offset, expected_ordinal, current_record):
    backups = sorted(source.parent.glob(source.name + ".*bak-*"))
    evidence = []
    for backup in backups:
        signature = file_signature(backup)
        if old_offset >= signature[2]:
            # EOF cannot prove the identity of the following record.
            continue
        with backup.open("rb") as stream:
            if old_offset:
                stream.seek(old_offset - 1)
                if stream.read(1) != b"\n":
                    continue
            raw = stream.readline()
        if not raw.endswith(b"\n"):
            raise ValueError(f"Incomplete backup boundary record: {backup}")
        record = json.loads(raw)
        if record.get("ordinal") != expected_ordinal:
            continue
        if record != current_record:
            raise ValueError(f"Cutoff event differs from backup; manual review required: {backup}")
        require_unchanged({backup: signature})
        evidence.append({"path": backup, "signature": signature})
    if not evidence:
        raise ValueError(f"No backup proves cutoff ordinal {expected_ordinal} at byte {old_offset}: {source}")
    return evidence


def fixed_length_header(entry, new_offset):
    record = deepcopy(entry["record"])
    record["payload"]["history_base"]["end_byte_offset"] = new_offset
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padding = len(entry["raw"]) - len(encoded) - 1
    if padding < 0:
        raise ValueError(f"Repaired metadata cannot fit existing header: {entry['path']}")
    return encoded + b" " * padding + b"\n"


def prepare_repairs(root, show_progress=True):
    inventory = read_inventory(root)
    links = history_links(inventory)
    wanted_by_source = {}
    for link in links:
        wanted_by_source.setdefault(link["source"]["path"], set()).add(link["base"]["end_ordinal_exclusive"])
    positions = {}
    signatures = {}
    for source, wanted in tqdm(wanted_by_source.items(), total=len(wanted_by_source), desc="Indexing sources", unit="file", disable=not show_progress):
        signatures[source] = file_signature(source)
        positions[source] = locate_ordinals(source, wanted, show_progress)
    repairs = []
    for link in links:
        child, source, base = link["child"], link["source"]["path"], link["base"]
        signatures[child["path"]] = child["signature"]
        position = positions[source][base["end_ordinal_exclusive"]]
        if position["offset"] == base["end_byte_offset"]:
            verify_boundary(source, position["offset"], base["end_ordinal_exclusive"])
            continue
        evidence = find_backup_evidence(source, base["end_byte_offset"], base["end_ordinal_exclusive"], position["record"])
        for item in evidence:
            signatures[item["path"]] = item["signature"]
        repairs.append({
            "path": child["path"], "source": source, "old_offset": base["end_byte_offset"],
            "new_offset": position["offset"], "ordinal": base["end_ordinal_exclusive"],
            "old_header": child["raw"], "new_header": fixed_length_header(child, position["offset"]),
            "evidence": [item["path"] for item in evidence],
        })
    require_inventory_unchanged(root, inventory, signatures)
    return inventory, signatures, repairs


def stage_header_repair(repair):
    temporary = None
    try:
        with create_staged_file(repair["path"]) as output, repair["path"].open("rb") as source:
            temporary = Path(output.name)
            if source.readline() != repair["old_header"]:
                raise RuntimeError(f"Header changed since planning: {repair['path']}")
            output.write(repair["new_header"])
            shutil.copyfileobj(source, output, COPY_CHUNK_BYTES)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size != repair["path"].stat().st_size:
            raise RuntimeError("Header repair changed file length")
        return temporary
    except BaseException:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        raise


def run_repair(root, apply_changes=False, show_progress=True):
    if not apply_changes:
        inventory, signatures, repairs = prepare_repairs(root, show_progress)
        print_repair_plan(inventory, repairs)
        return repairs
    # Each replacement preserves byte length, so interrupted batches are safely retryable.
    with offline_session_lock([root]):
        inventory, signatures, repairs = prepare_repairs(root, show_progress)
        print_repair_plan(inventory, repairs)
        for repair in tqdm(repairs, total=len(repairs), desc="Repairing headers", unit="file", disable=not show_progress):
            require_inventory_unchanged(root, inventory, signatures)
            temporary = stage_header_repair(repair)
            try:
                backup = replace_verified(repair["path"], temporary, signatures, "lineage-repair")
                signatures[repair["path"]] = file_signature(repair["path"])
                tqdm.write(f"repaired: {repair['path']}\nbackup: {backup}")
            finally:
                if temporary.exists():
                    temporary.unlink()
        require_inventory_unchanged(root, inventory, signatures)
        verified_inventory = read_inventory(root)
        protected_prefixes(verified_inventory)
        print(f"verified_lineage_links: {len(history_links(verified_inventory))}")
    return repairs


def print_repair_plan(inventory, repairs):
    print(f"sessions: {len(inventory)}; lineage_links: {len(history_links(inventory))}; repairs: {len(repairs)}")
    for repair in repairs:
        print(json.dumps({key: str(repair[key]) if isinstance(repair[key], Path) else repair[key] for key in (
            "path", "source", "ordinal", "old_offset", "new_offset",
        )}))
    print("Only metadata offsets change; header length and every body byte are preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    run_repair(arguments.sessions_root.absolute(), arguments.apply)


if __name__ == "__main__":
    main()

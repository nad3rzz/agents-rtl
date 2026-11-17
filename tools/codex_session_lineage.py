"""Read paginated history contracts and protect source prefixes from rewriting."""

import json
import re
from pathlib import Path

from codex_session_storage import file_signature, require_unchanged

ROLLOUT_ID_PATTERN = re.compile(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$")


def session_root(path):
    path = Path(path).absolute()
    for parent in path.parents:
        if parent.name == "sessions":
            return parent
    raise ValueError(f"Session must be inside an explicit sessions directory: {path}")


def read_header(path):
    signature = file_signature(path)
    with Path(path).open("rb") as stream:
        raw = stream.readline()
    if not raw.endswith(b"\n"):
        raise ValueError(f"Incomplete session header: {path}")
    record = json.loads(raw)
    if record.get("type") != "session_meta" or not isinstance(record.get("payload"), dict):
        raise ValueError(f"Missing session_meta header: {path}")
    require_unchanged({Path(path): signature})
    return {"record": record, "raw": raw, "signature": signature}


def read_inventory(root):
    root = Path(root).absolute()
    if not root.is_dir():
        raise ValueError(f"Missing sessions directory: {root}")
    paths = sorted(root.rglob("*.jsonl"))
    if not paths:
        raise ValueError(f"No sessions in {root}")
    inventory = {}
    for path in paths:
        match = ROLLOUT_ID_PATTERN.search(path.name)
        if not match or not path.name.startswith("rollout-"):
            raise ValueError(f"Unrecognized rollout filename: {path}")
        identifier = match.group(1)
        if identifier in inventory:
            raise ValueError(f"Ambiguous rollout ID {identifier}")
        inventory[identifier] = {"path": path, **read_header(path)}
    return inventory


def history_links(inventory):
    links = []
    parents = {}
    for identifier, entry in inventory.items():
        payload = entry["record"]["payload"]
        base = payload.get("history_base")
        if base is None:
            continue
        if payload.get("history_mode") != "paginated" or not isinstance(base, dict):
            raise ValueError(f"Unsupported history contract: {entry['path']}")
        for key in ("end_byte_offset", "end_ordinal_exclusive"):
            if type(base.get(key)) is not int or base[key] < 0:
                raise ValueError(f"Invalid {key}: {entry['path']}")
        source_id = base.get("thread_id")
        if source_id not in inventory:
            raise ValueError(f"Missing source rollout {source_id}: {entry['path']}")
        parents[identifier] = source_id
        links.append({"child": entry, "source": inventory[source_id], "base": base})
    for identifier in parents:
        seen = set()
        current = identifier
        while current in parents:
            if current in seen:
                raise ValueError(f"History lineage cycle: {identifier}")
            seen.add(current)
            current = parents[current]
    return links


def boundary_record(path, offset):
    size = Path(path).stat().st_size
    if offset > size:
        raise ValueError(f"Cutoff {offset} is past source size {size}: {path}")
    with Path(path).open("rb") as stream:
        if offset:
            stream.seek(offset - 1)
            if stream.read(1) != b"\n":
                raise ValueError(f"Cutoff {offset} is not a JSONL boundary: {path}")
        stream.seek(offset)
        raw = stream.readline()
    if not raw:
        return None  # EOF is a valid cutoff; its preceding ordinal must be checked separately.
    if not raw.endswith(b"\n"):
        raise ValueError(f"Incomplete record at cutoff: {path}")
    return json.loads(raw)


def verify_boundary(path, offset, expected_ordinal):
    record = boundary_record(path, offset)
    if record is None:
        # EOF requires a full ordered scan, not an invented ordinal.
        positions = locate_ordinals(path, {expected_ordinal}, show_progress=False)
        if positions[expected_ordinal]["offset"] != offset:
            raise ValueError(f"Incorrect EOF cutoff: {path}")
    elif record.get("ordinal") != expected_ordinal:
        raise ValueError(f"Cutoff ordinal mismatch in {path}: expected {expected_ordinal}, got {record.get('ordinal')}")


def locate_ordinals(path, wanted_ordinals, show_progress=True):
    from tqdm import tqdm

    signature = file_signature(path)
    positions = {}
    previous_ordinal = None
    offset = 0
    with Path(path).open("rb") as stream, tqdm(
        total=signature[2], desc=f"Index {Path(path).name[:27]}", unit="B", unit_scale=True, mininterval=1, disable=not show_progress,
    ) as progress:
        for line_number, raw in enumerate(stream, 1):
            if not raw.endswith(b"\n"):
                raise ValueError(f"Incomplete record: {path}:{line_number}")
            record = json.loads(raw)
            ordinal = record.get("ordinal")
            if type(ordinal) is not int or (previous_ordinal is not None and ordinal != previous_ordinal + 1):
                raise ValueError(f"Non-contiguous ordinal: {path}:{line_number}: {ordinal}, previous {previous_ordinal}")
            if ordinal in wanted_ordinals:
                positions[ordinal] = {"offset": offset, "record": record}
            previous_ordinal = ordinal
            offset += len(raw)
            progress.update(len(raw))
    if previous_ordinal is not None and previous_ordinal + 1 in wanted_ordinals:
        positions[previous_ordinal + 1] = {"offset": offset, "record": None}
    if set(positions) != set(wanted_ordinals):
        raise ValueError(f"Missing cutoff ordinals {set(wanted_ordinals) - set(positions)} in {path}")
    require_unchanged({Path(path): signature})
    return positions


def inventory_signatures(inventory):
    return {entry["path"]: entry["signature"] for entry in inventory.values()}


def require_inventory_unchanged(root, inventory, signatures):
    if set(Path(root).rglob("*.jsonl")) != set(inventory_signatures(inventory)):
        raise RuntimeError(f"Session inventory changed: {root}")
    require_unchanged(signatures)


def protected_prefixes(inventory):
    prefixes = {entry["path"]: len(entry["raw"]) for entry in inventory.values()}
    for link in history_links(inventory):
        base, source = link["base"], link["source"]["path"]
        verify_boundary(source, base["end_byte_offset"], base["end_ordinal_exclusive"])
        prefixes[source] = max(prefixes[source], base["end_byte_offset"])
    return prefixes


def require_unlinked_session(path):
    path = Path(path).absolute()
    inventory = read_inventory(session_root(path))
    for entry in inventory.values():
        if entry["path"] == path and entry["record"]["payload"].get("history_mode") == "paginated":
            raise ValueError(f"This operation cannot rewrite paginated history: {path}")
    for link in history_links(inventory):
        if path in (link["source"]["path"], link["child"]["path"]):
            raise ValueError(f"This operation cannot rewrite a linked rollout: {path}")

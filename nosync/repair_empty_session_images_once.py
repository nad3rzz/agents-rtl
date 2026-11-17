#!/usr/bin/env python3
"""One-time repair of empty legacy image entries; default is a read-only scan."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from tqdm import tqdm


SESSION_ROOT_NAMES = (".codex", ".codex-vscode", ".codex-antigravity")
UNRELATED_SPECIAL_FILESYSTEM_TYPES = {"overlay", "nsfs", "hugetlbfs", "mqueue"}


def session_paths():
    paths = sorted({path for name in SESSION_ROOT_NAMES for path in (Path.home() / name / "sessions").rglob("*.jsonl")})
    if not paths:
        raise RuntimeError("No session files found")
    return paths


def signature(path):
    metadata = path.stat()
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def require_clients_stopped():
    result = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "codex"], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        raise RuntimeError("Close Codex clients first. Running PIDs: " + result.stdout.strip())
    if result.returncode != 1 or result.stderr.strip():
        raise RuntimeError("Unable to check running clients: " + result.stderr.strip())


def build_file_check_command(path):
    target = path.resolve(strict=True)
    target_device = target.stat().st_dev
    target_device_id = f"{os.major(target_device)}:{os.minor(target_device)}"
    mounts = subprocess.run(
        ["findmnt", "--json", "--list", "--output", "TARGET,MAJ:MIN,FSTYPE"],
        capture_output=True, text=True, check=True,
    )
    if mounts.stderr.strip():
        raise RuntimeError("Cannot verify mounted filesystems: " + mounts.stderr.strip())
    filesystems = json.loads(mounts.stdout)["filesystems"]
    if not isinstance(filesystems, list) or not filesystems:
        raise ValueError("Invalid mount inventory")
    exempt_mounts = set()
    for filesystem in filesystems:
        mount = Path(filesystem["target"])
        if not mount.is_absolute():
            raise ValueError(f"Mount target is not absolute: {mount}")
        if (
            filesystem["fstype"] in UNRELATED_SPECIAL_FILESYSTEM_TYPES
            and filesystem["maj:min"] != target_device_id
            and not target.is_relative_to(mount)
        ):
            exempt_mounts.add(str(mount))
    command = ["lsof"]
    for mount in sorted(exempt_mounts):
        command.extend(["-e", mount])
    return [*command, "--", str(target)]


def require_file_closed(path):
    result = subprocess.run(build_file_check_command(path), capture_output=True, text=True, check=False)
    if result.returncode != 1 or result.stdout.strip() or result.stderr.strip():
        raise RuntimeError(f"File is open or its open-file check failed: {path}\n{result.stdout}{result.stderr}")


def repair_record(record):
    if not isinstance(record, dict) or "type" not in record or "payload" not in record:
        raise ValueError("Invalid session record")
    removed_count = 0
    payload = record["payload"]
    if record["type"] == "event_msg" and payload.get("type") == "item_completed":
        item = payload.get("item")
        if not isinstance(item, dict):
            raise ValueError("item_completed is missing its item")
        if item.get("type") in ("UserMessage", "userMessage"):
            content = item.get("content")
            if not isinstance(content, list):
                raise ValueError("User message content is not a list")
            retained_content = [entry for entry in content if entry != {"type": "image"}]
            removed_count = len(content) - len(retained_content)
            if removed_count:
                # Preserve the event and message ID, as normal image cleanup does.
                record = {**record, "payload": {**payload, "item": {**item, "content": retained_content}}}

    stack = [("$", record)]
    while stack:
        position, value = stack.pop()
        if isinstance(value, dict):
            if value.get("type") == "image" and "image_url" not in value:
                valid_mcp_image = (
                    isinstance(value.get("data"), str) and bool(value["data"])
                    and isinstance(value.get("mimeType"), str) and value["mimeType"].startswith("image/")
                )
                if not valid_mcp_image:
                    raise ValueError(f"Unrecognized incomplete image at {position}; refusing automatic repair")
            stack.extend((f"{position}.{key}", child) for key, child in value.items())
        elif isinstance(value, list):
            stack.extend((f"{position}[{index}]", child) for index, child in enumerate(value))
    return record, removed_count


def inspect_session(path, destination=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Not a regular non-symlink session: {path}")
    original_signature = signature(path)
    source_hash = hashlib.sha256()
    output_hash = hashlib.sha256()
    removed_count = 0
    changed_lines = []
    with path.open("rb") as source:
        for line_number, raw in enumerate(source, 1):
            if not raw.endswith(b"\n"):
                raise ValueError(f"Incomplete JSONL record: {path}:{line_number}")
            try:
                record = json.loads(raw)
                repaired, removed = repair_record(record)
            except (ValueError, TypeError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            output = raw
            if removed:
                removed_count += removed
                changed_lines.append(line_number)
                output = (json.dumps(repaired, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            source_hash.update(raw)
            output_hash.update(output)
            if destination is not None:
                destination.write(output)
    if signature(path) != original_signature:
        raise RuntimeError(f"Session changed during inspection: {path}")
    return {
        "path": str(path), "signature": original_signature,
        "source_sha256": source_hash.hexdigest(), "output_sha256": output_hash.hexdigest(),
        "removed_empty_images": removed_count, "changed_lines": changed_lines,
    }


def apply_repair(plan):
    path = Path(plan["path"])
    require_clients_stopped()
    require_file_closed(path)
    directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary_path = None
    try:
        fcntl.flock(directory_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if signature(path) != plan["signature"]:
            raise RuntimeError(f"Session changed since planning: {path}")
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".empty-image-repair-", delete=False) as destination:
            temporary_path = Path(destination.name)
            verified_plan = inspect_session(path, destination)
            if verified_plan != plan:
                raise RuntimeError(f"Repair differs from the verified plan: {path}")
            destination.flush()
            os.fsync(destination.fileno())
        with temporary_path.open("rb") as candidate:
            if hashlib.file_digest(candidate, "sha256").hexdigest() != plan["output_sha256"]:
                raise RuntimeError("Staged repair checksum mismatch")
        require_clients_stopped()
        require_file_closed(path)
        if signature(path) != plan["signature"]:
            raise RuntimeError(f"Session changed before backup: {path}")
        backup = path.with_name(path.name + ".empty-image-repair-bak-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        with path.open("rb") as source, backup.open("xb") as destination:
            os.fchmod(destination.fileno(), 0o600)
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        with backup.open("rb") as saved:
            if hashlib.file_digest(saved, "sha256").hexdigest() != plan["source_sha256"]:
                raise RuntimeError("Backup checksum mismatch")
        require_clients_stopped()
        require_file_closed(path)
        if signature(path) != plan["signature"]:
            raise RuntimeError(f"Session changed before replacement: {path}")
        os.replace(temporary_path, path)
        temporary_path = None
        os.fsync(directory_descriptor)
        with path.open("rb") as repaired:
            if hashlib.file_digest(repaired, "sha256").hexdigest() != plan["output_sha256"]:
                raise RuntimeError("Read-back checksum mismatch; retain the backup")
        print(f"repaired: {path}\nremoved_empty_images: {plan['removed_empty_images']}\nbackup: {backup}")
    finally:
        if temporary_path is not None:
            temporary_path.unlink()
        os.close(directory_descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if arguments.apply:
        raise RuntimeError("This one-time writer is retired: it changes paginated history offsets. Use the maintained session tools instead.")
    paths = session_paths()
    affected = []
    for path in tqdm(paths, total=len(paths), desc="Checking sessions", unit="session"):
        plan = inspect_session(path)
        if plan["removed_empty_images"]:
            affected.append(plan)
            tqdm.write(json.dumps({key: plan[key] for key in ("path", "removed_empty_images", "changed_lines")}))
    print(f"sessions: {len(paths)}; affected: {len(affected)}; empty_images: {sum(plan['removed_empty_images'] for plan in affected)}")
    if arguments.apply:
        for plan in tqdm(affected, total=len(affected), desc="Repairing sessions", unit="session"):
            apply_repair(plan)
    else:
        print("Dry run only; no files changed. Use --apply with Codex clients closed.")


if __name__ == "__main__":
    main()

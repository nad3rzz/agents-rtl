#!/usr/bin/env python3
"""Recover legacy doctor changes from explicit backups, retaining later events."""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

from tqdm import tqdm

from codex_session_doctor import DATA_IMAGE_RX, require_session_files_closed_for_write


def reproduce_legacy_cleaning(value):
    # Only used to prove that a difference was produced by the faulty doctor.
    if isinstance(value, list):
        cleaned = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "input_image":
                continue
            if isinstance(item, dict) and item.get("type") == "input_text" and item.get("text") in ("<image>", "</image>"):
                continue
            if isinstance(item, str) and DATA_IMAGE_RX.search(item):
                continue
            cleaned_item = reproduce_legacy_cleaning(item)
            if cleaned_item is not None:
                cleaned.append(cleaned_item)
        return cleaned
    if isinstance(value, dict):
        if value.get("type") == "input_image":
            return None
        cleaned = {}
        for key, child in value.items():
            if key in ("images", "local_images"):
                cleaned[key] = []
            elif key != "image_url":
                cleaned_child = reproduce_legacy_cleaning(child)
                if cleaned_child is not None:
                    cleaned[key] = cleaned_child
        return cleaned
    if isinstance(value, str):
        return DATA_IMAGE_RX.sub("[DATA_IMAGE_REMOVED]", value)
    return value


def file_signature(path):
    metadata = path.stat()
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def validate_sources_unchanged(paths, signatures):
    for path, expected_signature in zip(paths, signatures):
        if file_signature(path) != expected_signature:
            raise RuntimeError(f"File changed during recovery; nothing will be replaced: {path}")


def require_codex_stopped(session):
    result = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-x", "codex"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        raise RuntimeError(f"Close Codex clients before recovery. Running Codex PIDs: {result.stdout.strip()}")
    if result.returncode != 1 or result.stderr.strip():
        raise RuntimeError(f"Cannot verify Codex is stopped: {result.stderr.strip()}")
    require_session_files_closed_for_write([str(session)], "recover")


def reconstruct_records(paths, output=None, show_progress=True):
    signatures = [file_signature(path) for path in paths]
    source_counts = [0] * len(paths)
    changed_records = 0
    appended_records = 0
    with ExitStack() as stack:
        readers = [stack.enter_context(path.open("rb")) for path in paths]
        progress = stack.enter_context(tqdm(
            total=sum(signature[2] for signature in signatures),
            desc="Verifying recovery", unit="B", unit_scale=True, disable=not show_progress,
        ))
        for line_number, lines in enumerate(zip_longest(*readers), 1):
            if lines[-1] is None:
                raise ValueError(f"Current session is shorter than a backup at line {line_number}")
            available_lines = [line for line in lines if line is not None]
            canonical_line = available_lines[0]
            canonical_record = json.loads(canonical_line)
            if not isinstance(canonical_record, dict) or "type" not in canonical_record or "payload" not in canonical_record:
                raise ValueError(f"Invalid session record at line {line_number}")
            legacy_record = reproduce_legacy_cleaning(canonical_record)
            for index, line in enumerate(lines):
                if line is None:
                    continue
                if not line.endswith(b"\n"):
                    raise ValueError(f"Incomplete record in {paths[index]} at line {line_number}")
                source_counts[index] += 1
                record = json.loads(line)
                if record != canonical_record and record != legacy_record:
                    raise ValueError(f"Unexplained difference in {paths[index]} at line {line_number}; refusing recovery")
                if index == len(paths) - 1 and record != canonical_record:
                    changed_records += 1
                progress.update(len(line))
            if all(line is None for line in lines[:-1]):
                appended_records += 1
            if output is not None:
                output.write(canonical_line)
    if source_counts != sorted(source_counts):
        raise ValueError("Supply backups from oldest to newest; their event counts must not decrease")
    validate_sources_unchanged(paths, signatures)
    return {
        "source_events": source_counts,
        "recovered_events": changed_records,
        "preserved_new_events": appended_records,
    }


def recover_session(session, backups, apply_changes=False):
    paths = [*backups, session]
    if not backups or len(set(paths)) != len(paths):
        raise ValueError("Provide distinct backup files and a distinct target session")
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected a regular, non-symlink file: {path}")
    if not apply_changes:
        return reconstruct_records(paths)

    require_codex_stopped(session)
    directory_descriptor = os.open(session.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary_path = None
    try:
        fcntl.flock(directory_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        signatures = [file_signature(path) for path in paths]
        with tempfile.NamedTemporaryFile(mode="wb", dir=session.parent, prefix=".session-recovery-", delete=False) as output:
            temporary_path = Path(output.name)
            result = reconstruct_records(paths, output)
            output.flush()
            os.fsync(output.fileno())
        if result["recovered_events"] == 0:
            return {**result, "status": "already_recovered"}

        require_codex_stopped(session)
        validate_sources_unchanged(paths, signatures)
        snapshot = session.with_name(session.name + ".restore-bak-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        with session.open("rb") as source, snapshot.open("xb") as destination:
            os.fchmod(destination.fileno(), 0o600)
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        require_codex_stopped(session)
        validate_sources_unchanged(paths, signatures)
        os.replace(temporary_path, session)
        temporary_path = None
        os.fsync(directory_descriptor)
        return {**result, "status": "recovered", "backup": str(snapshot)}
    finally:
        if temporary_path is not None:
            temporary_path.unlink()
        os.close(directory_descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--backup", required=True, action="append", type=Path, help="Repeat in oldest-to-newest order")
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    result = recover_session(arguments.session, arguments.backup, arguments.apply)
    print(json.dumps({"mode": "apply" if arguments.apply else "dry-run", **result}, indent=2))


if __name__ == "__main__":
    main()

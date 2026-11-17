"""Regression tests for paginated history repair and prefix-safe image cleanup."""

import argparse
import hashlib
import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tqdm import tqdm

from codex_session_doctor import clean_sessions, process_clean_records, repair_tool_search_session
from codex_session_lineage import (
    history_links, locate_ordinals, protected_prefixes, read_inventory,
    require_unlinked_session,
)
from codex_session_repair_lineage import prepare_repairs, run_repair, stage_header_repair
from codex_session_storage import file_signature, offline_session_lock, require_closed, require_unchanged

SOURCE_ID = "00000000-0000-0000-0000-000000000001"
CHILD_ID = "00000000-0000-0000-0000-000000000002"
GRANDCHILD_ID = "00000000-0000-0000-0000-000000000003"


def record_bytes(record):
    return (json.dumps(record, ensure_ascii=False) + "\n").encode()


def metadata(identifier, ordinal, base=None):
    payload = {"id": identifier, "history_mode": "paginated"}
    if base is not None:
        payload["history_base"] = base
    return {"type": "session_meta", "ordinal": ordinal, "payload": payload}


def event(ordinal, text, image=False):
    content = [{"type": "text", "text": text}, None]
    if image:
        content.append({"type": "image", "image_url": "data:image/png;base64," + "A" * 500})
    return {"type": "event_msg", "ordinal": ordinal, "payload": {"type": "item_completed", "item": {"content": content}}}


def fixture(root, broken=True):
    root.mkdir()
    source = root / f"rollout-test-{SOURCE_ID}.jsonl"
    child = root / f"rollout-test-{CHILD_ID}.jsonl"
    grandchild = root / f"rollout-test-{GRANDCHILD_ID}.jsonl"
    source_records = [metadata(SOURCE_ID, 0), event(1, "shared", True), event(2, "boundary"), event(3, "unshared", True)]
    old_offset = len(record_bytes(source_records[0]) + record_bytes(source_records[1]))
    original = b"".join(map(record_bytes, source_records))
    source.with_name(source.name + ".doctor-bak-test").write_bytes(original)
    if broken:
        source_records[1]["payload"]["item"]["content"].pop()
    source.write_bytes(b"".join(map(record_bytes, source_records)))
    child_header = metadata(CHILD_ID, 2, {"thread_id": SOURCE_ID, "end_ordinal_exclusive": 2, "end_byte_offset": old_offset})
    child_records = [child_header, event(3, "child shared", True), event(4, "child boundary"), event(5, "newest reply", True)]
    child_original = b"".join(map(record_bytes, child_records))
    child_cutoff = len(record_bytes(child_header) + record_bytes(child_records[1]))
    child.with_name(child.name + ".doctor-bak-test").write_bytes(child_original)
    if broken:
        child_records[1]["payload"]["item"]["content"].pop()
    child.write_bytes(b"".join(map(record_bytes, child_records)))
    grandchild_header = metadata(GRANDCHILD_ID, 4, {"thread_id": CHILD_ID, "end_ordinal_exclusive": 4, "end_byte_offset": child_cutoff})
    grandchild.write_bytes(record_bytes(grandchild_header) + record_bytes(event(5, "latest", True)))
    return source, child, grandchild


def test_repair_preserves_all_body_bytes_and_repeated_apply_is_noop():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        paths = fixture(root)
        original = {path: path.read_bytes() for path in paths}
        with patch("codex_session_storage.require_codex_stopped"), patch("codex_session_storage.require_closed"):
            repairs = run_repair(root, True, False)
            assert len(repairs) == 2
            for path in paths:
                after = path.read_bytes()
                assert len(after) == len(original[path])
                assert after.split(b"\n", 1)[1] == original[path].split(b"\n", 1)[1]
            protected_prefixes(read_inventory(root))
            assert run_repair(root, True, False) == []
        assert len(list(root.glob("*.lineage-repair-bak-*"))) == 2
        for repair in repairs:
            backup = next(root.glob(repair["path"].name + ".lineage-repair-bak-*"))
            assert backup.read_bytes() == original[repair["path"]]


def test_cleanup_keeps_shared_prefix_and_preserves_null_and_unmodified_bytes():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        paths = fixture(root, False)
        prefixes = protected_prefixes(read_inventory(root))
        original = {path: path.read_bytes() for path in paths}
        with patch("codex_session_storage.require_codex_stopped"), patch("codex_session_storage.require_closed"):
            clean_sessions(paths, True)
            first_clean = {path: path.read_bytes() for path in paths}
            for path in paths:
                assert first_clean[path][:prefixes[path]] == original[path][:prefixes[path]]
                assert len(first_clean[path]) < len(original[path])
                records = list(map(json.loads, first_clean[path].splitlines()))
                assert records[-1]["payload"]["item"]["content"][-1] is None
            protected_prefixes(read_inventory(root))
            clean_sessions(paths, True)
            assert {path: path.read_bytes() for path in paths} == first_clean
        assert len(list(root.glob("*.doctor-bak-20*"))) == 3


def test_broken_graph_prevents_any_cleanup():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        paths = fixture(root)
        original = {path: path.read_bytes() for path in paths}
        with patch("codex_session_storage.require_codex_stopped"):
            try:
                clean_sessions(paths, True)
            except ValueError as error:
                assert "Cutoff" in str(error)
            else:
                raise AssertionError("Broken history was accepted")
        assert {path: path.read_bytes() for path in paths} == original
        assert not list(root.glob("*.doctor-bak-20*"))


def test_no_evidence_and_changed_boundary_are_rejected():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        source, child, grandchild = fixture(root)
        backup = source.with_name(source.name + ".doctor-bak-test")
        backup.unlink()
        try:
            prepare_repairs(root, False)
        except ValueError as error:
            assert "No backup proves" in str(error)
        else:
            raise AssertionError("Repair guessed without evidence")
        original_records = [metadata(SOURCE_ID, 0), event(1, "shared", True), event(2, "WRONG MESSAGE"), event(3, "unshared", True)]
        backup.write_bytes(b"".join(map(record_bytes, original_records)))
        try:
            prepare_repairs(root, False)
        except ValueError as error:
            assert "differs from backup" in str(error)
        else:
            raise AssertionError("Repair accepted a different boundary event")


def test_missing_sources_cycles_duplicates_and_ordinal_gaps_fail():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        source, child, grandchild = fixture(root, False)
        original = source.read_bytes()
        source.unlink()
        try:
            history_links(read_inventory(root))
        except ValueError as error:
            assert "Missing source" in str(error)
        else:
            raise AssertionError("Missing source accepted")
        source.write_bytes(original)
        records = list(map(json.loads, original.splitlines()))
        records[2]["ordinal"] = 99
        source.write_bytes(b"".join(map(record_bytes, records)))
        try:
            locate_ordinals(source, {2}, False)
        except ValueError as error:
            assert "Non-contiguous" in str(error)
        else:
            raise AssertionError("Ordinal gap accepted")
        records[0]["payload"]["history_base"] = {"thread_id": GRANDCHILD_ID, "end_byte_offset": 0, "end_ordinal_exclusive": 4}
        source.write_bytes(b"".join(map(record_bytes, records)))
        try:
            history_links(read_inventory(root))
        except ValueError as error:
            assert "cycle" in str(error)
        else:
            raise AssertionError("Cycle accepted")
        source.write_bytes(original)
        duplicate_dir = root / "duplicate"
        duplicate_dir.mkdir()
        (duplicate_dir / source.name).write_bytes(original)
        try:
            read_inventory(root)
        except ValueError as error:
            assert "Ambiguous" in str(error)
        else:
            raise AssertionError("Duplicate rollout ID accepted")


def test_running_client_changed_file_and_unknown_lsof_error_fail():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        source, child, grandchild = fixture(root)
        with patch("codex_session_storage.require_codex_stopped", side_effect=RuntimeError("running")):
            try:
                run_repair(root, True, False)
            except RuntimeError as error:
                assert str(error) == "running"
            else:
                raise AssertionError("Running client accepted")
        signatures = {source: file_signature(source)}
        with source.open("ab") as output:
            output.write(record_bytes(event(4, "concurrent append")))
        try:
            require_unchanged(signatures)
        except RuntimeError as error:
            assert "changed" in str(error)
        else:
            raise AssertionError("Concurrent change accepted")
        with patch("codex_session_storage.open_file_check") as check:
            check.return_value.returncode = 1
            check.return_value.stdout = ""
            check.return_value.stderr = "unexpected warning"
            try:
                require_closed(source)
            except RuntimeError as error:
                assert "unexpected warning" in str(error)
            else:
                raise AssertionError("Unknown warning ignored")


def test_legacy_rewriters_cannot_touch_linked_files():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        paths = fixture(root, False)
        for path in paths:
            try:
                require_unlinked_session(path)
            except ValueError:
                pass
            else:
                raise AssertionError("Linked file accepted for legacy rewrite")
            try:
                repair_tool_search_session(str(path), True)
            except ValueError as error:
                assert "rewrite" in str(error)
            else:
                raise AssertionError("Tool search repair bypassed lineage protection")


def test_lock_contention_and_failed_staging_do_not_modify_sessions():
    import fcntl
    import os

    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        paths = fixture(root)
        with patch("codex_session_storage.require_codex_stopped"):
            with offline_session_lock([root]):
                descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        raise AssertionError("Concurrent maintenance lock accepted")
                finally:
                    os.close(descriptor)
        _, _, repairs = prepare_repairs(root, False)
        original = repairs[0]["path"].read_bytes()
        repairs[0]["old_header"] = b"wrong\n"
        try:
            stage_header_repair(repairs[0])
        except RuntimeError:
            pass
        else:
            raise AssertionError("Changed header was accepted")
        assert repairs[0]["path"].read_bytes() == original
        assert not list(root.glob(".session-maintenance-*"))


def test_eof_cutoff_is_valid_and_json_errors_fail():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "source"
        raw = record_bytes(metadata(SOURCE_ID, 0)) + record_bytes(event(1, "last"))
        path.write_bytes(raw)
        positions = locate_ordinals(path, {2}, False)
        assert positions[2] == {"offset": len(raw), "record": None}
        path.write_bytes(raw + b'{"broken":\n')
        try:
            process_clean_records(path, len(record_bytes(metadata(SOURCE_ID, 0))))
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid JSON was silently skipped")


def test_partial_batch_can_resume_without_double_repair():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "sessions"
        fixture(root)
        with patch("codex_session_storage.require_codex_stopped"), patch("codex_session_storage.require_closed"):
            from codex_session_storage import replace_verified

            _, signatures, repairs = prepare_repairs(root, False)
            first = repairs[0]
            staged = stage_header_repair(first)
            replace_verified(first["path"], staged, signatures, "lineage-repair")
            remaining = run_repair(root, True, False)
            assert len(remaining) == 1
            assert run_repair(root, True, False) == []
            protected_prefixes(read_inventory(root))


def body_sha256(path):
    with path.open("rb") as stream:
        stream.readline()
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rehearse_real_sessions(original_root, temporary_parent):
    inventory, signatures, repairs = prepare_repairs(original_root)
    links = history_links(inventory)
    involved = {link[role]["path"] for link in links for role in ("child", "source")}
    evidence = {backup for repair in repairs for backup in repair["evidence"]}
    required_bytes = sum(path.stat().st_size for path in involved | evidence)
    if shutil.disk_usage(temporary_parent).free < required_bytes * 2:
        raise RuntimeError("Insufficient free space for a full isolated rehearsal and its backups")
    with TemporaryDirectory(prefix="lineage-rehearsal-", dir=temporary_parent) as directory:
        copied_root = Path(directory) / "sessions"
        copied_root.mkdir()
        copied_paths = {}
        for source in tqdm(sorted(involved | evidence), total=len(involved | evidence), desc="Copying isolated fixtures", unit="file"):
            destination = copied_root / source.relative_to(original_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied_paths[source] = destination
        require_unchanged(signatures)
        original_bodies = {}
        for source in tqdm(sorted(involved), total=len(involved), desc="Hashing source bodies", unit="file"):
            original_bodies[source] = body_sha256(source)
            assert body_sha256(copied_paths[source]) == original_bodies[source]
        # Only the client-process check is mocked, strictly for these isolated copies.
        # Real lsof checks, locks, backups, atomic writes and verification still run.
        with patch("codex_session_storage.require_codex_stopped"):
            applied = run_repair(copied_root, True)
            assert len(applied) == len(repairs)
            for source in tqdm(sorted(involved), total=len(involved), desc="Verifying every body byte", unit="file"):
                destination = copied_paths[source]
                assert destination.stat().st_size == source.stat().st_size
                assert body_sha256(destination) == original_bodies[source]
            assert run_repair(copied_root, True) == []
            # A cleanup after repair must preserve every referenced cutoff.
            clean_sessions([copied_paths[repairs[-1]["path"]]], True)
            protected_prefixes(read_inventory(copied_root))
        require_unchanged(signatures)
        print(f"REAL_COPY_REHEARSAL_OK links={len(links)} repaired={len(applied)} bodies_unchanged={len(involved)} originals_untouched=true")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-sessions-root", type=Path)
    parser.add_argument("--temporary-parent", type=Path)
    arguments = parser.parse_args()
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        with redirect_stdout(io.StringIO()):
            test()
        print(f"PASS {test.__name__}")
    print(f"lineage tests: {len(tests)} passed")
    if arguments.real_sessions_root is not None:
        if arguments.temporary_parent is None:
            raise ValueError("An explicit --temporary-parent is required for real-copy rehearsal")
        rehearse_real_sessions(arguments.real_sessions_root.absolute(), arguments.temporary_parent.absolute())


if __name__ == "__main__":
    main()

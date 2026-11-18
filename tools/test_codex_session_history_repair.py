import json
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codex_session_history_repair import home_repair_summary, repair_history_home
from codex_session_lineage import read_header
from codex_session_projection import connect_history, projection_rows
from codex_session_storage import offline_session_lock
from test_codex_session_projection import THREAD_ID, encoded, fixture, fail_mid_transaction

ARCHIVED_ID = "00000000-0000-0000-0000-000000000002"


def make_home_fixture(home):
    source, records, database = fixture(home)
    old_header = b" " * 100 + encoded(records[0])
    old_cutoff = len(old_header) + len(encoded(records[1]))
    backup = source.with_name(source.name + ".doctor-bak-fixture")
    backup.write_bytes(old_header + b"".join(map(encoded, records[1:])))
    archive = home / "archived_sessions"
    archive.mkdir()
    child = archive / f"rollout-test-{ARCHIVED_ID}.jsonl"
    metadata = {"ordinal": 2, "type": "session_meta", "payload": {"id": ARCHIVED_ID, "history_mode": "paginated",
                "history_base": {"thread_id": THREAD_ID, "end_byte_offset": old_cutoff, "end_ordinal_exclusive": 2}}}
    child_records = [metadata, {"ordinal": 3, "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "archived-turn"}}]
    child.write_bytes(b"".join(map(encoded, child_records)))
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM thread_history_projection_state WHERE thread_id='unrelated'")
        connection.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)", (ARCHIVED_ID,4,9999))
        connection.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?)", (ARCHIVED_ID,"archived-turn",3,8888,3,9999))
        connection.commit()
    return source, child, backup, database


def allow_offline_fixture(stack):
    stack.enter_context(patch("codex_session_storage.require_codex_stopped"))
    stack.enter_context(patch("codex_session_history_repair.require_codex_stopped"))
    stack.enter_context(patch("codex_session_history_repair.require_closed"))
    stack.enter_context(patch("codex_session_storage.require_closed"))


def test_all_home_preserves_messages_and_repeat_is_noop():
    with TemporaryDirectory() as directory, ExitStack() as stack:
        home = Path(directory)
        source, child, backup, database = make_home_fixture(home)
        source_before, child_before = source.read_bytes(), child.read_bytes()
        database_before = database.read_bytes()
        dry = repair_history_home(home)
        assert home_repair_summary(dry)["projection_repairs"] == 2
        assert home_repair_summary(dry)["lineage_header_repairs"] == 1
        assert database.read_bytes() == database_before
        assert child.read_bytes() == child_before
        allow_offline_fixture(stack)
        repair_history_home(home, True)
        assert source.read_bytes() == source_before
        assert len(child.read_bytes()) == len(child_before)
        assert child.read_bytes().split(b"\n",1)[1] == child_before.split(b"\n",1)[1]
        assert read_header(child)["record"]["payload"]["history_base"]["end_byte_offset"] == sum(map(len,source_before.splitlines(keepends=True)[:2]))
        with closing(connect_history(database)) as connection:
            assert connection.execute("SELECT item_json FROM thread_items").fetchall() == [('{"text":"original indexed message"}',)]
            assert connection.execute("SELECT * FROM thread_realtime_items").fetchall() == [(THREAD_ID,"realtime-1")]
        second = repair_history_home(home, True)
        assert home_repair_summary(second)["projection_repairs"] == 0
        assert home_repair_summary(second)["lineage_header_repairs"] == 0
        assert len(list((home / "session_maintenance_backups").glob("*.sqlite"))) == 1
        assert len(list(child.parent.glob("*.lineage-repair-bak-*"))) == 1


def test_interruption_after_header_rolls_back_db_and_retry_completes():
    with TemporaryDirectory() as directory, ExitStack() as stack:
        home = Path(directory)
        source, child, backup, database = make_home_fixture(home)
        allow_offline_fixture(stack)
        with patch("codex_session_history_repair.apply_projection_plan", side_effect=fail_mid_transaction):
            try:
                repair_history_home(home, True)
            except RuntimeError as error:
                assert "injected" in str(error)
            else:
                raise AssertionError("Interrupted repair succeeded")
        with closing(connect_history(database)) as connection:
            assert projection_rows(connection, THREAD_ID)[1] == (4,9000)
        retry = repair_history_home(home, True)
        assert home_repair_summary(retry)["lineage_header_repairs"] == 0
        assert home_repair_summary(retry)["projection_repairs"] == 2
        assert len(list(child.parent.glob("*.lineage-repair-bak-*"))) == 1


def test_missing_evidence_blocks_every_write():
    with TemporaryDirectory() as directory, ExitStack() as stack:
        home = Path(directory)
        source, child, backup, database = make_home_fixture(home)
        backup.unlink()
        before = (source.read_bytes(), child.read_bytes(), database.read_bytes())
        allow_offline_fixture(stack)
        try:
            repair_history_home(home, True)
        except ValueError as error:
            assert "No backup proves" in str(error)
        else:
            raise AssertionError("Unproven header repair accepted")
        assert before == (source.read_bytes(), child.read_bytes(), database.read_bytes())
        assert not (home / "session_maintenance_backups").exists()


def test_missing_indexed_file_and_unknown_database_are_rejected():
    with TemporaryDirectory() as directory:
        home = Path(directory)
        source, child, backup, database = make_home_fixture(home)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("INSERT INTO thread_history_projection_state VALUES ('missing',0,0)")
            connection.commit()
        try:
            repair_history_home(home)
        except ValueError as error:
            assert "Indexed rollouts missing" in str(error)
        else:
            raise AssertionError("Missing indexed file ignored")
        (home / "thread_history_2.sqlite").touch()
        try:
            repair_history_home(home)
        except ValueError as error:
            assert "Unknown history database" in str(error)
        else:
            raise AssertionError("Unknown database ignored")


def test_running_codex_and_overlapping_repair_are_rejected():
    with TemporaryDirectory() as directory:
        home = Path(directory)
        source, child, backup, database = make_home_fixture(home)
        with patch("codex_session_storage.require_codex_stopped", side_effect=RuntimeError("running")):
            try:
                repair_history_home(home, True)
            except RuntimeError as error:
                assert str(error) == "running"
            else:
                raise AssertionError("Running Codex accepted")
        with patch("codex_session_storage.require_codex_stopped"), offline_session_lock([home]):
            try:
                repair_history_home(home, True)
            except BlockingIOError:
                assert not (home / "session_maintenance_backups").exists()
            else:
                raise AssertionError("Overlapping repair acquired same lock")


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"home history repair tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

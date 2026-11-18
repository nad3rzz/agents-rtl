import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codex_session_doctor import clean_sessions
from codex_session_projection import (
    HISTORY_DATABASE_NAME, connect_history, prepare_projection_plan,
    projection_rows, repair_projection, require_no_projection_rewrite,
    validate_projection_schema,
)

THREAD_ID = "00000000-0000-0000-0000-000000000001"


def encoded(record):
    return (json.dumps(record) + "\n").encode()


def fixture(home):
    sessions = home / "sessions"
    sessions.mkdir()
    path = sessions / f"rollout-test-{THREAD_ID}.jsonl"
    records = [
        {"ordinal": 0, "type": "session_meta", "payload": {"id": THREAD_ID, "history_mode": "paginated"}},
        {"ordinal": 1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}},
        {"ordinal": 2, "type": "event_msg", "payload": {"type": "item_completed", "item": {"id": "message-1", "text": "old message"}}},
        {"ordinal": 3, "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}},
        {"ordinal": 4, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-2"}},
        {"ordinal": 5, "type": "event_msg", "payload": {"type": "item_completed", "item": {"id": "message-2", "text": "new message"}}},
    ]
    path.write_bytes(b"".join(map(encoded, records)))
    database_path = home / HISTORY_DATABASE_NAME
    with closing(sqlite3.connect(database_path)) as database:
        database.executescript("""
            CREATE TABLE thread_turns (thread_id TEXT,turn_id TEXT,rollout_ordinal INTEGER,rollout_byte_offset INTEGER,rollout_end_ordinal INTEGER,rollout_end_byte_offset INTEGER, PRIMARY KEY(thread_id,turn_id));
            CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY,next_rollout_ordinal INTEGER,next_rollout_byte_offset INTEGER);
            CREATE TABLE thread_items (thread_id TEXT,item_id TEXT,item_json TEXT);
            CREATE TABLE thread_realtime_items (thread_id TEXT,item_id TEXT);
        """)
        database.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?)", (THREAD_ID,"turn-1",1,8000,3,9000))
        database.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)", (THREAD_ID,4,9000))
        database.execute("INSERT INTO thread_items VALUES (?,?,?)", (THREAD_ID,"message-1",'{"text":"original indexed message"}'))
        database.execute("INSERT INTO thread_realtime_items VALUES (?,?)", (THREAD_ID,"realtime-1"))
        database.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)", ("unrelated",100,99999))
        database.commit()
    return path, records, database_path


def test_offsets_only_repair_and_idempotence():
    with TemporaryDirectory() as directory:
        path, records, database_path = fixture(Path(directory))
        original = path.read_bytes()
        with closing(connect_history(database_path)) as reader:
            items = reader.execute("SELECT * FROM thread_items").fetchall()
        with patch("codex_session_storage.require_codex_stopped"), patch("codex_session_projection.require_codex_stopped"), patch("codex_session_projection.require_closed"):
            plans = repair_projection(path, True)
            repair_projection(path, True)
        assert path.read_bytes() == original
        assert len(list((Path(directory)/"session_maintenance_backups").glob("*.sqlite"))) == 1
        with closing(connect_history(database_path)) as reader:
            assert reader.execute("SELECT * FROM thread_items").fetchall() == items
            assert reader.execute("SELECT * FROM thread_realtime_items").fetchall() == [(THREAD_ID,"realtime-1")]
            assert reader.execute("SELECT next_rollout_byte_offset FROM thread_history_projection_state WHERE thread_id='unrelated'").fetchone() == (99999,)
            turns, checkpoint = projection_rows(reader, THREAD_ID)
            assert turns[0][2] == len(encoded(records[0]))
            assert checkpoint == (4, sum(len(encoded(record)) for record in records[:4]))
            assert checkpoint[0] == plans[0]["old_checkpoint"][0]
        backup = next((Path(directory)/"session_maintenance_backups").glob("*.sqlite"))
        with closing(connect_history(backup)) as reader:
            assert projection_rows(reader, THREAD_ID)[1] == (4,9000)


def fail_mid_transaction(connection, plans):
    connection.execute("UPDATE thread_turns SET rollout_byte_offset=123 WHERE thread_id=?", (THREAD_ID,))
    raise RuntimeError("injected transaction failure")


def test_transaction_rollback_preserves_old_offsets():
    with TemporaryDirectory() as directory:
        path, records, database_path = fixture(Path(directory))
        with patch("codex_session_storage.require_codex_stopped"), patch("codex_session_projection.require_codex_stopped"), patch("codex_session_projection.require_closed"), patch("codex_session_projection.apply_projection_plan", side_effect=fail_mid_transaction):
            try:
                repair_projection(path, True)
            except RuntimeError as error:
                assert "injected" in str(error)
            else:
                raise AssertionError("Injected write failure was hidden")
        with closing(connect_history(database_path)) as reader:
            assert projection_rows(reader, THREAD_ID)[0][0][2] == 8000
            assert projection_rows(reader, THREAD_ID)[1] == (4,9000)


def test_identity_mismatch_and_unknown_trigger_are_rejected():
    with TemporaryDirectory() as directory:
        path, records, database_path = fixture(Path(directory))
        records[1]["payload"]["turn_id"] = "different-turn"
        path.write_bytes(b"".join(map(encoded, records)))
        with closing(connect_history(database_path)) as reader:
            try:
                prepare_projection_plan(path, reader)
            except ValueError as error:
                assert "Turn identity" in str(error)
            else:
                raise AssertionError("Wrong turn accepted")
        with closing(sqlite3.connect(database_path)) as writer:
            writer.execute("CREATE TRIGGER unexpected AFTER UPDATE ON thread_turns BEGIN SELECT 1; END")
            writer.commit()
            try:
                validate_projection_schema(writer)
            except ValueError as error:
                assert "Unexpected trigger" in str(error)
            else:
                raise AssertionError("Unknown trigger accepted")


def test_doctor_blocks_projected_rollouts_without_changes():
    with TemporaryDirectory() as directory:
        path, records, database_path = fixture(Path(directory))
        before = path.read_bytes()
        try:
            require_no_projection_rewrite([path])
        except ValueError as error:
            assert "Refusing to rewrite an indexed rollout" in str(error)
        else:
            raise AssertionError("Projection rewrite guard did not fail")
        with patch("codex_session_storage.require_codex_stopped"):
            try:
                clean_sessions([path], True)
            except ValueError as error:
                assert "Refusing to rewrite an indexed rollout" in str(error)
            else:
                raise AssertionError("Doctor rewrote a projected rollout")
        assert path.read_bytes() == before
        assert not list(path.parent.glob("*.doctor-bak-*"))


def test_apply_refuses_running_codex_and_readonly_plan_does_not_write():
    with TemporaryDirectory() as directory:
        path, records, database_path = fixture(Path(directory))
        before = database_path.read_bytes()
        repair_projection(path, False)
        assert database_path.read_bytes() == before
        with patch("codex_session_storage.require_codex_stopped", side_effect=RuntimeError("running")):
            try:
                repair_projection(path, True)
            except RuntimeError as error:
                assert str(error) == "running"
            else:
                raise AssertionError("Running Codex accepted")
        assert database_path.read_bytes() == before


def main():
    tests = [value for name,value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print("PASS",test.__name__)
    print(f"projection tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

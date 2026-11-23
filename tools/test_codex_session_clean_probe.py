import json
import sqlite3
from contextlib import closing
from pathlib import Path

import codex_session_clean_probe as probe
import pytest
from codex_session_image_projection import (
    apply_projected_images,
    clean_projected_user_image,
    inline_images,
    plan_projected_images,
    projected_items,
)
from codex_session_projection import HISTORY_DATABASE_NAME, connect_history
from codex_session_storage import sha256_file

THREAD = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
IMAGE = "data:image/png;base64," + "AAAA" * 1024


def encode(record):
    return (json.dumps(record, ensure_ascii=False) + "\n").encode()


def make_probe_fixture(home):
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / f"rollout-test-{THREAD}.jsonl"
    records = [{"type": "session_meta", "payload": {"id": THREAD, "history_mode": "paginated"}}]
    turns, items = [], []
    for number, text in enumerate(("before", "describe image", "after")):
        turn_id = f"turn-{number}"
        start = len(records)
        content = [{"type": "text", "text": text, "text_elements": []}]
        input_content = [{"type": "input_text", "text": text}]
        projected_content = list(content)
        if number == 1:
            content.append({"type": "image", "image_url": IMAGE})
            input_content.append({"type": "input_image", "image_url": IMAGE})
            projected_content.append({"type": "image", "detail": "auto", "url": IMAGE})
        source_item = {"type": "UserMessage", "id": f"user-{number}", "client_id": f"client-{number}", "content": content}
        item = {"type": "userMessage", "id": source_item["id"], "clientId": source_item["client_id"], "content": projected_content}
        records.extend([
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn_id}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": input_content}},
            {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": turn_id, "thread_id": THREAD, "item": source_item}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "reply " + text}]}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id}},
        ])
        turns.append((turn_id, start, len(records) - 1))
        items.append((turn_id, item, start + 2))
    for ordinal, record in enumerate(records):
        record["ordinal"] = ordinal
    path.write_bytes(b"".join(map(encode, records)))
    positions = probe.inspect_positions(path)
    database_path = home / HISTORY_DATABASE_NAME
    with closing(sqlite3.connect(database_path)) as database:
        database.executescript("""
            CREATE TABLE thread_turns (thread_id TEXT,turn_id TEXT,rollout_ordinal INTEGER,rollout_byte_offset INTEGER,rollout_end_ordinal INTEGER,rollout_end_byte_offset INTEGER, PRIMARY KEY(thread_id,turn_id));
            CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY,next_rollout_ordinal INTEGER,next_rollout_byte_offset INTEGER);
            CREATE TABLE thread_items (thread_id TEXT,turn_id TEXT,item_id TEXT,rollout_ordinal INTEGER,updated_at_ordinal INTEGER,item_type TEXT,item_json TEXT, PRIMARY KEY(thread_id,turn_id,item_id));
            CREATE TABLE thread_realtime_items (thread_id TEXT,item_id TEXT,rollout_ordinal INTEGER,item_type TEXT,item_json TEXT,PRIMARY KEY(thread_id,item_id));
        """)
        for turn_id, start, end in turns:
            database.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?)", (THREAD, turn_id, start, positions[start]["offset"], end, positions[end+1]["offset"]))
        database.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)", (THREAD, len(records), path.stat().st_size))
        for turn_id, item, ordinal in items:
            database.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)", (THREAD, turn_id, item["id"], ordinal, ordinal, item["type"], json.dumps(item)))
        database.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)", ("unrelated", "other-turn", "other-item", 5, 5, "sentinel", '{"untouched":true}'))
        database.commit()
    return path, database_path


def test_isolated_cleanup_preserves_source_texts_offsets_and_other_threads(tmp_path, monkeypatch):
    source, database = make_probe_fixture(tmp_path / "source")
    output_parent = tmp_path / "nosync"
    output_parent.mkdir()
    monkeypatch.setattr(probe, "PROBE_PARENT", output_parent)
    before = sha256_file(source), sha256_file(database)
    proof = probe.run_probe(source)
    assert proof["source_unchanged"] and proof["message_text_order_identity_preserved"]
    assert proof["indexed_images_updated"] == 1
    assert proof["turns"] == 3 and proof["turn_offsets_updated"] == 2
    assert proof["saved_bytes"] > len(IMAGE)
    assert proof["native_ui_verified"] is False
    assert (sha256_file(source), sha256_file(database)) == before
    copied_database = Path(proof["output_home"]) / HISTORY_DATABASE_NAME
    with closing(connect_history(copied_database)) as reader:
        assert reader.execute("SELECT item_json FROM thread_items WHERE thread_id='unrelated'").fetchone() == ('{"untouched":true}',)
        assert not inline_images(projected_items(reader, THREAD))


def test_linked_or_archived_child_is_rejected(tmp_path, monkeypatch):
    source, _ = make_probe_fixture(tmp_path / "source")
    archived = source.parent.parent / "archived_sessions"
    archived.mkdir()
    child = archived / f"rollout-child-{CHILD}.jsonl"
    child.write_bytes(encode({"ordinal": 1, "type": "session_meta", "payload": {
        "id": CHILD, "history_mode": "paginated", "history_base": {
            "thread_id": THREAD, "end_ordinal_exclusive": 1, "end_byte_offset": 1,
        },
    }}))
    output_parent = tmp_path / "nosync"
    output_parent.mkdir()
    monkeypatch.setattr(probe, "PROBE_PARENT", output_parent)
    with pytest.raises(ValueError, match="unlinked"):
        probe.run_probe(source)
    assert not list(output_parent.iterdir())


def test_stale_projection_is_rejected_before_copy(tmp_path, monkeypatch):
    source, database = make_probe_fixture(tmp_path / "source")
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("UPDATE thread_history_projection_state SET next_rollout_byte_offset=999999")
        writer.commit()
    output_parent = tmp_path / "nosync"
    output_parent.mkdir()
    monkeypatch.setattr(probe, "PROBE_PARENT", output_parent)
    with pytest.raises(ValueError, match="incorrect offsets"):
        probe.run_probe(source)
    assert not list(output_parent.iterdir())


def test_corrupt_projection_image_is_rejected(tmp_path):
    source, database = make_probe_fixture(tmp_path / "source")
    with closing(connect_history(database, writable=True)) as writer:
        value = json.loads(writer.execute("SELECT item_json FROM thread_items WHERE item_id='user-1'").fetchone()[0])
        value["content"][1]["url"] = "data:image/png;base64,BBBB"
        writer.execute("UPDATE thread_items SET item_json=? WHERE item_id='user-1'", (json.dumps(value),))
        writer.commit()
        with pytest.raises(ValueError, match="image bytes differ"):
            plan_projected_images(writer, THREAD, probe.inspect_positions(source))


def test_unknown_and_image_only_shapes_are_rejected():
    source = {"type": "UserMessage", "id": "u", "client_id": None, "content": [{"type": "image", "image_url": IMAGE}]}
    item = {"type": "userMessage", "id": "u", "clientId": None, "content": [{"type": "image", "url": IMAGE, "detail": "auto"}]}
    with pytest.raises(ValueError, match="empty content"):
        clean_projected_user_image(item, source)
    item["content"][0]["unknown"] = True
    with pytest.raises(ValueError, match="Unknown"):
        clean_projected_user_image(item, source)


def test_failed_item_update_rolls_back_offset_update(tmp_path):
    source, database = make_probe_fixture(tmp_path / "source")
    with closing(connect_history(database, writable=True)) as writer:
        _, updates = plan_projected_images(writer, THREAD, probe.inspect_positions(source))
        old_offsets = writer.execute("SELECT * FROM thread_turns").fetchall()
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE thread_turns SET rollout_byte_offset=0")
        updates[0]["old_json"] = "mismatch"
        with pytest.raises(RuntimeError, match="changed after planning"):
            apply_projected_images(writer, updates)
        writer.rollback()
        assert writer.execute("SELECT * FROM thread_turns").fetchall() == old_offsets

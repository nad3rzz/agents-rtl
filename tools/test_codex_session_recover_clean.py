import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codex_session_recover_clean import reconstruct_records, recover_session, reproduce_legacy_cleaning


def make_record(text):
    return {
        "type": "event_msg",
        "timestamp": "2026-11-15T10:00:00Z",
        "payload": {
            "type": "item_completed",
            "completed_at_ms": None,
            "item": {"content": [{"type": "text", "text": text}, {"type": "image", "image_url": "data:image/png;base64,AAAA"}]},
        },
    }


def write_records(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_chained_recovery_preserves_new_events_and_is_idempotent():
    with TemporaryDirectory() as directory:
        oldest, newest, current, reconstructed = [Path(directory) / name for name in ("oldest", "newest", "current", "reconstructed")]
        first, second, third = [make_record(text) for text in ("first", "second", "newest reply")]
        write_records(oldest, [first])
        write_records(newest, [reproduce_legacy_cleaning(first), second])
        write_records(current, [reproduce_legacy_cleaning(first), reproduce_legacy_cleaning(second), third])
        original_current = current.read_bytes()
        with reconstructed.open("wb") as output:
            result = reconstruct_records([oldest, newest, current], output, show_progress=False)
        assert result == {"source_events": [1, 2, 3], "recovered_events": 2, "preserved_new_events": 1}
        assert [json.loads(line) for line in reconstructed.read_bytes().splitlines()] == [first, second, third]
        assert current.read_bytes() == original_current
        repeated = reconstruct_records([oldest, newest, reconstructed], show_progress=False)
        assert repeated["recovered_events"] == 0


def test_unexplained_changes_and_shorter_targets_are_rejected():
    with TemporaryDirectory() as directory:
        backup, current = [Path(directory) / name for name in ("backup", "current")]
        write_records(backup, [make_record("original")])
        write_records(current, [make_record("different message")])
        try:
            reconstruct_records([backup, current], show_progress=False)
        except ValueError as error:
            assert "Unexplained difference" in str(error)
        else:
            raise AssertionError("Recovery accepted a different message")
        write_records(current, [])
        try:
            reconstruct_records([backup, current], show_progress=False)
        except ValueError as error:
            assert "shorter" in str(error)
        else:
            raise AssertionError("Recovery accepted a truncated current session")


def test_apply_rejects_running_clients_without_writing():
    with TemporaryDirectory() as directory:
        backup, current = [Path(directory) / name for name in ("backup", "current")]
        original = make_record("message")
        write_records(backup, [original])
        write_records(current, [reproduce_legacy_cleaning(original)])
        before = current.read_bytes()
        with patch("codex_session_recover_clean.require_codex_stopped", side_effect=RuntimeError("Codex is running")):
            try:
                recover_session(current, [backup], apply_changes=True)
            except RuntimeError as error:
                assert str(error) == "Codex is running"
            else:
                raise AssertionError("Recovery wrote while a client was running")
        assert current.read_bytes() == before
        assert sorted(path.name for path in Path(directory).iterdir()) == ["backup", "current"]


def test_apply_saves_original_and_repeated_apply_is_noop():
    with TemporaryDirectory() as directory:
        backup, current = [Path(directory) / name for name in ("backup", "current")]
        original = make_record("message")
        write_records(backup, [original])
        write_records(current, [reproduce_legacy_cleaning(original), make_record("later reply")])
        before = current.read_bytes()
        with patch("codex_session_recover_clean.require_codex_stopped"):
            result = recover_session(current, [backup], apply_changes=True)
            assert Path(result["backup"]).read_bytes() == before
            assert json.loads(current.read_bytes().splitlines()[0]) == original
            assert result["preserved_new_events"] == 1
            repeated = recover_session(current, [backup], apply_changes=True)
            assert repeated["status"] == "already_recovered"
        assert len(list(Path(directory).glob("*.restore-bak-*"))) == 1
        assert not list(Path(directory).glob(".session-recovery-*"))


def main():
    tests = (
        test_chained_recovery_preserves_new_events_and_is_idempotent,
        test_unexplained_changes_and_shorter_targets_are_rejected,
        test_apply_rejects_running_clients_without_writing,
        test_apply_saves_original_and_repeated_apply_is_noop,
    )
    for test in tests:
        test()
    print(f"codex_session_recover_clean tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

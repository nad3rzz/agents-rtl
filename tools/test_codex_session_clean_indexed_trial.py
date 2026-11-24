import json
import multiprocessing
import os
from contextlib import closing
from pathlib import Path

import codex_session_clean_indexed_trial as trial
import codex_session_clean_probe as probe
import codex_session_image_transaction as transaction
import codex_session_storage as storage
import pytest
from codex_session_image_projection import inline_images, projected_items
from codex_session_projection import (
    connect_history,
    projection_plan_changed,
    projection_plan_from_positions,
    projection_rows,
)
from test_codex_session_clean_probe import THREAD, make_probe_fixture

PROCESS_INTERRUPTED_EXIT_CODE = 73


def allow_offline_test(*arguments):
    """Synthetic homes only; no production guard is weakened."""
    return


@pytest.fixture(params=["delete", "wal"])
def trial_fixture(tmp_path, monkeypatch, request):
    source, database = make_probe_fixture(tmp_path / "home")
    with closing(connect_history(database, writable=True)) as writer:
        assert writer.execute(f"PRAGMA journal_mode={request.param}").fetchone()[0] == request.param
    output = tmp_path / "nosync"
    output.mkdir()
    monkeypatch.setattr(probe, "PROBE_PARENT", output)
    monkeypatch.setattr(storage, "require_codex_stopped", allow_offline_test)
    monkeypatch.setattr(transaction, "require_codex_stopped", allow_offline_test)
    monkeypatch.setattr(transaction, "require_closed", allow_offline_test)
    monkeypatch.setattr(trial, "require_codex_stopped", allow_offline_test)
    monkeypatch.setattr(trial, "require_closed", allow_offline_test)
    return source, database


def capture_state(source, database):
    with closing(connect_history(database)) as reader:
        return storage.sha256_file(source), transaction.database_state(reader, THREAD)


def pending_journal(source):
    paths = list((source.parent.parent / "session_maintenance_backups").glob("image-clean-transaction-*/transaction.json"))
    assert len(paths) == 1
    return paths[0]


def test_trial_updates_file_and_index_but_not_other_threads(trial_fixture):
    source, database = trial_fixture
    original_hash, _ = capture_state(source, database)
    path = trial.run_trial(source)
    journal = transaction.load_journal(path)
    assert journal["status"] == "applied"
    assert journal["old_sha256"] == original_hash
    assert storage.sha256_file(path.parent / "original.jsonl") == original_hash
    assert Path(journal["database_backup"]).is_file()
    assert capture_state(source, database) == (journal["new_sha256"], journal["new_database"])
    with closing(connect_history(database)) as reader:
        turns, checkpoint = projection_rows(reader, THREAD)
        assert not projection_plan_changed(projection_plan_from_positions(source, turns, checkpoint, probe.inspect_positions(source)))
        assert not inline_images(projected_items(reader, THREAD))
        assert reader.execute("SELECT item_json FROM thread_items WHERE thread_id='unrelated'").fetchone() == ('{"untouched":true}',)
    assert transaction.recover_transaction_locked(path) == "applied"
    after = capture_state(source, database)
    with pytest.raises(ValueError, match="No proved indexed images"):
        trial.run_trial(source)
    assert capture_state(source, database) == after


def fail_before_publish(*arguments):
    raise RuntimeError("injected before publish")


def fail_after_publish(*arguments):
    transaction.publish_verified_file(*arguments)
    raise RuntimeError("injected after publish")


def interrupt_after_publish(*arguments):
    transaction.publish_verified_file(*arguments)
    raise KeyboardInterrupt("injected interrupt")


@pytest.mark.parametrize("injection,exception", [
    (fail_before_publish, RuntimeError), (fail_after_publish, RuntimeError),
    (interrupt_after_publish, KeyboardInterrupt),
])
def test_normal_failure_restores_both_resources(trial_fixture, monkeypatch, injection, exception):
    source, database = trial_fixture
    before = capture_state(source, database)
    monkeypatch.setattr(trial, "publish_verified_file", injection)
    with pytest.raises(exception, match="injected"):
        trial.run_trial(source)
    assert capture_state(source, database) == before
    assert transaction.load_journal(pending_journal(source))["status"] == "rolled_back"


def crash_after_publish(*arguments):
    transaction.publish_verified_file(*arguments)
    os._exit(PROCESS_INTERRUPTED_EXIT_CODE)


def crash_before_final_verification(*arguments):
    os._exit(PROCESS_INTERRUPTED_EXIT_CODE)


def run_crashing_trial(source, output, crash_location):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(probe, "PROBE_PARENT", output)
        monkeypatch.setattr(storage, "require_codex_stopped", allow_offline_test)
        monkeypatch.setattr(transaction, "require_codex_stopped", allow_offline_test)
        monkeypatch.setattr(transaction, "require_closed", allow_offline_test)
        monkeypatch.setattr(trial, "require_codex_stopped", allow_offline_test)
        monkeypatch.setattr(trial, "require_closed", allow_offline_test)
        if crash_location == "before_commit":
            monkeypatch.setattr(trial, "publish_verified_file", crash_after_publish)
        else:
            monkeypatch.setattr(trial, "recover_transaction_locked", crash_before_final_verification)
        trial.run_trial(source)


@pytest.mark.parametrize("crash_location,result", [("before_commit", "rolled_back"), ("after_commit", "applied")])
def test_process_death_recovers_known_boundary(trial_fixture, crash_location, result):
    source, database = trial_fixture
    before = capture_state(source, database)
    process = multiprocessing.get_context("spawn").Process(
        target=run_crashing_trial, args=(source, probe.PROBE_PARENT, crash_location))
    process.start()
    process.join(timeout=20)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("Crash test did not terminate")
    assert process.exitcode == PROCESS_INTERRUPTED_EXIT_CODE
    path = pending_journal(source)
    journal = transaction.load_journal(path)
    assert journal["status"] == "prepared"
    with pytest.raises(RuntimeError, match="pending transaction"):
        transaction.require_no_pending_transactions(source.parent.parent)
    assert transaction.recover_transaction_locked(path) == result
    expected = before if result == "rolled_back" else (journal["new_sha256"], journal["new_database"])
    assert capture_state(source, database) == expected
    assert transaction.recover_transaction_locked(path) == result


def test_recovery_refuses_newer_messages(trial_fixture):
    source, database = trial_fixture
    path = trial.run_trial(source)
    with source.open("ab") as stream:
        stream.write(b'{"new":"message"}\n')
    before = capture_state(source, database)
    with pytest.raises(RuntimeError, match="not a known transaction boundary"):
        transaction.recover_transaction_locked(path)
    assert capture_state(source, database) == before


def test_partial_index_refused_before_probe(trial_fixture):
    source, database = trial_fixture
    with closing(connect_history(database, writable=True)) as writer:
        writer.execute("UPDATE thread_history_projection_state SET next_rollout_ordinal=1,next_rollout_byte_offset=1")
        writer.commit()
    before = capture_state(source, database)
    with pytest.raises(ValueError, match="fully indexed"):
        trial.run_trial(source)
    assert capture_state(source, database) == before
    assert not list(probe.PROBE_PARENT.iterdir())


def test_stale_plan_refused_without_overwriting_new_data(trial_fixture):
    source, database = trial_fixture
    path, journal, plan, updates = trial.prepare_trial(source)
    with closing(connect_history(database, writable=True)) as writer:
        writer.execute("UPDATE thread_items SET item_json=? WHERE thread_id=? AND item_id='user-0'", (json.dumps({"new": True}), THREAD))
        writer.commit()
    before = capture_state(source, database)
    with pytest.raises(RuntimeError, match="changed after planning"):
        trial.commit_trial(path, journal, plan, updates)
    assert capture_state(source, database) == before


def test_live_codex_refused_before_any_write(tmp_path):
    source, database = make_probe_fixture(tmp_path / "home")
    before = capture_state(source, database)
    # The real guard is exercised by the caller tests through a deterministic failure.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(storage, "require_codex_stopped", fail_before_publish)
        with pytest.raises(RuntimeError, match="injected"):
            trial.run_trial(source)
    assert capture_state(source, database) == before
    assert not (source.parent.parent / "session_maintenance_backups").exists()

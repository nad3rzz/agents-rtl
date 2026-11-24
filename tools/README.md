# Tools

## codex_apply_performance_workarounds.py

Local re-applier for verified Codex WebView performance workarounds:

- Caches heartbeat-only turn detection.
- Increases the streamed-text character budget per animation frame.

Useful commands:

```bash
python3 tools/codex_apply_performance_workarounds.py status --target all
python3 tools/codex_apply_performance_workarounds.py apply --target all
```

Notes:

- Patches VS Code and Antigravity Codex WebView assets only when the exact current signature matches.
- Creates backups before writing.
- Fails instead of guessing if Codex changes the relevant minified shape.
- Restart VS Code / Antigravity after `apply`.

## codex_session_doctor.py

Local maintenance CLI for Codex session `.jsonl` files.

Useful commands:

```bash
python3 tools/codex_session_doctor.py list
python3 tools/codex_session_doctor.py report --top 20
python3 tools/codex_session_doctor.py clean --session /path/to/session.jsonl
python3 tools/codex_session_doctor.py clean --session /path/to/session.jsonl --apply
python3 tools/codex_session_doctor.py repair-tool-search --session /path/to/session.jsonl
python3 tools/codex_session_doctor.py repair-tool-search --session /path/to/session.jsonl --apply
```

Notes:

- `clean --apply` refuses indexed rollouts. Tail-only cleanup is NOT safe when SQLite holds byte offsets. The separate experimental trial below is not integrated into doctor.
- For unindexed legacy files, `clean` removes image payloads only from unreferenced tails; shared prefixes and metadata remain unchanged.
- `repair-tool-search` removes corrupt `tool_search_call` records with invalid long argument property names and their failed parser outputs.
- `clean` is dry-run by default.
- `repair-tool-search` is dry-run by default.
- `--apply` always refuses to clean/repair an open session file; there is no override.
- Backups are written next to the original session as `.doctor-bak-*`.
- Cleanup preserves JSON `null` values and removes complete image items. Already broken image items require recovery first.
- Cleanup validates all history links before writing. Broken cutoffs must be repaired first; stopping clients alone does not repair them.
- No-op cleanup does not rewrite JSON or create a backup. Linux writes require all Codex clients stopped; do not restart them during maintenance.
- Legacy restore, migration, tool-search removal and record recovery refuse linked/paginated rollouts.

### Experimental Indexed Image Cleanup

Only for disposable, independent paginated test chats up to 16 MiB. Linked chats,
partial indexes, unproved image shapes and image-only messages are rejected.
This is NOT yet validated in the native UI and is not a general cleanup command.

```bash
# Copies only; never changes the original:
python3 -B tools/codex_session_clean_probe.py --session /absolute/sessions/path/rollout-....jsonl
# Close ALL Codex clients and keep them closed until completion/recovery:
python3 -B tools/codex_session_clean_indexed_trial.py --session /absolute/sessions/path/rollout-....jsonl --apply
# After interruption, use the recovery_journal path printed before writes:
python3 -B tools/codex_session_clean_indexed_trial.py --recover /absolute/path/transaction.json --apply
```

The trial removes images from both the rollout and selected projected user items,
updates offsets, preserves text/IDs/ordinals, and saves verified backups. File
replacement and SQLite commit are NOT jointly atomic: a durable journal recovers
known interruption boundaries, refusing unknown/newer state. Never reopen Codex
mid-operation. Recovery never restores a whole older database over other chats.
An unfinished journal blocks another trial; rerunning after success refuses the
now image-free input without rewriting it. Keep backups until native UI verification.

### Repair History Offsets

Old cleaners changed byte offsets without updating `history_base`. This tool proves
each replacement using contiguous ordinals and matching backup boundary records.
It changes only the header offset, pads JSON whitespace to retain header length,
and preserves every body byte, including newer messages. No backup is restored.

```bash
python3 tools/codex_session_repair_lineage.py --sessions-root ~/.codex/sessions
# After reviewing the plan, close all Codex clients and keep them closed:
python3 tools/codex_session_repair_lineage.py --sessions-root ~/.codex/sessions --apply
```

Each file replacement is atomic, backed up as `.lineage-repair-bak-*`, and verified.
Directory locks serialize these tools; Codex itself does not honor those locks,
so clients must stay closed. An interrupted batch can be rerun: completed repairs
are no-ops and fixed header lengths preserve the remaining source offsets.
Unknown records, missing evidence or concurrent changes abort explicitly.
Keep all backups until the conversations open correctly in Codex.

### Repair SQLite Projection Offsets

Fixing `history_base` alone does not fix `thread_history_1.sqlite`. A cleaner can
leave `next_rollout_byte_offset` and turn boundaries pointing into the old bytes,
causing `durable rollout shrank before projection` and an apparently old chat.

```bash
python3 tools/codex_session_repair_projection.py --session /absolute/sessions/path/rollout-....jsonl
# Close every Codex client, then run the same command with --apply.
```

This repairs the selected physical rollout and its ancestors in one SQLite
transaction. It proves contiguous ordinals and matching turn identities, changes
byte offsets only, and leaves next ordinals, item rows and JSONL files untouched.
A verified full SQLite backup is stored in `CODEX_HOME/session_maintenance_backups/`.
Interrupted transactions roll back; repeated successful application is a no-op.
Reopen the conversation to let Codex project the newer records. Successful SQL
verification is NOT sufficient: check the latest messages through native
`thread/turns/list` after resume, then confirm the actual UI with the user.

Tests: `python3 -B tools/test_codex_session_projection.py`.

### Repair All Histories (Including Archives)

```bash
python3 tools/codex_session_repair_projection.py --all-home ~/.codex
# Close every Codex client before applying:
python3 tools/codex_session_repair_projection.py --all-home ~/.codex --apply
```

This repairs index byte offsets, not messages. Stale lineage headers require matching
backup evidence and retain their exact byte length. Missing files, changed files,
unknown schemas, and overlapping runs fail explicitly. The history database is
backed up before writes; its offset updates commit in one transaction. Each header
replacement is independently atomic and backed up. If interrupted after a header
repair, that valid header remains; rerunning recomputes the remaining work.
No backups are deleted. Reopen and check the native history before declaring recovery.

Tests: `python3 -B tools/test_codex_session_history_repair.py`.

Regression tests: `python3 -B tools/test_codex_session_lineage.py`.
Optional real-copy rehearsal (writes only disposable test copies):

```bash
python3 -B tools/test_codex_session_lineage.py --real-sessions-root ~/.codex/sessions --temporary-parent ./nosync
```

### Recover Old Doctor Changes

`codex_session_recover_clean.py` restores original records from explicit backups,
retains newer records, and rejects differences not explained by the old cleaner.
Supply backups oldest first. Dry-run is the default; `--apply` requires all Codex
clients stopped and saves the current file as `.restore-bak-*` before replacement.

```bash
python3 tools/codex_session_recover_clean.py --session /path/session.jsonl --backup /path/oldest-backup --backup /path/newest-backup
```

## antigravity_native_network_monitor.py

Report-only monitor for Antigravity native agent traffic and local conversation file growth.

Useful command:

```bash
python3 tools/antigravity_native_network_monitor.py --trace-sockets --watch-conversation-id 948732df-66c3-4a49-8db6-f68f6ac1e809
```

Passive background-rate command:

```bash
python3 tools/antigravity_native_network_monitor.py --passive --trace-sockets --trace-files --duration-sec 60 --watch-conversation-id 948732df-66c3-4a49-8db6-f68f6ac1e809
```

Notes:

- The tool prints `SEND_MESSAGE_NOW`; send exactly one message after that marker.
- `--passive` starts measuring immediately without a send marker.
- `--trace-sockets` uses `strace` to estimate socket TX/RX bytes without printing payload content.
- Socket totals are split into external, loopback, local-network, local-IPC, and per-endpoint counters.
- `--trace-files` also records file syscall lines for watched conversation paths, to correlate local reads with socket writes.
- Reports are written to `~/Downloads/antigravity-native-net-monitor-*.json`.

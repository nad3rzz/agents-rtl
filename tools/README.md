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

- `clean` removes image payloads only from unreferenced tails. Shared history prefixes and metadata remain byte-for-byte unchanged; some images therefore remain intentionally.
- `repair-tool-search` removes corrupt `tool_search_call` records with invalid long argument property names and their failed parser outputs.
- `clean` is dry-run by default.
- `repair-tool-search` is dry-run by default.
- `--apply` always refuses to clean/repair an open session file; there is no override.
- Backups are written next to the original session as `.doctor-bak-*`.
- Cleanup preserves JSON `null` values and removes complete image items. Already broken image items require recovery first.
- Cleanup validates all history links before writing. Broken cutoffs must be repaired first; stopping clients alone does not repair them.
- No-op cleanup does not rewrite JSON or create a backup. Linux writes require all Codex clients stopped; do not restart them during maintenance.
- Legacy restore, migration, tool-search removal and record recovery refuse linked/paginated rollouts.

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

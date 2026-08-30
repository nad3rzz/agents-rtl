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

- `clean` removes image payloads only.
- `repair-tool-search` removes corrupt `tool_search_call` records with invalid long argument property names and their failed parser outputs.
- `clean` is dry-run by default.
- `repair-tool-search` is dry-run by default.
- `--apply` refuses to clean/repair an open session file when `lsof` is available.
- Backups are written next to the original session as `.doctor-bak-*`.

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

# ⚡ Codex WebView Performance Workaround

## ✅ Current Workaround

Codex `26.803.61601` repeatedly scans completed turns with heartbeat regexes
during conversation merging. Agents RTL is not the source of this lag.

The active local workaround caches the unchanged completed-turn decision in a
`WeakMap` while preserving the original decision logic.

| Metric | Before | After |
|---|---:|---:|
| ⚙️ Heartbeat detector CPU | ❌ `1187.321ms` | ✅ `4.438ms` |
| ⏱️ Long tasks during the sample | ❌ `15` | ✅ `0` |

## 🛠️ Commands

```bash
cd /home/nad3r/Nad3rCloud/sync/remote/srv/projects/agents-rtl
python3 tools/codex_apply_performance_workarounds.py status --target vscode
python3 tools/codex_apply_performance_workarounds.py apply --target vscode
```

Use `--target antigravity` or `--target all` only when those installed targets
need the same verified patch. Restart the affected Extension Host after `apply`.

The tool:

- ✅ Requires the exact known minified function signature.
- ✅ Requires exactly one supported asset per target.
- ✅ Creates a backup before writing.
- ✅ Verifies the written file after patching.
- ❌ Fails instead of guessing after an incompatible Codex update.

## 🧪 Verification

Profile the WebView before and after applying the patch:

```bash
python3 tools/codex_webview_profiler.py \
  --port PORT \
  --duration-sec 12 \
  --label heartbeat-cache-check \
  --out-dir /home/nad3r/Downloads
```

The diagnosed hotspot is `nOe` inside `app-initial-*.js`. Do not apply a new
patch if a future profile points to a different hotspot.

## 🗃️ Historical Workarounds

These older experiments are intentionally absent from the executable tool. Their
signatures do not apply to Codex `26.803.61601` and must not be re-applied blindly.

| Date | Historical workaround | Old target | Current state |
|---|---|---|---|
| 📅 2026-07-29 | `no_inotify_launcher` | `out/extension.js` | 🗄️ Archived |
| 📅 2026-07-16 | `turn_end_resources` | `local-conversation-thread-*.js` | 🗄️ Archived |
| 📅 2026-06-12 | `app_resolution` | `split-items-into-render-groups-*.js` | 🗄️ Archived |
| 📅 2026-06-12 | `RUST_LOG` change | `out/extension.js` | 🗄️ Archived; unrelated to render lag |

Historical findings:

- `app_resolution` disabled an expensive app/tool resolution function in older
  bundles where it consumed most of the profile window.
- `turn_end_resources` disabled repeated extraction of old turn resources.
- `no_inotify_launcher` experimented with denying inherited `inotify_*` calls.
- `RUST_LOG` only reduced logging and was not a fix for WebView rendering lag.

## ♻️ After A Codex Update

1. Run `status`.
2. If it fails because the signature disappeared, do not patch.
3. Record a new CPU profile.
4. Identify and prove the new hotspot with an A/B test.
5. Update the tool only after behavioral and performance verification.

Backups use this suffix:

```text
.agents-rtl-workaround-bak-YYYYMMDDTHHMMSSZ
```

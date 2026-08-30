#!/usr/bin/env python3
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tqdm import tqdm


DEFAULT_ROOTS = [
    "~/.codex",
    "~/.codex-vscode",
    "~/.codex-antigravity",
]

ROOT_ALIASES = {
    "codex": "~/.codex",
    ".codex": "~/.codex",
    "vscode": "~/.codex-vscode",
    "codex-vscode": "~/.codex-vscode",
    ".codex-vscode": "~/.codex-vscode",
    "antigravity": "~/.codex-antigravity",
    "codex-antigravity": "~/.codex-antigravity",
    ".codex-antigravity": "~/.codex-antigravity",
}

DATA_IMAGE_RX = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
TOOL_SEARCH_ARGUMENT_PROPERTY_NAME_MAX_LENGTH = 256
FAILED_TOOL_SEARCH_ARGUMENTS_OUTPUT_PREFIX = "failed to parse tool_search arguments:"
BACKUP_SUFFIX_MARKERS = [
    ".bak-",
    ".strip-broken-bak-",
    ".strip-inline-dataimage-bak-",
    ".strip-huge-outputs-bak-",
    ".doctor-bak-",
]


def expand_path(path_text):
    return str(Path(path_text).expanduser())


def session_paths_from_root(root):
    root_path = expand_path(root)
    pattern = os.path.join(root_path, "sessions", "**", "*.jsonl")
    return [
        path for path in glob.glob(pattern, recursive=True)
        if os.path.isfile(path)
    ]


def default_session_paths():
    paths = []
    for root in DEFAULT_ROOTS:
        paths.extend(session_paths_from_root(root))
    return sorted(set(paths))


def requested_session_paths(root_args):
    paths = []
    for root_arg in root_args or []:
        root = ROOT_ALIASES.get(root_arg)
        if not root:
            raise SystemExit(f"Unknown root: {root_arg}")
        paths.extend(session_paths_from_root(root))
    return sorted(set(paths))


def require_session_paths(paths):
    if not paths:
        raise SystemExit("No session .jsonl files found.")
    return paths


def choose_session(session_arg):
    if session_arg:
        session_path = expand_path(session_arg)
        if not os.path.isfile(session_path):
            raise SystemExit(f"Session file not found: {session_path}")
        return session_path

    paths = require_session_paths(default_session_paths())
    return max(paths, key=os.path.getmtime)


def choose_sessions(session_arg, all_sessions, root_args):
    if session_arg and (all_sessions or root_args):
        raise SystemExit("Use --session alone, or use --all/--root without --session.")
    if all_sessions and root_args:
        raise SystemExit("Use either --all or --root, not both.")
    if session_arg:
        return [choose_session(session_arg)]
    if root_args:
        return require_session_paths(requested_session_paths(root_args))
    if all_sessions:
        return require_session_paths(default_session_paths())
    return [choose_session(None)]


def get_root_label(path):
    home = str(Path.home())
    normalized = os.path.abspath(path)
    for root in DEFAULT_ROOTS:
        root_path = os.path.abspath(expand_path(root))
        if normalized.startswith(root_path + os.sep):
            return root.replace("~/", "")
    if normalized.startswith(home + os.sep):
        return "~/" + normalized[len(home) + 1:].split(os.sep)[0]
    return "unknown"


def parse_jsonl(path):
    with open(path, encoding="utf-8") as file_obj:
        for line_no, line in enumerate(file_obj, 1):
            try:
                yield line_no, json.loads(line)
            except Exception:
                yield line_no, None


def iter_json_strings(obj):
    stack = [("root", obj)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                stack.append((path + "." + str(key), child))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((path + "[" + str(index) + "]", child))
        elif isinstance(value, str):
            yield path, value


def classify_string(path, value, max_output_bytes):
    if "encrypted_content" in path:
        return "encrypted"
    if value.startswith("data:image/"):
        return "image"
    if ".image_url" in path:
        return "image_url"
    if ".images[" in path:
        return "image"
    if path.endswith(".output") and len(value.encode()) > max_output_bytes:
        return "huge_output"
    return "text"


def build_preview(value):
    return value[:180].replace("\n", "\\n").replace("\t", "\\t")


def sha16(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def analyze_session(path, max_output_bytes):
    rows = []
    totals = {}
    counts = {}
    last_token_usage = None

    for line_no, obj in parse_jsonl(path):
        if obj is None:
            continue

        payload = obj.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("type") == "token_count":
            info = payload.get("info") or {}
            if isinstance(info, dict):
                last_token_usage = info.get("last_token_usage")

        for string_path, value in iter_json_strings(obj):
            value_bytes = len(value.encode())
            kind = classify_string(string_path, value, max_output_bytes)

            totals[kind] = totals.get(kind, 0) + value_bytes
            counts[kind] = counts.get(kind, 0) + 1

            if kind != "text" or value_bytes > max_output_bytes:
                rows.append({
                    "bytes": value_bytes,
                    "mb": value_bytes / 1048576,
                    "line": line_no,
                    "record_type": obj.get("type"),
                    "payload_type": payload.get("type"),
                    "kind": kind,
                    "path": string_path,
                    "sha16": sha16(value),
                    "preview": build_preview(value),
                })

            for match in DATA_IMAGE_RX.finditer(value):
                image_value = match.group(0)
                image_bytes = len(image_value.encode())
                totals["inline_data_image"] = totals.get("inline_data_image", 0) + image_bytes
                counts["inline_data_image"] = counts.get("inline_data_image", 0) + 1
                rows.append({
                    "bytes": image_bytes,
                    "mb": image_bytes / 1048576,
                    "line": line_no,
                    "record_type": obj.get("type"),
                    "payload_type": payload.get("type"),
                    "kind": "inline_data_image",
                    "path": string_path,
                    "sha16": sha16(image_value),
                    "preview": build_preview(image_value),
                })

    rows.sort(key=lambda row: row["bytes"], reverse=True)
    return rows, totals, counts, last_token_usage


def print_session_summary(path, totals, counts, last_token_usage):
    print(f"session: {path}")
    print(f"root: {get_root_label(path)}")
    print(f"file_mb: {os.path.getsize(path) / 1048576:.3f}")

    print("\nkind_totals:")
    for kind in sorted(totals):
        print(f"{kind}\tcount={counts.get(kind, 0)}\tmb={totals[kind] / 1048576:.3f}")

    print("\nlast_token_usage:")
    print(json.dumps(last_token_usage, ensure_ascii=False, indent=2))


def write_tsv(path, rows):
    fieldnames = ["session", "mb", "line", "record_type", "payload_type", "kind", "path", "sha16", "preview"]
    with open(path, "w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, delimiter="	")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "session": row.get("session", ""),
                "mb": round(row["mb"], 6),
                "line": row["line"],
                "record_type": row["record_type"],
                "payload_type": row["payload_type"],
                "kind": row["kind"],
                "path": row["path"],
                "sha16": row["sha16"],
                "preview": row["preview"],
            })


def print_top_rows(rows, top, by_kind):
    if by_kind:
        groups = {}
        for row in rows:
            groups.setdefault(row["kind"], []).append(row)

        for kind in sorted(groups):
            print(f"\n== {kind} ==")
            for row in groups[kind][:top]:
                print_row(row)
        return

    print("\ntop_items:")
    for row in rows[:top]:
        print_row(row)


def print_row(row):
    session_part = ""
    if row.get("session"):
        session_part = f"	{get_root_label(row['session'])}"
    print(
        f"{row['mb']:.3f} MB	line={row['line']}	"
        f"{row['kind']}	{row['record_type']}/{row['payload_type']}	"
        f"{row['path']}	{row['sha16']}{session_part}"
    )


def get_open_session_processes(path):
    try:
        result = subprocess.run(
            ["lsof", path],
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return True, "lsof is not installed; refusing to clean without an exact open-file check."

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode == 1 and not stdout:
        return False, stderr
    if result.returncode not in (0, 1):
        return True, stderr or stdout

    lines = stdout.splitlines()
    if len(lines) <= 1:
        return False, stderr

    return True, stdout


def remove_images_from_structure(value, stats):
    if isinstance(value, list):
        cleaned = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "input_image":
                stats["removed_input_image_items"] += 1
                continue
            if isinstance(item, dict) and item.get("type") == "input_text" and item.get("text") in ("<image>", "</image>"):
                stats["removed_image_text_tags"] += 1
                continue
            if isinstance(item, str) and DATA_IMAGE_RX.search(item):
                stats["removed_image_strings"] += 1
                continue
            cleaned_item = remove_images_from_structure(item, stats)
            if cleaned_item is not None:
                cleaned.append(cleaned_item)
        return cleaned

    if isinstance(value, dict):
        if value.get("type") == "input_image":
            stats["removed_input_image_dicts"] += 1
            return None

        cleaned = {}
        for key, child in value.items():
            if key in ("images", "local_images"):
                if isinstance(child, list):
                    stats["cleared_image_lists"] += len(child)
                else:
                    stats["cleared_image_lists"] += 1
                cleaned[key] = []
                continue

            if key == "image_url":
                stats["removed_image_url_fields"] += 1
                continue

            cleaned_child = remove_images_from_structure(child, stats)
            if cleaned_child is not None:
                cleaned[key] = cleaned_child

        return cleaned

    if isinstance(value, str):
        cleaned_value = DATA_IMAGE_RX.sub("[DATA_IMAGE_REMOVED]", value)
        if cleaned_value != value:
            stats["removed_inline_data_images"] += 1
        return cleaned_value

    return value


def validate_jsonl(path):
    for line_no, obj in parse_jsonl(path):
        if obj is None:
            raise RuntimeError(f"Invalid JSON at line {line_no}: {path}")


def get_passthrough_turn_id(payload):
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    if not isinstance(metadata, dict):
        return None
    turn_id = metadata.get("turn_id")
    if isinstance(turn_id, str) and turn_id:
        return turn_id
    return None


def get_long_tool_search_argument_keys(payload):
    if payload.get("type") != "tool_search_call":
        return []

    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        return []

    return [
        key
        for key in arguments.keys()
        if isinstance(key, str)
        and len(key) > TOOL_SEARCH_ARGUMENT_PROPERTY_NAME_MAX_LENGTH
    ]


def is_broken_tool_search_parse_output(payload, bad_turn_ids):
    if payload.get("type") != "function_call_output":
        return False
    if payload.get("call_id") != "":
        return False
    output = payload.get("output")
    if not isinstance(output, str):
        return False
    if not output.startswith(FAILED_TOOL_SEARCH_ARGUMENTS_OUTPUT_PREFIX):
        return False
    turn_id = get_passthrough_turn_id(payload)
    return turn_id in bad_turn_ids


def calculate_tool_search_repair_plan(path):
    bad_turn_ids = set()
    removals = []
    original_bytes = os.path.getsize(path)
    removed_bytes = 0

    with open(path, encoding="utf-8") as file_obj:
        for line_no, line in enumerate(tqdm(file_obj, desc="scan-tool-search", unit="line"), 1):
            try:
                obj = json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"Invalid JSON at line {line_no}: {path}") from exc

            payload = obj.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}

            long_argument_keys = get_long_tool_search_argument_keys(payload)
            if long_argument_keys:
                turn_id = get_passthrough_turn_id(payload)
                if turn_id is not None:
                    bad_turn_ids.add(turn_id)
                line_bytes = len(line.encode())
                removed_bytes += line_bytes
                removals.append({
                    "line": line_no,
                    "timestamp": obj.get("timestamp"),
                    "record_type": obj.get("type"),
                    "payload_type": payload.get("type"),
                    "id": payload.get("id"),
                    "call_id": payload.get("call_id"),
                    "turn_id": turn_id,
                    "reason": "tool_search_argument_key_too_long",
                    "key_count": len(long_argument_keys),
                    "longest_key_length": max(len(key) for key in long_argument_keys),
                    "bytes": line_bytes,
                })
                continue

            if is_broken_tool_search_parse_output(payload, bad_turn_ids):
                line_bytes = len(line.encode())
                removed_bytes += line_bytes
                removals.append({
                    "line": line_no,
                    "timestamp": obj.get("timestamp"),
                    "record_type": obj.get("type"),
                    "payload_type": payload.get("type"),
                    "id": payload.get("id"),
                    "call_id": payload.get("call_id"),
                    "turn_id": get_passthrough_turn_id(payload),
                    "reason": "broken_tool_search_parse_output",
                    "key_count": 0,
                    "longest_key_length": 0,
                    "bytes": line_bytes,
                })

    return {
        "original_bytes": original_bytes,
        "repaired_bytes": original_bytes - removed_bytes,
        "removed_bytes": removed_bytes,
        "removals": removals,
    }


def print_tool_search_repair_plan(path, plan):
    print(f"session: {path}")
    print(f"original_mb: {plan['original_bytes'] / 1048576:.3f}")
    print(f"estimated_repaired_mb: {plan['repaired_bytes'] / 1048576:.3f}")
    print(f"estimated_removed_mb: {plan['removed_bytes'] / 1048576:.6f}")
    print("\nrepair_stats:")
    print(f"removed_lines: {len(plan['removals'])}")
    reasons = {}
    for removal in plan["removals"]:
        reasons[removal["reason"]] = reasons.get(removal["reason"], 0) + 1
    for reason in sorted(reasons):
        print(f"{reason}: {reasons[reason]}")

    if not plan["removals"]:
        return

    print("\nremovals:")
    for removal in plan["removals"]:
        print(
            f"line={removal['line']}\t"
            f"{removal['record_type']}/{removal['payload_type']}\t"
            f"reason={removal['reason']}\t"
            f"call_id={removal['call_id']}\t"
            f"turn_id={removal['turn_id']}\t"
            f"longest_key_length={removal['longest_key_length']}"
        )


def repair_tool_search_session(path, apply_changes, allow_open_session):
    plan = calculate_tool_search_repair_plan(path)

    if not apply_changes:
        print("mode: dry-run")
        print_tool_search_repair_plan(path, plan)
        print("\nNo files were changed. Re-run with --apply to write changes.")
        return plan

    if not plan["removals"]:
        print("mode: apply")
        print_tool_search_repair_plan(path, plan)
        print("No corrupt tool_search records found. No files were changed.")
        return plan

    is_open, open_process_output = get_open_session_processes(path)
    if is_open and not allow_open_session:
        raise SystemExit(
            "Target session file is open. Close Codex/VSCode/Antigravity before repair.\n"
            + open_process_output
        )
    if is_open:
        print("open_session_override: yes")

    removed_line_numbers = {removal["line"] for removal in plan["removals"]}
    backup = path + ".doctor-tool-search-bak-" + time.strftime("%Y%m%d-%H%M%S")
    tmp = path + ".doctor-tool-search-tmp"

    with open(path, encoding="utf-8") as read_obj, open(tmp, "w", encoding="utf-8") as write_obj:
        for line_no, line in enumerate(tqdm(read_obj, desc="write-tool-search-repair", unit="line"), 1):
            if line_no in removed_line_numbers:
                continue
            write_obj.write(line)

    validate_jsonl(tmp)
    shutil.copy2(path, backup)
    os.replace(tmp, path)

    print("mode: apply")
    print_tool_search_repair_plan(path, plan)
    print(f"backup: {backup}")
    print(f"actual_repaired_mb: {os.path.getsize(path) / 1048576:.3f}")
    return plan


def calculate_clean_plan(path):
    stats = {
        "removed_input_image_items": 0,
        "removed_image_text_tags": 0,
        "removed_image_strings": 0,
        "removed_input_image_dicts": 0,
        "cleared_image_lists": 0,
        "removed_image_url_fields": 0,
        "removed_inline_data_images": 0,
    }
    original_bytes = os.path.getsize(path)
    cleaned_bytes = 0

    for _, obj in parse_jsonl(path):
        if obj is None:
            continue
        obj = remove_images_from_structure(obj, stats)
        cleaned_bytes += len(json.dumps(obj, ensure_ascii=False).encode()) + 1

    return stats, original_bytes, cleaned_bytes


def print_clean_plan(path, stats, original_bytes, cleaned_bytes):
    saved_bytes = max(original_bytes - cleaned_bytes, 0)
    print(f"session: {path}")
    print(f"original_mb: {original_bytes / 1048576:.3f}")
    print(f"estimated_clean_mb: {cleaned_bytes / 1048576:.3f}")
    print(f"estimated_saved_mb: {saved_bytes / 1048576:.3f}")
    print("\nclean_stats:")
    for key in sorted(stats):
        print(f"{key}: {stats[key]}")


def clean_session(path, apply_changes, allow_open_session):
    stats, original_bytes, cleaned_bytes = calculate_clean_plan(path)

    if not apply_changes:
        print("mode: dry-run")
        print_clean_plan(path, stats, original_bytes, cleaned_bytes)
        print("\nNo files were changed. Re-run with --apply to write changes.")
        return

    is_open, open_process_output = get_open_session_processes(path)
    if is_open and not allow_open_session:
        raise SystemExit(
            "Target session file is open. Close Codex/VSCode/Antigravity before clean.\n"
            + open_process_output
        )
    if is_open:
        print("open_session_override: yes")

    backup = path + ".doctor-bak-" + time.strftime("%Y%m%d-%H%M%S")
    tmp = path + ".doctor-tmp"

    with open(path, encoding="utf-8") as read_obj, open(tmp, "w", encoding="utf-8") as write_obj:
        for line in read_obj:
            obj = json.loads(line)
            obj = remove_images_from_structure(obj, stats={key: 0 for key in stats})
            write_obj.write(json.dumps(obj, ensure_ascii=False) + "\n")

    validate_jsonl(tmp)
    shutil.copy2(path, backup)
    os.replace(tmp, path)

    print("mode: apply")
    print_clean_plan(path, stats, original_bytes, cleaned_bytes)
    print(f"backup: {backup}")
    print(f"actual_clean_mb: {os.path.getsize(path) / 1048576:.3f}")


def list_sessions(root_args):
    if root_args:
        paths = require_session_paths(requested_session_paths(root_args))
    else:
        paths = require_session_paths(default_session_paths())
    rows = []
    for path in paths:
        rows.append((
            os.path.getmtime(path),
            os.path.getsize(path) / 1048576,
            get_root_label(path),
            path,
        ))

    rows.sort(reverse=True)
    print("mtime\tmb\troot\tpath")
    for mtime, mb, root, path in rows:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))}\t{mb:.3f}\t{root}\t{path}")


def restore_latest_backup(session_arg):
    if session_arg:
        session_path = expand_path(session_arg)
        backups = glob.glob(session_path + ".*bak-*") + glob.glob(session_path + ".doctor-bak-*")
    else:
        candidates = []
        for session_path in default_session_paths():
            candidates.extend(glob.glob(session_path + ".*bak-*"))
            candidates.extend(glob.glob(session_path + ".doctor-bak-*"))
        backups = candidates

    if not backups:
        raise SystemExit("No backups found.")

    backup = max(backups, key=os.path.getmtime)
    marker_index = backup.find(".jsonl")
    if marker_index == -1:
        raise SystemExit(f"Cannot infer target session from backup: {backup}")

    target = backup[:marker_index + len(".jsonl")]
    shutil.copy2(backup, target)
    print(f"restored: {target}")
    print(f"from: {backup}")


def print_all_sessions_summary(session_summaries, totals, counts):
    print("sessions_summary:")
    print("mb	root	path")
    for item in sorted(session_summaries, key=lambda row: row["file_bytes"], reverse=True):
        print(f"{item['file_bytes'] / 1048576:.3f}	{get_root_label(item['path'])}	{item['path']}")

    print("\nall_kind_totals:")
    for kind in sorted(totals):
        print(f"{kind}	count={counts.get(kind, 0)}	mb={totals[kind] / 1048576:.3f}")


def merge_counter_bytes(target, source):
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def merge_counter_counts(target, source):
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def command_report(args):
    paths = choose_sessions(args.session, args.all, args.root)
    all_rows = []
    all_totals = {}
    all_counts = {}
    session_summaries = []

    for path in paths:
        rows, totals, counts, last_token_usage = analyze_session(path, args.max_output_bytes)
        for row in rows:
            row["session"] = path
        all_rows.extend(rows)
        merge_counter_bytes(all_totals, totals)
        merge_counter_counts(all_counts, counts)
        session_summaries.append({"path": path, "file_bytes": os.path.getsize(path)})

        if not args.all and not args.root:
            print_session_summary(path, totals, counts, last_token_usage)
            print_top_rows(rows, args.top, args.by_kind)

    if args.all or args.root:
        all_rows.sort(key=lambda row: row["bytes"], reverse=True)
        print_all_sessions_summary(session_summaries, all_totals, all_counts)
        print_top_rows(all_rows, args.top, args.by_kind)

    if args.tsv:
        write_tsv(expand_path(args.tsv), all_rows)
        print(f"\ntsv: {expand_path(args.tsv)}")


def command_clean(args):
    paths = choose_sessions(args.session, args.all, args.root)
    if args.apply:
        open_errors = []
        for path in paths:
            is_open, open_process_output = get_open_session_processes(path)
            if is_open:
                open_errors.append(f"{path}\n{open_process_output}")
        if open_errors:
            if not args.allow_open_session:
                raise SystemExit(
                    "Some target session files are open. Close Codex/VSCode/Antigravity before clean.\n\n"
                    + "\n\n".join(open_errors)
                )
            print("WARNING: some target session files are open.\n")
            print("\n\n".join(open_errors))
            if not sys.stdin.isatty():
                raise SystemExit("Refusing open-session clean without an interactive y/N confirmation.")
            answer = input("\nClean open session files anyway? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                raise SystemExit("Aborted.")

    total_original_bytes = 0
    total_cleaned_bytes = 0
    cleaned_sessions = 0

    for path in paths:
        original_bytes = os.path.getsize(path)
        clean_session(path, args.apply, args.allow_open_session)
        total_original_bytes += original_bytes
        if os.path.exists(path):
            total_cleaned_bytes += os.path.getsize(path) if args.apply else calculate_clean_plan(path)[2]
        cleaned_sessions += 1
        print()

    print("summary:")
    print(f"sessions: {cleaned_sessions}")
    print(f"original_mb: {total_original_bytes / 1048576:.3f}")
    clean_label = "actual_clean_mb" if args.apply else "estimated_clean_mb"
    saved_label = "actual_saved_mb" if args.apply else "estimated_saved_mb"
    print(f"{clean_label}: {total_cleaned_bytes / 1048576:.3f}")
    print(f"{saved_label}: {max(total_original_bytes - total_cleaned_bytes, 0) / 1048576:.3f}")


def command_repair_tool_search(args):
    paths = choose_sessions(args.session, args.all, args.root)
    if args.apply:
        open_errors = []
        for path in paths:
            is_open, open_process_output = get_open_session_processes(path)
            if is_open:
                open_errors.append(f"{path}\n{open_process_output}")
        if open_errors:
            if not args.allow_open_session:
                raise SystemExit(
                    "Some target session files are open. Close Codex/VSCode/Antigravity before repair.\n\n"
                    + "\n\n".join(open_errors)
                )
            print("WARNING: some target session files are open.\n")
            print("\n\n".join(open_errors))
            if not sys.stdin.isatty():
                raise SystemExit("Refusing open-session repair without an interactive y/N confirmation.")
            answer = input("\nRepair open session files anyway? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                raise SystemExit("Aborted.")

    total_original_bytes = 0
    total_repaired_bytes = 0
    total_removed_lines = 0

    for path in paths:
        original_bytes = os.path.getsize(path)
        plan = repair_tool_search_session(path, args.apply, args.allow_open_session)
        total_original_bytes += original_bytes
        if os.path.exists(path):
            total_repaired_bytes += os.path.getsize(path) if args.apply else plan["repaired_bytes"]
        total_removed_lines += len(plan["removals"])
        print()

    print("summary:")
    print(f"sessions: {len(paths)}")
    print(f"removed_lines: {total_removed_lines}")
    print(f"original_mb: {total_original_bytes / 1048576:.3f}")
    repair_label = "actual_repaired_mb" if args.apply else "estimated_repaired_mb"
    removed_label = "actual_removed_mb" if args.apply else "estimated_removed_mb"
    print(f"{repair_label}: {total_repaired_bytes / 1048576:.3f}")
    print(f"{removed_label}: {max(total_original_bytes - total_repaired_bytes, 0) / 1048576:.6f}")


def command_list(args):
    list_sessions(args.root)


def print_tokens_for_session(path, max_output_bytes):
    _, _, _, last_token_usage = analyze_session(path, max_output_bytes)
    cached = 0
    input_tokens = 0
    if isinstance(last_token_usage, dict):
        input_tokens = int(last_token_usage.get("input_tokens") or 0)
        cached = int(last_token_usage.get("cached_input_tokens") or 0)
    cache_percent = (cached / input_tokens * 100) if input_tokens else 0

    print(f"session: {path}")
    print(f"file_mb: {os.path.getsize(path) / 1048576:.3f}")
    print(f"input_tokens: {input_tokens}")
    print(f"cached_input_tokens: {cached}")
    print(f"cache_percent: {cache_percent:.2f}")
    print(json.dumps(last_token_usage, ensure_ascii=False, indent=2))


def command_tokens(args):
    paths = choose_sessions(args.session, args.all, args.root)
    total_input_tokens = 0
    total_cached_tokens = 0

    for path in paths:
        _, _, _, last_token_usage = analyze_session(path, args.max_output_bytes)
        if isinstance(last_token_usage, dict):
            total_input_tokens += int(last_token_usage.get("input_tokens") or 0)
            total_cached_tokens += int(last_token_usage.get("cached_input_tokens") or 0)
        print_tokens_for_session(path, args.max_output_bytes)
        print()

    if args.all or args.root:
        cache_percent = (total_cached_tokens / total_input_tokens * 100) if total_input_tokens else 0
        print("summary:")
        print(f"sessions: {len(paths)}")
        print(f"input_tokens: {total_input_tokens}")
        print(f"cached_input_tokens: {total_cached_tokens}")
        print(f"cache_percent: {cache_percent:.2f}")


def command_open_files(args):
    paths = choose_sessions(args.session, args.all, args.root)
    open_count = 0
    for path in paths:
        is_open, output = get_open_session_processes(path)
        print(f"session: {path}")
        if not is_open:
            print("open: no")
            if output:
                print(output)
            print()
            continue
        open_count += 1
        print("open: yes")
        print(output)
        print()

    if args.all or args.root:
        print("summary:")
        print(f"sessions: {len(paths)}")
        print(f"open_sessions: {open_count}")


def command_restore(args):
    restore_latest_backup(args.session)


def add_session_selection_arguments(parser):
    parser.add_argument("--session")
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--root",
        action="append",
        choices=sorted(ROOT_ALIASES),
        help="Limit command to a Codex root. Can be repeated.",
    )


def build_parser():
    parser = argparse.ArgumentParser(prog="codex-session-doctor")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    report = subparsers.add_parser("report")
    add_session_selection_arguments(report)
    report.add_argument("--top", type=int, default=30)
    report.add_argument("--by-kind", action="store_true")
    report.add_argument("--max-output-bytes", type=int, default=20000)
    report.add_argument("--tsv")
    report.set_defaults(func=command_report)

    clean = subparsers.add_parser("clean")
    add_session_selection_arguments(clean)
    clean.add_argument("--apply", action="store_true")
    clean.add_argument("--allow-open-session", action="store_true")
    clean.set_defaults(func=command_clean)

    repair_tool_search = subparsers.add_parser("repair-tool-search")
    add_session_selection_arguments(repair_tool_search)
    repair_tool_search.add_argument("--apply", action="store_true")
    repair_tool_search.add_argument("--allow-open-session", action="store_true")
    repair_tool_search.set_defaults(func=command_repair_tool_search)

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument(
        "--root",
        action="append",
        choices=sorted(ROOT_ALIASES),
        help="Limit list to a Codex root. Can be repeated.",
    )
    list_cmd.set_defaults(func=command_list)

    tokens = subparsers.add_parser("tokens")
    add_session_selection_arguments(tokens)
    tokens.add_argument("--max-output-bytes", type=int, default=20000)
    tokens.set_defaults(func=command_tokens)

    open_files = subparsers.add_parser("open-files")
    add_session_selection_arguments(open_files)
    open_files.set_defaults(func=command_open_files)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--session")
    restore.set_defaults(func=command_restore)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

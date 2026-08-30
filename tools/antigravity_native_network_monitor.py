#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROCESS_PATTERN = "language_server_linux_x64"
DEFAULT_DURATION_SEC = 45.0
DEFAULT_PREPARE_SEC = 3.0
DEFAULT_SAMPLE_SEC = 1.0
DEFAULT_OUTPUT_DIRECTORY = Path.home() / "Downloads"
DEFAULT_WATCH_ROOTS = [
    Path.home() / ".gemini" / "antigravity",
    Path.home() / ".gemini" / "antigravity-ide",
]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
STRACE_SYSCALLS = "read,write,sendto,recvfrom,sendmsg,recvmsg"
STRACE_FILE_SYSCALLS = "openat,openat2,newfstatat,statx,close"
TX_SYSCALLS = {"write", "sendto", "sendmsg"}
RX_SYSCALLS = {"read", "recvfrom", "recvmsg"}
SOCKET_MARKERS = ("<socket:", "socket:[", "<TCP:", "<UDP:", "<UNIX-STREAM:")
LOOPBACK_HOSTS = {"localhost", "ip6-localhost"}


def parse_args():
    parser = argparse.ArgumentParser(
        prog="antigravity-native-network-monitor",
        description="Measure Antigravity native agent network/socket IO and related local conversation file growth.",
    )
    parser.add_argument("--pid", type=int, help="Monitor this exact process id.")
    parser.add_argument("--pattern", default=DEFAULT_PROCESS_PATTERN, help="Process pattern used when --pid is omitted.")
    parser.add_argument("--duration-sec", type=float, default=DEFAULT_DURATION_SEC, help="Measurement duration after SEND_MESSAGE_NOW.")
    parser.add_argument("--prepare-sec", type=float, default=DEFAULT_PREPARE_SEC, help="Countdown before SEND_MESSAGE_NOW.")
    parser.add_argument("--sample-sec", type=float, default=DEFAULT_SAMPLE_SEC, help="Sampling interval.")
    parser.add_argument("--passive", action="store_true", help="Start measuring immediately without SEND_MESSAGE_NOW.")
    parser.add_argument("--trace-sockets", action="store_true", help="Attach strace and estimate socket TX/RX bytes.")
    parser.add_argument("--trace-files", action="store_true", help="Also trace file open/stat/read syscalls for correlation.")
    parser.add_argument("--watch-conversation-id", action="append", default=[], help="Conversation UUID to watch under Antigravity roots.")
    parser.add_argument("--watch-root", action="append", default=[], help="Extra Antigravity storage root.")
    parser.add_argument("--watch-path", action="append", default=[], help="Extra file or directory to watch.")
    parser.add_argument("--out", help="Output JSON report path.")
    parser.add_argument("--no-save", action="store_true", help="Do not write a JSON report.")
    return parser.parse_args()


def timestamp_slug():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z").replace(":", "-").replace(".", "-")


def run_command(command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def require_command(command_name):
    if shutil.which(command_name) is None:
        raise RuntimeError(f"Required command is missing: {command_name}")


def find_pids_by_pattern(pattern):
    result = run_command(["pgrep", "-af", pattern])
    if result.returncode not in (0, 1):
        raise RuntimeError(f"pgrep failed: {result.stderr.strip()}")

    current_pid = os.getpid()
    pids = []
    lines = []
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        command_line = parts[1] if len(parts) > 1 else ""
        if pid == current_pid or "antigravity_native_network_monitor.py" in command_line:
            continue
        pids.append(pid)
        lines.append(line)
    return pids, lines


def validate_pid(pid):
    proc_path = Path("/proc") / str(pid)
    if not proc_path.exists():
        raise RuntimeError(f"Process does not exist: {pid}")
    return pid


def resolve_target_pid(args):
    if args.pid is not None:
        return validate_pid(args.pid), []

    pids, lines = find_pids_by_pattern(args.pattern)
    if len(pids) != 1:
        raise RuntimeError(
            "Expected exactly one process for pattern "
            f"{args.pattern!r}, found {len(pids)}: {lines}"
        )
    return validate_pid(pids[0]), lines


def read_text_file(path):
    return Path(path).read_text(errors="replace")


def read_process_cmdline(pid):
    raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def read_process_status(pid):
    status = read_text_file(f"/proc/{pid}/status")
    result = {}
    for key in ("Name", "State", "VmRSS", "VmSize", "Threads"):
        match = re.search(rf"^{key}:\s*(.+)$", status, re.MULTILINE)
        if match:
            result[key] = match.group(1)
    return result


def read_process_io(pid):
    data = {}
    for line in read_text_file(f"/proc/{pid}/io").splitlines():
        key, value = line.split(":", 1)
        data[key.strip()] = int(value.strip())
    return data


def read_network_interfaces():
    data = {}
    lines = read_text_file("/proc/net/dev").splitlines()[2:]
    for line in lines:
        interface, values = line.split(":", 1)
        fields = values.split()
        data[interface.strip()] = {
            "rx_bytes": int(fields[0]),
            "tx_bytes": int(fields[8]),
        }
    return data


def get_tcp_connections_for_pid(pid):
    result = run_command(["ss", "-tnp"])
    if result.returncode != 0:
        raise RuntimeError(f"ss failed: {result.stderr.strip()}")
    needle = f"pid={pid},"
    return [line for line in result.stdout.splitlines() if needle in line]


def build_watch_paths(args):
    paths = []
    roots = [*DEFAULT_WATCH_ROOTS, *[Path(path).expanduser() for path in args.watch_root]]
    for conversation_id in args.watch_conversation_id:
        for root in roots:
            paths.append(root / "conversations" / f"{conversation_id}.pb")
            paths.append(root / "brain" / conversation_id)
            paths.append(root / "annotations" / f"{conversation_id}.pbtxt")
    paths.extend(Path(path).expanduser() for path in args.watch_path)
    unique_paths = []
    seen = set()
    for path in paths:
        resolved = str(path)
        if resolved not in seen:
            unique_paths.append(path)
            seen.add(resolved)
    return unique_paths


def snapshot_file(path):
    stat = path.stat()
    return {
        "exists": True,
        "kind": "file",
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "file_count": 1,
        "image_count": 1 if path.suffix.lower() in IMAGE_SUFFIXES else 0,
        "image_bytes": stat.st_size if path.suffix.lower() in IMAGE_SUFFIXES else 0,
    }


def snapshot_directory(path):
    total_bytes = 0
    file_count = 0
    image_count = 0
    image_bytes = 0
    newest_mtime_ns = 0
    largest_files = []
    for root, _, filenames in os.walk(path):
        for filename in filenames:
            file_path = Path(root) / filename
            stat = file_path.stat()
            file_count += 1
            total_bytes += stat.st_size
            newest_mtime_ns = max(newest_mtime_ns, stat.st_mtime_ns)
            if file_path.suffix.lower() in IMAGE_SUFFIXES:
                image_count += 1
                image_bytes += stat.st_size
            largest_files.append({"path": str(file_path), "bytes": stat.st_size})
    largest_files.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "exists": True,
        "kind": "directory",
        "bytes": total_bytes,
        "mtime_ns": newest_mtime_ns,
        "file_count": file_count,
        "image_count": image_count,
        "image_bytes": image_bytes,
        "largest_files": largest_files[:10],
    }


def snapshot_path(path):
    if not path.exists():
        return {"exists": False, "kind": "missing", "bytes": 0, "file_count": 0, "image_count": 0, "image_bytes": 0}
    if path.is_file():
        return snapshot_file(path)
    if path.is_dir():
        return snapshot_directory(path)
    raise RuntimeError(f"Unsupported path type: {path}")


def snapshot_paths(paths):
    return {str(path): snapshot_path(path) for path in paths}


def diff_number(end, start, key):
    return int(end.get(key, 0)) - int(start.get(key, 0))


def diff_snapshots(start, end):
    result = {}
    for path in sorted(set(start) | set(end)):
        before = start.get(path, {"bytes": 0, "file_count": 0, "image_count": 0, "image_bytes": 0})
        after = end.get(path, {"bytes": 0, "file_count": 0, "image_count": 0, "image_bytes": 0})
        result[path] = {
            "bytes_delta": diff_number(after, before, "bytes"),
            "file_count_delta": diff_number(after, before, "file_count"),
            "image_count_delta": diff_number(after, before, "image_count"),
            "image_bytes_delta": diff_number(after, before, "image_bytes"),
            "before": before,
            "after": after,
        }
    return result


def build_strace_syscalls(trace_files):
    if trace_files:
        return f"{STRACE_SYSCALLS},{STRACE_FILE_SYSCALLS}"
    return STRACE_SYSCALLS


def start_strace(pid, output_path, trace_files):
    require_command("strace")
    command = [
        "strace",
        "-f",
        "-tt",
        "-s",
        "0",
        "-yy",
        "-e",
        f"trace={build_strace_syscalls(trace_files)}",
        "-p",
        str(pid),
        "-o",
        str(output_path),
    ]
    process = subprocess.Popen(command, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(1.0)
    if process.poll() is not None:
        stderr = process.stderr.read() if process.stderr else ""
        raise RuntimeError(f"strace exited early: {stderr.strip()}")
    return process


def stop_strace(process):
    if process is None:
        return
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def line_has_socket_marker(line):
    return any(marker in line for marker in SOCKET_MARKERS)


def parse_strace_return_bytes(line):
    match = re.search(r"\)\s+=\s+(\d+)(?:\s|$)", line)
    if not match:
        return None
    return int(match.group(1))


def parse_socket_descriptor(line):
    match = re.search(r"<(TCP|UDP):\[([^\]]+)\]>", line)
    if match:
        protocol = match.group(1)
        endpoint = match.group(2)
        return {
            "protocol": protocol,
            "endpoint": endpoint,
            "category": classify_network_endpoint(endpoint),
        }
    if "<UNIX-STREAM:" in line:
        return {
            "protocol": "UNIX-STREAM",
            "endpoint": "unix-stream",
            "category": "local_ipc",
        }
    if "<socket:" in line or "socket:[" in line:
        return {
            "protocol": "socket",
            "endpoint": "unknown-socket",
            "category": "unknown_socket",
        }
    return {
        "protocol": "unknown",
        "endpoint": "unknown",
        "category": "unknown_socket",
    }


def classify_network_endpoint(endpoint):
    if "127.0.0.1" in endpoint or "::1" in endpoint or "localhost" in endpoint:
        return "loopback"
    if "->" not in endpoint:
        return "unknown_socket"
    remote_side = endpoint.rsplit("->", 1)[1]
    remote_host = parse_socket_host(remote_side)
    if remote_host is None:
        return "unknown_socket"
    if is_loopback_host(remote_host):
        return "loopback"
    if is_private_network_host(remote_host):
        return "local_network"
    return "external"


def parse_socket_host(socket_side):
    value = socket_side.strip()
    if value.startswith("["):
        match = re.match(r"\[([^\]]+)\]", value)
        return match.group(1) if match else None
    if ":" not in value:
        return value or None
    return value.rsplit(":", 1)[0] or None


def is_loopback_host(host):
    normalized = host.strip().lower()
    if normalized in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_private_network_host(host):
    normalized = host.strip().lower()
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_private or ip.is_link_local


def parse_strace_syscall(line):
    match = re.search(r"(?:^\d+\s+)?\d\d:\d\d:\d\d\.\d+\s+([a-zA-Z_][a-zA-Z0-9_]*)\(", line)
    if match:
        return match.group(1)
    match = re.search(r"\]\s+\d\d:\d\d:\d\d\.\d+\s+([a-zA-Z_][a-zA-Z0-9_]*)\(", line)
    if match:
        return match.group(1)
    return None


def parse_strace_socket_bytes(path):
    if not path or not path.exists():
        return {"enabled": False}

    return parse_strace_lines_socket_bytes(path.read_text(errors="replace").splitlines(), include_samples=True)


def empty_socket_summary(include_samples):
    summary = {
        "enabled": True,
        "socket_tx_bytes": 0,
        "socket_rx_bytes": 0,
        "socket_tx_calls": 0,
        "socket_rx_calls": 0,
        "external_socket_tx_bytes": 0,
        "external_socket_rx_bytes": 0,
        "external_socket_tx_calls": 0,
        "external_socket_rx_calls": 0,
        "loopback_socket_tx_bytes": 0,
        "loopback_socket_rx_bytes": 0,
        "loopback_socket_tx_calls": 0,
        "loopback_socket_rx_calls": 0,
        "by_syscall": {},
        "by_socket_category": {},
        "by_endpoint": {},
    }
    if include_samples:
        summary["sample_lines"] = []
    return summary


def empty_socket_counter():
    return {
        "tx_bytes": 0,
        "rx_bytes": 0,
        "tx_calls": 0,
        "rx_calls": 0,
    }


def parse_strace_lines_socket_bytes(lines, include_samples):
    summary = empty_socket_summary(include_samples)
    for line in lines:
        add_strace_line_socket_bytes(summary, line, include_samples)
    return summary


def add_strace_line_socket_bytes(summary, line, include_samples):
    if not line_has_socket_marker(line):
        return
    syscall = parse_strace_syscall(line)
    byte_count = parse_strace_return_bytes(line)
    if syscall is None or byte_count is None:
        return
    by_syscall = summary["by_syscall"].setdefault(syscall, {"calls": 0, "bytes": 0})
    by_syscall["calls"] += 1
    by_syscall["bytes"] += byte_count
    socket_descriptor = parse_socket_descriptor(line)
    category = socket_descriptor["category"]
    endpoint = f"{socket_descriptor['protocol']} {socket_descriptor['endpoint']}"
    category_summary = summary["by_socket_category"].setdefault(category, empty_socket_counter())
    endpoint_summary = summary["by_endpoint"].setdefault(endpoint, empty_socket_counter())
    if syscall in TX_SYSCALLS:
        summary["socket_tx_calls"] += 1
        summary["socket_tx_bytes"] += byte_count
        category_summary["tx_calls"] += 1
        category_summary["tx_bytes"] += byte_count
        endpoint_summary["tx_calls"] += 1
        endpoint_summary["tx_bytes"] += byte_count
        if category == "external":
            summary["external_socket_tx_calls"] += 1
            summary["external_socket_tx_bytes"] += byte_count
        elif category == "loopback":
            summary["loopback_socket_tx_calls"] += 1
            summary["loopback_socket_tx_bytes"] += byte_count
    elif syscall in RX_SYSCALLS:
        summary["socket_rx_calls"] += 1
        summary["socket_rx_bytes"] += byte_count
        category_summary["rx_calls"] += 1
        category_summary["rx_bytes"] += byte_count
        endpoint_summary["rx_calls"] += 1
        endpoint_summary["rx_bytes"] += byte_count
        if category == "external":
            summary["external_socket_rx_calls"] += 1
            summary["external_socket_rx_bytes"] += byte_count
        elif category == "loopback":
            summary["loopback_socket_rx_calls"] += 1
            summary["loopback_socket_rx_bytes"] += byte_count
    if include_samples and len(summary["sample_lines"]) < 20:
        summary["sample_lines"].append(line[:500])


def read_new_strace_lines(path, offset, partial):
    if not path or not path.exists():
        return [], offset, partial
    with path.open("r", errors="replace") as file:
        file.seek(offset)
        chunk = file.read()
        offset = file.tell()
    if not chunk:
        return [], offset, partial
    text = partial + chunk
    if text.endswith("\n"):
        return text.splitlines(), offset, ""
    lines = text.splitlines()
    if not lines:
        return [], offset, text
    return lines[:-1], offset, lines[-1]


def find_file_trace_lines(lines, watch_paths, watch_ids):
    needles = [str(path) for path in watch_paths]
    needles.extend(watch_ids)
    matches = []
    for line in lines:
        if any(needle and needle in line for needle in needles):
            matches.append(line[:500])
        if len(matches) >= 20:
            break
    return matches


def merge_socket_summaries(total, delta):
    total["socket_tx_bytes"] += delta["socket_tx_bytes"]
    total["socket_rx_bytes"] += delta["socket_rx_bytes"]
    total["socket_tx_calls"] += delta["socket_tx_calls"]
    total["socket_rx_calls"] += delta["socket_rx_calls"]
    total["external_socket_tx_bytes"] += delta["external_socket_tx_bytes"]
    total["external_socket_rx_bytes"] += delta["external_socket_rx_bytes"]
    total["external_socket_tx_calls"] += delta["external_socket_tx_calls"]
    total["external_socket_rx_calls"] += delta["external_socket_rx_calls"]
    total["loopback_socket_tx_bytes"] += delta["loopback_socket_tx_bytes"]
    total["loopback_socket_rx_bytes"] += delta["loopback_socket_rx_bytes"]
    total["loopback_socket_tx_calls"] += delta["loopback_socket_tx_calls"]
    total["loopback_socket_rx_calls"] += delta["loopback_socket_rx_calls"]
    for syscall, values in delta["by_syscall"].items():
        target = total["by_syscall"].setdefault(syscall, {"calls": 0, "bytes": 0})
        target["calls"] += values["calls"]
        target["bytes"] += values["bytes"]
    merge_socket_counter_maps(total["by_socket_category"], delta["by_socket_category"])
    merge_socket_counter_maps(total["by_endpoint"], delta["by_endpoint"])


def merge_socket_counter_maps(total, delta):
    for key, values in delta.items():
        target = total.setdefault(key, empty_socket_counter())
        target["tx_bytes"] += values["tx_bytes"]
        target["rx_bytes"] += values["rx_bytes"]
        target["tx_calls"] += values["tx_calls"]
        target["rx_calls"] += values["rx_calls"]


def socket_rates(delta, sample_seconds):
    return {
        "socket_tx_bytes_per_sec": round(delta["socket_tx_bytes"] / sample_seconds, 2),
        "socket_rx_bytes_per_sec": round(delta["socket_rx_bytes"] / sample_seconds, 2),
        "external_socket_tx_bytes_per_sec": round(delta["external_socket_tx_bytes"] / sample_seconds, 2),
        "external_socket_rx_bytes_per_sec": round(delta["external_socket_rx_bytes"] / sample_seconds, 2),
        "loopback_socket_tx_bytes_per_sec": round(delta["loopback_socket_tx_bytes"] / sample_seconds, 2),
        "loopback_socket_rx_bytes_per_sec": round(delta["loopback_socket_rx_bytes"] / sample_seconds, 2),
    }


def compute_net_delta(start, end):
    result = {}
    for interface in sorted(set(start) | set(end)):
        before = start.get(interface, {"rx_bytes": 0, "tx_bytes": 0})
        after = end.get(interface, {"rx_bytes": 0, "tx_bytes": 0})
        result[interface] = {
            "rx_bytes_delta": diff_number(after, before, "rx_bytes"),
            "tx_bytes_delta": diff_number(after, before, "tx_bytes"),
        }
    return result


def compute_io_delta(start, end):
    return {
        "read_bytes_delta": diff_number(end, start, "read_bytes"),
        "write_bytes_delta": diff_number(end, start, "write_bytes"),
        "syscr_delta": diff_number(end, start, "syscr"),
        "syscw_delta": diff_number(end, start, "syscw"),
        "rchar_delta": diff_number(end, start, "rchar"),
        "wchar_delta": diff_number(end, start, "wchar"),
    }


def default_output_path():
    return DEFAULT_OUTPUT_DIRECTORY / f"antigravity-native-net-monitor-{timestamp_slug()}.json"


def print_json(label, payload):
    print(label, json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def countdown(seconds):
    remaining = int(seconds)
    while remaining > 0:
        print_json("PREPARE", {"remaining_sec": remaining})
        time.sleep(1)
        remaining -= 1
    fractional = seconds - int(seconds)
    if fractional > 0:
        time.sleep(fractional)


def run_monitor(args):
    pid, matching_processes = resolve_target_pid(args)
    watch_paths = build_watch_paths(args)
    output_path = None if args.no_save else Path(args.out).expanduser() if args.out else default_output_path()
    strace_path = output_path.with_suffix(".strace.log") if output_path and args.trace_sockets else None

    target = {
        "pid": pid,
        "cmdline": read_process_cmdline(pid),
        "status": read_process_status(pid),
        "matching_processes": matching_processes,
        "tcp_connections": get_tcp_connections_for_pid(pid),
        "watch_paths": [str(path) for path in watch_paths],
        "trace_sockets": args.trace_sockets,
        "trace_files": args.trace_files,
        "mode": "passive" if args.passive else "prompt",
    }
    print_json("MONITOR_TARGET", target)

    strace_process = None
    if args.trace_sockets:
        strace_process = start_strace(pid, strace_path, args.trace_files)
        print_json("STRACE_STARTED", {"path": str(strace_path)})

    if args.passive:
        print("PASSIVE_MONITOR_STARTED", flush=True)
    else:
        countdown(args.prepare_sec)
        print("SEND_MESSAGE_NOW", flush=True)

    start_time = time.time()
    start_io = read_process_io(pid)
    start_status = read_process_status(pid)
    start_net = read_network_interfaces()
    start_files = snapshot_paths(watch_paths)

    samples = []
    previous_io = start_io
    total_socket_summary = empty_socket_summary(include_samples=False)
    strace_offset = 0
    strace_partial = ""
    file_trace_samples = []
    while time.time() - start_time < args.duration_sec:
        time.sleep(args.sample_sec)
        current_io = read_process_io(pid)
        socket_delta = {"enabled": False}
        new_strace_lines = []
        if args.trace_sockets and strace_path is not None:
            new_strace_lines, strace_offset, strace_partial = read_new_strace_lines(strace_path, strace_offset, strace_partial)
            socket_delta = parse_strace_lines_socket_bytes(new_strace_lines, include_samples=False)
            merge_socket_summaries(total_socket_summary, socket_delta)
            if args.trace_files:
                file_trace_samples.extend(find_file_trace_lines(new_strace_lines, watch_paths, args.watch_conversation_id))
                file_trace_samples = file_trace_samples[:50]
        sample = {
            "elapsed_sec": round(time.time() - start_time, 3),
            "io_delta_since_previous": compute_io_delta(previous_io, current_io),
            "socket_delta_since_previous": socket_delta,
            "socket_rate_since_previous": socket_rates(socket_delta, args.sample_sec) if socket_delta.get("enabled") else {"enabled": False},
            "status": read_process_status(pid),
        }
        samples.append(sample)
        print_json("SAMPLE", sample)
        previous_io = current_io

    end_io = read_process_io(pid)
    end_status = read_process_status(pid)
    end_net = read_network_interfaces()
    end_files = snapshot_paths(watch_paths)
    stop_strace(strace_process)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "duration_sec": args.duration_sec,
        "prepare_sec": args.prepare_sec,
        "start_status": start_status,
        "end_status": end_status,
        "process_io_delta": compute_io_delta(start_io, end_io),
        "network_interface_delta": compute_net_delta(start_net, end_net),
        "watched_file_delta": diff_snapshots(start_files, end_files),
        "socket_trace": parse_strace_socket_bytes(strace_path),
        "live_socket_trace": total_socket_summary if args.trace_sockets else {"enabled": False},
        "file_trace_samples": file_trace_samples,
        "samples": samples,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        report["report_path"] = str(output_path)
        if strace_path is not None:
            report["strace_path"] = str(strace_path)

    print_json("RESULT", {
        "report_path": report.get("report_path"),
        "strace_path": report.get("strace_path"),
        "process_io_delta": report["process_io_delta"],
        "network_interface_delta": report["network_interface_delta"],
        "watched_file_delta": report["watched_file_delta"],
        "socket_trace": report["socket_trace"],
        "live_socket_trace": report["live_socket_trace"],
        "file_trace_samples": report["file_trace_samples"],
    })


def main():
    args = parse_args()
    if args.duration_sec <= 0:
        raise RuntimeError("--duration-sec must be positive.")
    if args.prepare_sec < 0:
        raise RuntimeError("--prepare-sec must not be negative.")
    if args.sample_sec <= 0:
        raise RuntimeError("--sample-sec must be positive.")
    if args.trace_files and not args.trace_sockets:
        raise RuntimeError("--trace-files requires --trace-sockets.")
    run_monitor(args)


if __name__ == "__main__":
    main()

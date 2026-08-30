#!/usr/bin/env python3
import argparse
import base64
import json
import os
import secrets
import socket
import struct
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_TARGET_MARKER = "extensionId=openai.chatgpt"
DEFAULT_WRAPPED_FUNCTIONS = [
    "apply",
    "renderCodexChatTabs",
    "updateCodexConversations",
    "applyCodexConversationListRenameControls",
    "installControlButtons",
    "syncScrollButtons",
]


def parse_args():
    parser = argparse.ArgumentParser(
        prog="codex-webview-profiler",
        description="Record lightweight and CPU profiles from a Codex VS Code-compatible WebView.",
    )
    parser.add_argument("--port", type=int, required=True, help="Explicit port for the active DevTools endpoint.")
    parser.add_argument("--duration-sec", type=float, default=45, help="Recording duration in seconds.")
    parser.add_argument("--label", default="codex-webview", help="Output filename label.")
    parser.add_argument("--out-dir", default=str(Path.home() / "Downloads"), help="Output directory.")
    parser.add_argument("--target-marker", default=DEFAULT_TARGET_MARKER, help="Substring used to find the target URL.")
    parser.add_argument("--cpu", action=argparse.BooleanOptionalAction, default=True, help="Record CPU profile.")
    parser.add_argument("--light", action=argparse.BooleanOptionalAction, default=True, help="Record lightweight browser metrics.")
    parser.add_argument("--sampling-interval-us", type=int, default=100, help="CPU profiler sampling interval in microseconds.")
    return parser.parse_args()


def timestamp_slug():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z").replace(":", "-").replace(".", "-")


def read_json_url(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def find_target(port, target_marker):
    targets = read_json_url(f"http://127.0.0.1:{port}/json/list")
    for target in targets:
        if target.get("webSocketDebuggerUrl") and target_marker in target.get("url", ""):
            return target
    target_summaries = [
        {"type": target.get("type"), "title": target.get("title"), "url": target.get("url")}
        for target in targets
    ]
    raise RuntimeError(f"No DevTools target matched {target_marker!r} on port {port}: {target_summaries}")


def websocket_accept_key(key):
    import hashlib

    digest = hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def connect_websocket(websocket_url):
    parsed_url = urlparse(websocket_url)
    if parsed_url.scheme != "ws":
        raise RuntimeError(f"Unsupported WebSocket URL scheme: {websocket_url}")

    host = parsed_url.hostname or "127.0.0.1"
    port = parsed_url.port
    path = parsed_url.path
    if parsed_url.query:
        path += "?" + parsed_url.query

    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=5)
    request = "\r\n".join(
        [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            "",
            "",
        ]
    )
    sock.sendall(request.encode("ascii"))
    response = read_until(sock, b"\r\n\r\n")
    head = response.decode("iso-8859-1", errors="replace")
    if not head.startswith("HTTP/1.1 101"):
        raise RuntimeError(f"WebSocket handshake failed: {head.splitlines()[0] if head else head}")
    expected_accept = websocket_accept_key(key)
    if expected_accept not in head:
        raise RuntimeError("WebSocket handshake did not include the expected accept key.")
    sock.settimeout(10)
    return sock


def read_until(sock, marker):
    chunks = []
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("Socket closed during read.")
        chunks.append(chunk)
        data = b"".join(chunks)
    return data


def encode_websocket_frame(payload):
    payload_bytes = payload.encode("utf-8")
    mask = secrets.token_bytes(4)
    length = len(payload_bytes)
    if length < 126:
        header = bytes([0x81, 0x80 | length])
    elif length < 65536:
        header = bytes([0x81, 0x80 | 126]) + struct.pack("!H", length)
    else:
        header = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", length)
    masked_payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload_bytes))
    return header + mask + masked_payload


def read_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise RuntimeError("Socket closed during frame read.")
        data += chunk
    return data


def read_websocket_message(sock):
    first_two = read_exact(sock, 2)
    first_byte, second_byte = first_two
    opcode = first_byte & 0x0F
    length = second_byte & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(sock, 8))[0]

    mask = read_exact(sock, 4) if second_byte & 0x80 else b""
    payload = read_exact(sock, length)
    if mask:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    if opcode == 8:
        raise RuntimeError("WebSocket closed.")
    if opcode != 1:
        return None
    return json.loads(payload.decode("utf-8"))


def send_command(sock, next_id, method, params=None):
    payload = {"id": next_id, "method": method, "params": params or {}}
    sock.sendall(encode_websocket_frame(json.dumps(payload, separators=(",", ":"))))
    return next_id + 1


def wait_for_response(sock, command_id, events):
    while True:
        message = read_websocket_message(sock)
        if message is None:
            continue
        if message.get("id") == command_id:
            return message
        if "method" in message:
            events.append(message)


def command(sock, next_id, events, method, params=None):
    command_id = next_id
    next_id = send_command(sock, next_id, method, params)
    response = wait_for_response(sock, command_id, events)
    if response.get("error"):
        raise RuntimeError(f"CDP command {method} failed: {response['error']}")
    return next_id, response.get("result", {})


def expression_json(value):
    return json.dumps(value, separators=(",", ":"))


def light_probe_expression(function_names):
    function_names_json = expression_json(function_names)
    return f"""(() => {{
  const KEY = "__agentsRtlPerfProbe";
  if (window[KEY]?.stop) window[KEY].stop();
  const state = {{
    startedAt: new Date().toISOString(),
    href: location.href,
    hasAgentsRtl: Boolean(window.__agentsRtl),
    agentsRtlVersion: window.__agentsRtl?.version || null,
    longTasks: [],
    rafStalls: [],
    intervalStalls: [],
    mutationBatches: [],
    samples: [],
    agentsRtlCalls: {{}},
    wrappedFunctions: [],
    errors: []
  }};
  const cleanup = [];
  const wrapped = [];
  const now = () => Math.round(performance.now());
  try {{
    const performanceObserver = new PerformanceObserver((list) => {{
      for (const entry of list.getEntries()) {{
        state.longTasks.push({{
          start: Math.round(entry.startTime),
          duration: Math.round(entry.duration),
          name: entry.name
        }});
      }}
    }});
    performanceObserver.observe({{ entryTypes: ["longtask"] }});
    cleanup.push(() => performanceObserver.disconnect());
  }} catch (error) {{
    state.errors.push("longtask: " + error.message);
  }}
  let previousIntervalTime = performance.now();
  const intervalId = setInterval(() => {{
    const currentTime = performance.now();
    const lag = currentTime - previousIntervalTime - 250;
    if (lag > 80) state.intervalStalls.push({{ at: now(), lag: Math.round(lag) }});
    previousIntervalTime = currentTime;
  }}, 250);
  cleanup.push(() => clearInterval(intervalId));
  let previousFrameTime = performance.now();
  let rafId = 0;
  const rafLoop = (frameTime) => {{
    const gap = frameTime - previousFrameTime;
    if (gap > 120) state.rafStalls.push({{ at: Math.round(frameTime), gap: Math.round(gap) }});
    previousFrameTime = frameTime;
    rafId = requestAnimationFrame(rafLoop);
  }};
  rafId = requestAnimationFrame(rafLoop);
  cleanup.push(() => cancelAnimationFrame(rafId));
  try {{
    let mutationCount = 0;
    const mutationObserver = new MutationObserver((mutations) => {{ mutationCount += mutations.length; }});
    mutationObserver.observe(document.body, {{ subtree: true, childList: true, attributes: true, characterData: true }});
    const mutationIntervalId = setInterval(() => {{
      if (mutationCount > 0) state.mutationBatches.push({{ at: now(), count: mutationCount }});
      mutationCount = 0;
    }}, 1000);
    cleanup.push(() => mutationObserver.disconnect());
    cleanup.push(() => clearInterval(mutationIntervalId));
  }} catch (error) {{
    state.errors.push("mutation: " + error.message);
  }}
  const sampleIntervalId = setInterval(() => {{
    state.samples.push({{
      at: now(),
      bodyTextLength: document.body?.innerText?.length || 0,
      nodeCount: document.querySelectorAll("*").length,
      agentsRtlElements: document.querySelectorAll("[id^='agents-rtl'],[class*='agents-rtl']").length,
      tabsText: document.querySelector("#agents-rtl-codex-chat-tabs")?.innerText || ""
    }});
  }}, 1000);
  cleanup.push(() => clearInterval(sampleIntervalId));
  const wrapFunction = (object, key, label) => {{
    if (!object || typeof object[key] !== "function") return;
    const original = object[key];
    if (original.__agentsRtlPerfWrapped) return;
    const wrappedFunction = function(...args) {{
      const startedAt = performance.now();
      try {{
        return original.apply(this, args);
      }} finally {{
        const duration = performance.now() - startedAt;
        const bucket = state.agentsRtlCalls[label] || {{ count: 0, totalMs: 0, maxMs: 0, slowCalls: [] }};
        bucket.count += 1;
        bucket.totalMs += duration;
        bucket.maxMs = Math.max(bucket.maxMs, duration);
        if (duration > 20) bucket.slowCalls.push({{ at: now(), duration: Math.round(duration) }});
        state.agentsRtlCalls[label] = bucket;
      }}
    }};
    wrappedFunction.__agentsRtlPerfWrapped = true;
    object[key] = wrappedFunction;
    wrapped.push(() => {{ object[key] = original; }});
    state.wrappedFunctions.push(label);
  }};
  {function_names_json}.forEach((name) => wrapFunction(window.__agentsRtl, name, "window.__agentsRtl." + name));
  window[KEY] = {{
    state,
    stop: () => {{
      for (const fn of cleanup.splice(0)) {{
        try {{ fn(); }} catch (error) {{ state.errors.push("cleanup: " + error.message); }}
      }}
      for (const fn of wrapped.splice(0)) {{
        try {{ fn(); }} catch (error) {{ state.errors.push("unwrap: " + error.message); }}
      }}
      state.endedAt = new Date().toISOString();
      state.longTaskTotalMs = state.longTasks.reduce((total, task) => total + task.duration, 0);
      state.maxLongTaskMs = Math.max(0, ...state.longTasks.map((task) => task.duration));
      state.maxIntervalLagMs = Math.max(0, ...state.intervalStalls.map((stall) => stall.lag));
      state.maxRafGapMs = Math.max(0, ...state.rafStalls.map((stall) => stall.gap));
      window[KEY] = null;
      return state;
    }}
  }};
  return {{
    installed: true,
    hasAgentsRtl: state.hasAgentsRtl,
    agentsRtlVersion: state.agentsRtlVersion,
    wrappedFunctions: state.wrappedFunctions
  }};
}})()"""


def evaluate_expression(sock, next_id, events, context_id, expression):
    params = {
        "contextId": context_id,
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    }
    next_id, result = command(sock, next_id, events, "Runtime.evaluate", params)
    if result.get("exceptionDetails"):
        raise RuntimeError(f"Evaluation failed: {result['exceptionDetails']}")
    return next_id, result.get("result", {}).get("value")


def collect_runtime_contexts(sock, next_id, events):
    next_id, _ = command(sock, next_id, events, "Runtime.enable")
    time.sleep(0.8)
    contexts = []
    for event in events:
        if event.get("method") != "Runtime.executionContextCreated":
            continue
        context = event.get("params", {}).get("context")
        if context:
            contexts.append(context)
    return next_id, contexts


def select_content_context(sock, next_id, events, contexts):
    probe = "(() => ({ bodyLen: document.body?.innerText?.length || 0, hasAgentsRtl: !!window.__agentsRtl }))()"
    selected_context = None
    selected_value = None
    for context in contexts:
        next_id, value = evaluate_expression(sock, next_id, events, context["id"], probe)
        if value and value.get("bodyLen", 0) > 0:
            selected_context = context
            selected_value = value
    if not selected_context:
        raise RuntimeError("Could not find a content execution context with non-empty body text.")
    return next_id, selected_context, selected_value


def ensure_output_dir(output_dir):
    path = Path(output_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_paths(args):
    output_dir = ensure_output_dir(args.out_dir)
    slug = timestamp_slug()
    label = args.label.replace("/", "-").replace(" ", "-")
    return {
        "light": output_dir / f"{label}-light-{slug}.json",
        "cpu": output_dir / f"{label}-cpu-{slug}.cpuprofile",
    }


def stop_light_probe(sock, next_id, events, context_id):
    expression = "window.__agentsRtlPerfProbe.stop()"
    return evaluate_expression(sock, next_id, events, context_id, expression)


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def print_summary(light_result, light_path, cpu_path, cpu_enabled):
    summary = {
        "lightProfile": str(light_path) if light_path else None,
        "cpuProfile": str(cpu_path) if cpu_enabled else None,
        "longTasks": len(light_result.get("longTasks", [])) if light_result else None,
        "totalLongTaskMs": light_result.get("longTaskTotalMs") if light_result else None,
        "maxLongTaskMs": light_result.get("maxLongTaskMs") if light_result else None,
        "maxIntervalLagMs": light_result.get("maxIntervalLagMs") if light_result else None,
        "maxRafGapMs": light_result.get("maxRafGapMs") if light_result else None,
        "agentsRtlCalls": light_result.get("agentsRtlCalls") if light_result else None,
    }
    print("PROFILE_DONE " + json.dumps(summary, ensure_ascii=False))


def run_profile(args):
    target = find_target(args.port, args.target_marker)
    paths = output_paths(args)
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    try:
        next_id, contexts = collect_runtime_contexts(sock, next_id, events)
        next_id, context, selected_value = select_content_context(sock, next_id, events, contexts)

        light_result = None
        light_path = None
        if args.light:
            expression = light_probe_expression(DEFAULT_WRAPPED_FUNCTIONS)
            next_id, install_value = evaluate_expression(sock, next_id, events, context["id"], expression)
            print("LIGHT_PROBE " + json.dumps(install_value, ensure_ascii=False))

        if args.cpu:
            next_id, _ = command(sock, next_id, events, "Profiler.enable")
            next_id, _ = command(sock, next_id, events, "Profiler.setSamplingInterval", {"interval": args.sampling_interval_us})
            next_id, _ = command(sock, next_id, events, "Profiler.start")

        print(
            "PROFILE_STARTED "
            + json.dumps(
                {
                    "port": args.port,
                    "target": target.get("title") or target.get("url"),
                    "contextId": context["id"],
                    "contentProbe": selected_value,
                    "durationSec": args.duration_sec,
                    "lightPath": str(paths["light"]) if args.light else None,
                    "cpuPath": str(paths["cpu"]) if args.cpu else None,
                },
                ensure_ascii=False,
            )
        )
        print("SEND_MESSAGE_NOW")
        sys.stdout.flush()
        time.sleep(args.duration_sec)

        if args.cpu:
            next_id, cpu_result = command(sock, next_id, events, "Profiler.stop")
            write_json(paths["cpu"], cpu_result["profile"])

        if args.light:
            next_id, light_result = stop_light_probe(sock, next_id, events, context["id"])
            write_json(paths["light"], light_result)
            light_path = paths["light"]

        print_summary(light_result, light_path, paths["cpu"], args.cpu)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def main():
    args = parse_args()
    if args.duration_sec <= 0:
        raise SystemExit("--duration-sec must be > 0")
    if not args.cpu and not args.light:
        raise SystemExit("Enable at least one of --cpu or --light.")
    run_profile(args)


if __name__ == "__main__":
    main()

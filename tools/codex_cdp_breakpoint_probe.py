#!/usr/bin/env python3
import argparse
import json
import socket
import time
from pathlib import Path

from codex_webview_profiler import (
    collect_runtime_contexts,
    command,
    connect_websocket,
    evaluate_expression,
    find_target,
    read_websocket_message,
)


DEFAULT_TARGET_MARKER = "extensionId=openai.chatgpt"
DEFAULT_SCRIPT_MARKER = "app-initial-HCwVBrOJ.js"


def parse_arguments():
    parser = argparse.ArgumentParser(
        prog="codex-cdp-breakpoint-probe",
        description="Capture argument shapes at a Codex WebView JavaScript breakpoint.",
    )
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--line", type=int, required=True, help="One-based source line.")
    parser.add_argument("--column", type=int, required=True, help="One-based source column.")
    parser.add_argument("--duration-sec", type=float, default=30)
    parser.add_argument("--max-pauses", type=int, default=3)
    parser.add_argument("--target-marker", default=DEFAULT_TARGET_MARKER)
    parser.add_argument("--script-marker", default=DEFAULT_SCRIPT_MARKER)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def validate_arguments(arguments):
    if arguments.line <= 0:
        raise ValueError("--line must be greater than zero")
    if arguments.column <= 0:
        raise ValueError("--column must be greater than zero")
    if arguments.duration_sec <= 0:
        raise ValueError("--duration-sec must be greater than zero")
    if arguments.max_pauses <= 0:
        raise ValueError("--max-pauses must be greater than zero")


def drain_debugger_script_events(sock, next_id, events, context_id):
    return evaluate_expression(sock, next_id, events, context_id, "0")


def find_unique_script(events, script_marker):
    matching_scripts = []
    for event in events:
        if event.get("method") != "Debugger.scriptParsed":
            continue
        params = event.get("params", {})
        if script_marker not in params.get("url", ""):
            continue
        matching_scripts.append(
            {
                "scriptId": params.get("scriptId"),
                "url": params.get("url"),
            }
        )

    unique_scripts = {
        script["scriptId"]: script
        for script in matching_scripts
        if script.get("scriptId")
    }
    if len(unique_scripts) != 1:
        raise ValueError(
            f"Expected exactly one script matching {script_marker!r}, "
            f"found {len(unique_scripts)}: {list(unique_scripts.values())}"
        )
    return next(iter(unique_scripts.values()))


def get_possible_breakpoints(sock, next_id, events, script_id, line_index, column_index):
    params = {
        "start": {
            "scriptId": script_id,
            "lineNumber": line_index,
            "columnNumber": max(0, column_index - 160),
        },
        "end": {
            "scriptId": script_id,
            "lineNumber": line_index,
            "columnNumber": column_index + 160,
        },
        "restrictToFunction": False,
    }
    next_id, result = command(
        sock,
        next_id,
        events,
        "Debugger.getPossibleBreakpoints",
        params,
    )
    return next_id, result.get("locations", [])


def choose_closest_breakpoint(locations, line_index, column_index):
    matching_locations = [
        location
        for location in locations
        if location.get("lineNumber") == line_index
    ]
    if not matching_locations:
        raise ValueError(
            f"No executable breakpoint locations were found near "
            f"{line_index + 1}:{column_index + 1}"
        )
    return min(
        matching_locations,
        key=lambda location: abs(location.get("columnNumber", 0) - column_index),
    )


def install_breakpoint(sock, next_id, events, location):
    next_id, result = command(
        sock,
        next_id,
        events,
        "Debugger.setBreakpoint",
        {"location": location},
    )
    breakpoint_id = result.get("breakpointId")
    actual_location = result.get("actualLocation")
    if not breakpoint_id or not actual_location:
        raise RuntimeError(f"Debugger did not install the breakpoint: {result}")
    return next_id, breakpoint_id, actual_location


def summarize_remote_object(remote_object):
    value = remote_object.get("value")
    preview = remote_object.get("preview", {})
    preview_properties = []
    for preview_property in preview.get("properties", [])[:40]:
        preview_properties.append(
            {
                "name": preview_property.get("name"),
                "type": preview_property.get("type"),
                "subtype": preview_property.get("subtype"),
            }
        )
    return {
        "type": remote_object.get("type"),
        "subtype": remote_object.get("subtype"),
        "className": remote_object.get("className"),
        "description": remote_object.get("description"),
        "stringLength": len(value) if isinstance(value, str) else None,
        "primitiveValue": value if isinstance(value, (bool, int, float)) else None,
        "previewProperties": preview_properties,
        "previewOverflow": preview.get("overflow"),
    }


def get_scope_properties(sock, next_id, events, scope):
    scope_object = scope.get("object", {})
    object_id = scope_object.get("objectId")
    if object_id is None:
        return next_id, []
    next_id, result = command(
        sock,
        next_id,
        events,
        "Runtime.getProperties",
        {
            "objectId": object_id,
            "ownProperties": True,
            "accessorPropertiesOnly": False,
            "generatePreview": True,
            "nonIndexedPropertiesOnly": True,
        },
    )
    properties = []
    for descriptor in result.get("result", [])[:80]:
        properties.append(
            {
                "name": descriptor.get("name"),
                "value": summarize_remote_object(descriptor.get("value", {})),
            }
        )
    return next_id, properties


def capture_call_frame_scopes(sock, next_id, events, call_frame):
    captured_scopes = []
    for scope in call_frame.get("scopeChain", [])[:6]:
        next_id, properties = get_scope_properties(
            sock,
            next_id,
            events,
            scope,
        )
        captured_scopes.append(
            {
                "type": scope.get("type"),
                "name": scope.get("name"),
                "properties": properties,
            }
        )
    return next_id, captured_scopes


def summarize_call_frame(call_frame):
    location = call_frame.get("location", {})
    return {
        "functionName": call_frame.get("functionName") or "(anonymous)",
        "url": call_frame.get("url") or "",
        "line": location.get("lineNumber", -1) + 1,
        "column": location.get("columnNumber", -1) + 1,
    }


def capture_pause(sock, next_id, events, paused_message):
    call_frames = paused_message.get("params", {}).get("callFrames", [])
    if not call_frames:
        raise RuntimeError("Debugger paused without call frames")
    top_call_frame = call_frames[0]
    next_id, captured_scopes = capture_call_frame_scopes(
        sock,
        next_id,
        events,
        top_call_frame,
    )
    capture = {
        "capturedAt": time.time(),
        "reason": paused_message.get("params", {}).get("reason"),
        "topFrames": [summarize_call_frame(frame) for frame in call_frames[:16]],
        "topFrameScopes": captured_scopes,
    }
    return next_id, capture


def resume_debugger(sock, next_id, events):
    return command(sock, next_id, events, "Debugger.resume")


def remove_breakpoint(sock, next_id, events, breakpoint_id):
    return command(
        sock,
        next_id,
        events,
        "Debugger.removeBreakpoint",
        {"breakpointId": breakpoint_id},
    )


def wait_for_captures(sock, next_id, events, duration_sec, max_pauses):
    captures = []
    deadline = time.monotonic() + duration_sec
    while time.monotonic() < deadline and len(captures) < max_pauses:
        remaining = deadline - time.monotonic()
        sock.settimeout(min(1.0, max(0.05, remaining)))
        try:
            message = read_websocket_message(sock)
        except socket.timeout:
            continue
        if message is None:
            continue
        if message.get("method") != "Debugger.paused":
            if "method" in message:
                events.append(message)
            continue
        next_id, capture = capture_pause(sock, next_id, events, message)
        captures.append(capture)
        print("BREAKPOINT_CAPTURE " + json.dumps(capture, ensure_ascii=False))
        next_id, _ = resume_debugger(sock, next_id, events)
    return next_id, captures


def write_report(path, report):
    resolved_path = path.expanduser()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_probe(arguments):
    target = find_target(arguments.port, arguments.target_marker)
    sock = connect_websocket(target["webSocketDebuggerUrl"])
    events = []
    next_id = 1
    breakpoint_id = None
    debugger_may_be_paused = False
    try:
        next_id, contexts = collect_runtime_contexts(sock, next_id, events)
        content_contexts = [
            context
            for context in contexts
            if context.get("auxData", {}).get("isDefault")
        ]
        if not content_contexts:
            raise RuntimeError("No default execution context was found")
        content_context = content_contexts[-1]

        next_id, _ = command(sock, next_id, events, "Debugger.enable")
        next_id, _ = drain_debugger_script_events(
            sock,
            next_id,
            events,
            content_context["id"],
        )
        script = find_unique_script(events, arguments.script_marker)
        line_index = arguments.line - 1
        column_index = arguments.column - 1
        next_id, locations = get_possible_breakpoints(
            sock,
            next_id,
            events,
            script["scriptId"],
            line_index,
            column_index,
        )
        location = choose_closest_breakpoint(
            locations,
            line_index,
            column_index,
        )
        next_id, breakpoint_id, actual_location = install_breakpoint(
            sock,
            next_id,
            events,
            location,
        )
        debugger_may_be_paused = True
        print(
            "BREAKPOINT_READY "
            + json.dumps(
                {
                    "script": script,
                    "requested": {
                        "line": arguments.line,
                        "column": arguments.column,
                    },
                    "actual": {
                        "line": actual_location["lineNumber"] + 1,
                        "column": actual_location["columnNumber"] + 1,
                    },
                    "durationSec": arguments.duration_sec,
                    "maxPauses": arguments.max_pauses,
                },
                ensure_ascii=False,
            )
        )
        print("TRIGGER_STREAM_NOW")
        next_id, captures = wait_for_captures(
            sock,
            next_id,
            events,
            arguments.duration_sec,
            arguments.max_pauses,
        )
        debugger_may_be_paused = False
        report = {
            "target": target.get("url"),
            "script": script,
            "requestedLine": arguments.line,
            "requestedColumn": arguments.column,
            "actualLocation": actual_location,
            "captureCount": len(captures),
            "captures": captures,
        }
        write_report(arguments.out, report)
        print("BREAKPOINT_DONE " + json.dumps(report, ensure_ascii=False))
    finally:
        if debugger_may_be_paused:
            try:
                next_id, _ = resume_debugger(sock, next_id, events)
            except (OSError, RuntimeError):
                pass
        if breakpoint_id is not None:
            try:
                next_id, _ = remove_breakpoint(
                    sock,
                    next_id,
                    events,
                    breakpoint_id,
                )
            except (OSError, RuntimeError):
                pass
        try:
            command(sock, next_id, events, "Debugger.disable")
        except (OSError, RuntimeError):
            pass
        sock.close()


def main():
    arguments = parse_arguments()
    validate_arguments(arguments)
    run_probe(arguments)


if __name__ == "__main__":
    main()

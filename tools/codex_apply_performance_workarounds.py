#!/usr/bin/env python3
import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


CODEX_EXTENSION_ROOTS = {
    "vscode": Path.home() / ".vscode" / "extensions",
    "antigravity": Path.home() / ".antigravity" / "extensions",
}

STATUS_NEEDS_PATCH = "needs_patch"
STATUS_PATCHED = "patched"
STATUS_NOT_APPLICABLE = "not_applicable"

STREAM_FRAME_CHARACTER_BUDGET = 384

HEARTBEAT_TURN_DETECTION_ORIGINAL = (
    "function nOe(e){return e.status!==`completed`||e.error!=null||"
    "Uh(e.params.input)!=null||Hh(e.items)!=null?!1:Lh(e.items).some("
    "e=>e.type===`agentMessage`&&Ph(e.text)!=null)}"
)
HEARTBEAT_TURN_DETECTION_CACHE_MARKER = (
    "/* agents-rtl-cache-heartbeat-turn-detection */"
)
HEARTBEAT_TURN_DETECTION_CACHED = (
    "var agentsRtlHeartbeatTurnDetectionCache=new WeakMap;"
    f"{HEARTBEAT_TURN_DETECTION_CACHE_MARKER}"
    "function nOe(e){if(e.status!==`completed`)return!1;"
    "let t=e.params.input,n=e.items,r=n.length,i=n[r-1],"
    "a=agentsRtlHeartbeatTurnDetectionCache.get(e);"
    "if(a!=null&&a.error===e.error&&a.input===t&&a.items===n&&"
    "a.length===r&&a.last===i)return a.value;"
    "let o=e.error!=null||Uh(t)!=null||Hh(n)!=null?!1:Lh(n).some("
    "e=>e.type===`agentMessage`&&Ph(e.text)!=null);"
    "return agentsRtlHeartbeatTurnDetectionCache.set(e,{error:e.error,"
    "input:t,items:n,length:r,last:i,value:o}),o}"
)

STREAM_FRAME_CHARACTER_BUDGET_ORIGINAL = "NNe=16,PNe=24,FNe=8,INe=class"
STREAM_FRAME_CHARACTER_BUDGET_MARKER = (
    "/* agents-rtl-increase-stream-frame-character-budget */"
)
STREAM_FRAME_CHARACTER_BUDGET_PATCHED = (
    f"{STREAM_FRAME_CHARACTER_BUDGET_MARKER}"
    f"NNe=16,PNe={STREAM_FRAME_CHARACTER_BUDGET},FNe=8,INe=class"
)


def parse_arguments():
    parser = argparse.ArgumentParser(
        prog="codex-apply-performance-workarounds",
        description=(
            "Inspect or apply the verified Codex WebView performance workarounds."
        ),
    )
    parser.add_argument(
        "command",
        choices=["status", "apply"],
        help="Inspect without writing or apply the exact verified patch.",
    )
    parser.add_argument(
        "--target",
        choices=["all", "vscode", "antigravity"],
        default="all",
        help="Installed application target.",
    )
    return parser.parse_args()


def selected_target_names(target_name):
    if target_name == "all":
        return list(CODEX_EXTENSION_ROOTS)
    return [target_name]


def discover_codex_asset_directories(target_names):
    asset_directories = []
    for target_name in target_names:
        extension_root = CODEX_EXTENSION_ROOTS[target_name]
        if not extension_root.exists():
            raise FileNotFoundError(
                f"Codex extension root does not exist: {extension_root}"
            )

        target_asset_directories = sorted(
            extension_root.glob("openai.chatgpt-*/webview/assets")
        )
        if not target_asset_directories:
            raise FileNotFoundError(
                f"No Codex WebView asset directories found under: {extension_root}"
            )
        if len(target_asset_directories) != 1:
            raise ValueError(
                "Expected exactly one installed Codex extension directory for "
                f"{target_name}, found {len(target_asset_directories)}: "
                f"{[str(path) for path in target_asset_directories]}"
            )

        for asset_directory in target_asset_directories:
            asset_directories.append((target_name, asset_directory))
    return asset_directories


def find_app_initial_files(asset_directories):
    app_initial_files = []
    for target_name, asset_directory in asset_directories:
        matching_files = sorted(asset_directory.glob("app-initial-*.js"))
        if not matching_files:
            raise FileNotFoundError(
                f"No app-initial JavaScript files found in: {asset_directory}"
            )
        for matching_file in matching_files:
            app_initial_files.append((target_name, matching_file))
    return app_initial_files


def inspect_exact_source_workaround(
    source,
    original_source,
    marker,
    patched_source,
    workaround_name,
):
    original_count = source.count(original_source)
    marker_count = source.count(marker)
    patched_count = source.count(patched_source)
    if original_count > 1:
        raise ValueError(f"Multiple original {workaround_name} forms were found.")
    if marker_count > 1:
        raise ValueError(f"Multiple {workaround_name} markers were found.")
    if original_count == 1 and marker_count == 1:
        raise ValueError(
            f"Both original and patched {workaround_name} forms were found."
        )
    if original_count == 1:
        return STATUS_NEEDS_PATCH
    if marker_count == 1:
        if patched_count != 1:
            raise ValueError(
                f"{workaround_name} marker exists, but the patched form does not "
                "match the verified source."
            )
        return STATUS_PATCHED
    if patched_count != 0:
        raise ValueError(
            f"Patched {workaround_name} exists without its required marker."
        )
    return STATUS_NOT_APPLICABLE


def patch_exact_source_workaround(
    source,
    original_source,
    marker,
    patched_source,
    workaround_name,
):
    status = inspect_exact_source_workaround(
        source,
        original_source,
        marker,
        patched_source,
        workaround_name,
    )
    if status == STATUS_PATCHED:
        return source, status
    if status != STATUS_NEEDS_PATCH:
        raise ValueError(f"The verified {workaround_name} is not applicable.")

    updated_source = source.replace(
        original_source,
        patched_source,
        1,
    )
    updated_status = inspect_exact_source_workaround(
        updated_source,
        original_source,
        marker,
        patched_source,
        workaround_name,
    )
    if updated_status != STATUS_PATCHED:
        raise ValueError(f"{workaround_name} failed post-patch verification.")
    return updated_source, "applied"


def inspect_heartbeat_turn_detection_cache(source):
    return inspect_exact_source_workaround(
        source,
        HEARTBEAT_TURN_DETECTION_ORIGINAL,
        HEARTBEAT_TURN_DETECTION_CACHE_MARKER,
        HEARTBEAT_TURN_DETECTION_CACHED,
        "heartbeat turn detection cache",
    )


def patch_heartbeat_turn_detection_cache(source):
    return patch_exact_source_workaround(
        source,
        HEARTBEAT_TURN_DETECTION_ORIGINAL,
        HEARTBEAT_TURN_DETECTION_CACHE_MARKER,
        HEARTBEAT_TURN_DETECTION_CACHED,
        "heartbeat turn detection cache",
    )


def inspect_stream_frame_character_budget(source):
    return inspect_exact_source_workaround(
        source,
        STREAM_FRAME_CHARACTER_BUDGET_ORIGINAL,
        STREAM_FRAME_CHARACTER_BUDGET_MARKER,
        STREAM_FRAME_CHARACTER_BUDGET_PATCHED,
        "stream frame character budget",
    )


def patch_stream_frame_character_budget(source):
    return patch_exact_source_workaround(
        source,
        STREAM_FRAME_CHARACTER_BUDGET_ORIGINAL,
        STREAM_FRAME_CHARACTER_BUDGET_MARKER,
        STREAM_FRAME_CHARACTER_BUDGET_PATCHED,
        "stream frame character budget",
    )


def inspect_app_initial_files(app_initial_files):
    reports = []
    for target_name, path in app_initial_files:
        source = path.read_text()
        reports.append(
            {
                "target_name": target_name,
                "path": path,
                "source": source,
                "heartbeat_status": inspect_heartbeat_turn_detection_cache(source),
                "stream_frame_status": inspect_stream_frame_character_budget(source),
            }
        )
    return reports


def validate_exactly_one_supported_file_per_target(reports, target_names):
    for target_name in target_names:
        for status_key, workaround_name in [
            ("heartbeat_status", "heartbeat turn detection cache"),
            ("stream_frame_status", "stream frame character budget"),
        ]:
            supported_reports = [
                report
                for report in reports
                if report["target_name"] == target_name
                and report[status_key] != STATUS_NOT_APPLICABLE
            ]
            if len(supported_reports) != 1:
                supported_paths = [
                    str(report["path"]) for report in supported_reports
                ]
                raise ValueError(
                    "Expected exactly one supported Codex asset for "
                    f"{workaround_name} on {target_name}, found "
                    f"{len(supported_reports)}: {supported_paths}"
                )


def backup_file(path):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(
        f"{path.name}.agents-rtl-workaround-bak-{timestamp}"
    )
    shutil.copy2(path, backup_path)
    return backup_path


def print_status_reports(reports):
    for report in reports:
        print(f"{report['target_name']}: {report['path']}")
        print(
            "  heartbeat_turn_detection_cache: "
            f"{report['heartbeat_status']}"
        )
        print(
            "  stream_frame_character_budget: "
            f"{report['stream_frame_status']}"
        )
        would_change = (
            report["heartbeat_status"] == STATUS_NEEDS_PATCH
            or report["stream_frame_status"] == STATUS_NEEDS_PATCH
        )
        print(f"  would_change: {would_change}")


def apply_reports(reports):
    patch_plans = []
    for report in reports:
        if (
            report["heartbeat_status"] != STATUS_NEEDS_PATCH
            and report["stream_frame_status"] != STATUS_NEEDS_PATCH
        ):
            continue

        patched_source = report["source"]
        heartbeat_patch_status = report["heartbeat_status"]
        stream_frame_patch_status = report["stream_frame_status"]
        if heartbeat_patch_status == STATUS_NEEDS_PATCH:
            patched_source, heartbeat_patch_status = (
                patch_heartbeat_turn_detection_cache(patched_source)
            )
        if stream_frame_patch_status == STATUS_NEEDS_PATCH:
            patched_source, stream_frame_patch_status = (
                patch_stream_frame_character_budget(patched_source)
            )

        patch_plans.append(
            {
                "target_name": report["target_name"],
                "path": report["path"],
                "patched_source": patched_source,
                "heartbeat_patch_status": heartbeat_patch_status,
                "stream_frame_patch_status": stream_frame_patch_status,
            }
        )

    changed_count = 0
    changed_paths = set()
    for patch_plan in patch_plans:
        path = patch_plan["path"]
        backup_path = backup_file(path)
        path.write_text(patch_plan["patched_source"])
        written_source = path.read_text()
        final_heartbeat_status = inspect_heartbeat_turn_detection_cache(
            written_source
        )
        final_stream_frame_status = inspect_stream_frame_character_budget(
            written_source
        )
        if final_heartbeat_status != STATUS_PATCHED:
            raise ValueError(
                f"Written heartbeat patch failed verification: {path}"
            )
        if final_stream_frame_status != STATUS_PATCHED:
            raise ValueError(
                f"Written stream frame patch failed verification: {path}"
            )

        changed_count += 1
        changed_paths.add(path)
        print(f"{patch_plan['target_name']}: {path}")
        print("  changed: True")
        print(f"  backup: {backup_path}")
        print(
            "  heartbeat_turn_detection_cache: "
            f"{patch_plan['heartbeat_patch_status']}"
        )
        print(
            "  stream_frame_character_budget: "
            f"{patch_plan['stream_frame_patch_status']}"
        )

    for report in reports:
        if report["path"] in changed_paths:
            continue
        print(f"{report['target_name']}: {report['path']}")
        print("  changed: False")
        print(
            "  heartbeat_turn_detection_cache: "
            f"{report['heartbeat_status']}"
        )
        print(
            "  stream_frame_character_budget: "
            f"{report['stream_frame_status']}"
        )

    print(f"changed_files: {changed_count}")


def main():
    arguments = parse_arguments()
    target_names = selected_target_names(arguments.target)
    asset_directories = discover_codex_asset_directories(target_names)
    app_initial_files = find_app_initial_files(asset_directories)
    reports = inspect_app_initial_files(app_initial_files)
    validate_exactly_one_supported_file_per_target(reports, target_names)

    if arguments.command == "status":
        print_status_reports(reports)
        return
    apply_reports(reports)


if __name__ == "__main__":
    main()

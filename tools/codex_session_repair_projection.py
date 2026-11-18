#!/usr/bin/env python3
"""Repair one conversation's indexes, or all indexes and lineage in a Codex home."""

import argparse
from pathlib import Path

from codex_session_projection import repair_projection
from codex_session_history_repair import repair_history_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--session", type=Path)
    targets.add_argument("--all-home", type=Path, help="Include sessions and archived_sessions")
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if arguments.all_home is not None:
        repair_history_home(arguments.all_home, arguments.apply)
    else:
        repair_projection(arguments.session, arguments.apply)


if __name__ == "__main__":
    main()

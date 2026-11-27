"""Offline structured-image cleanup for a session and its ancestors, or a home.

Keep every Codex client stopped until completion or --recover. Shared history
cutoffs and SQLite offsets are updated together. No replacement text is added.
Cleaning shared ancestors also removes those images from dependent histories.
Ordinary text, external attachment files and backups are not removed.
"""

import argparse
from pathlib import Path

from codex_session_bulk_transaction import (
    clean_history_home,
    clean_history_session,
    recover_history_home,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session", type=Path, help="Clean this rollout and its ancestors; update all affected references")
    mode.add_argument("--all-home", type=Path, help="Clean active AND archived histories in this Codex home")
    mode.add_argument("--recover", type=Path, help="Journal printed by an interrupted operation")
    parser.add_argument("--apply", action="store_true", help="Required explicit permission to write")
    arguments = parser.parse_args()
    if not arguments.apply:
        parser.error("No files changed. --apply is required for cleanup or recovery.")
    if arguments.session is not None:
        clean_history_session(arguments.session.expanduser())
    elif arguments.all_home is not None:
        clean_history_home(arguments.all_home.expanduser())
    else:
        recover_history_home(arguments.recover.expanduser())


if __name__ == "__main__":
    main()

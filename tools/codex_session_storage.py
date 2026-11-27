"""Offline, checked writes shared by session maintenance tools (Linux only)."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

COPY_CHUNK_BYTES = 1024 * 1024
UNRELATED_SPECIAL_FILESYSTEM_TYPES = {"overlay", "nsfs", "hugetlbfs", "mqueue"}
IMAGE_CLEANUP_JOURNAL_PATTERNS = (
    "image-clean-transaction-*/transaction.json",
    "bulk-image-clean-*/bulk-transaction.json",
)


def file_signature(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular non-symlink file: {path}")
    metadata = path.stat()
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def require_unchanged(signatures):
    for path, expected in signatures.items():
        if file_signature(path) != expected:
            raise RuntimeError(f"Session changed during maintenance: {path}")


def require_codex_stopped():
    result = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-x", "codex"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        raise RuntimeError(f"Close all Codex clients before writing. Running PIDs: {result.stdout.strip()}")
    if result.returncode != 1 or result.stderr.strip():
        raise RuntimeError(f"Cannot check running Codex processes: {result.stderr.strip()}")


def open_file_check(path):
    target = Path(path).resolve(strict=True)
    device = target.stat().st_dev
    device_id = f"{os.major(device)}:{os.minor(device)}"
    mounts = subprocess.run(
        ["findmnt", "--json", "--list", "--output", "TARGET,MAJ:MIN,FSTYPE"],
        capture_output=True, text=True, check=True,
    )
    if mounts.stderr.strip():
        raise RuntimeError(f"Cannot verify mounts: {mounts.stderr.strip()}")
    filesystems = json.loads(mounts.stdout)["filesystems"]
    if not isinstance(filesystems, list) or not filesystems:
        raise ValueError("Invalid mount inventory")
    exempt_mounts = set()
    for filesystem in filesystems:
        mount = Path(filesystem["target"])
        if not mount.is_absolute():
            raise ValueError(f"Mount target is not absolute: {mount}")
        if (
            filesystem["fstype"] in UNRELATED_SPECIAL_FILESYSTEM_TYPES
            and filesystem["maj:min"] != device_id and not target.is_relative_to(mount)
        ):
            exempt_mounts.add(str(mount))
    command = ["lsof"]
    for mount in sorted(exempt_mounts):
        command.extend(["-e", mount])
    return subprocess.run([*command, "--", str(target)], capture_output=True, text=True, check=False)


def require_closed(path):
    result = open_file_check(path)
    if result.returncode != 1 or result.stdout.strip() or result.stderr.strip():
        raise RuntimeError(f"File is open or its check failed: {path}\n{result.stdout}{result.stderr}")


def require_no_unfinished_image_cleanup(roots):
    homes = set(map(Path, roots))
    homes.update(root.parent for root in list(homes) if root.name in ("sessions", "archived_sessions"))
    for home in sorted(homes):
        directory = home / "session_maintenance_backups"
        if directory.is_symlink():
            raise ValueError(f"Symlink maintenance directory: {directory}")
        for pattern in IMAGE_CLEANUP_JOURNAL_PATTERNS:
            for journal_path in sorted(directory.glob(pattern)):
                file_signature(journal_path)
                journal = json.loads(journal_path.read_text())
                if journal["version"] != 1 or journal["status"] not in ("prepared", "applied", "rolled_back"):
                    raise ValueError(f"Unknown image-clean transaction state: {journal_path}")
                if journal["status"] == "prepared":
                    raise RuntimeError(f"Recover unfinished image cleanup before other maintenance: {journal_path}")


@contextmanager
def offline_session_lock(roots, *, allow_pending_image_cleanup=False):
    if os.name != "posix":
        raise RuntimeError("Session maintenance writes require Linux offline guards")
    import fcntl

    descriptors = []
    try:
        roots = sorted(set(map(Path, roots)))
        for root in roots:
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            descriptors.append(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_codex_stopped()
        if not allow_pending_image_cleanup:
            require_no_unfinished_image_cleanup(roots)
        yield
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def sha256_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_staged_file(path):
    return tempfile.NamedTemporaryFile(mode="wb", dir=Path(path).parent, prefix=".session-maintenance-", delete=False)


def replace_verified(path, staged_path, signatures, backup_label):
    path, staged_path = Path(path), Path(staged_path)
    require_codex_stopped()
    require_closed(path)
    require_unchanged(signatures)
    staged_hash = sha256_file(staged_path)
    source_hash = sha256_file(path)
    backup = path.with_name(path.name + f".{backup_label}-bak-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    with path.open("rb") as source, backup.open("xb") as destination:
        os.fchmod(destination.fileno(), 0o600)
        shutil.copyfileobj(source, destination, COPY_CHUNK_BYTES)
        destination.flush()
        os.fsync(destination.fileno())
    if sha256_file(backup) != source_hash:
        raise RuntimeError(f"Backup verification failed: {backup}")
    require_codex_stopped()
    require_closed(path)
    require_unchanged(signatures)
    os.replace(staged_path, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if sha256_file(path) != staged_hash:
        raise RuntimeError(f"Read-back verification failed; retain {backup}")
    return backup

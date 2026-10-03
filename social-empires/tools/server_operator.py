"""Offline-only admin operations for the single-process revival alpha.

Keep this tool on the host computer. No administrative HTTP endpoints exist.
Backup requires *stopping* the game server first for a consistent snapshot.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def promote_admin(db_path: Path, username: str) -> int:
    username = username.casefold().strip()
    if not username or len(username) > 24:
        raise ValueError("Invalid account name")
    with sqlite3.connect(db_path) as db:
        changed = db.execute(
            "UPDATE accounts SET is_admin=1 WHERE username=? AND is_admin=0",
            (username,),
        ).rowcount
        if changed == 0:
            present = db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone()
            if not present:
                raise ValueError("Account not found; create it through /register first")
        return changed


def snapshot(db_path: Path, saves_dir: Path, output: Path):
    """Produce a verified, owner-readable ZIP from a STOPPED server.

    Validate the entire input before writing the final backup. If a registered
    account is missing its village or a save is damaged, abort rather than
    deliver a false impression of complete recovery.
    """
    db_path = db_path.resolve()
    saves_dir = saves_dir.resolve()
    output = output.resolve()
    if not db_path.is_file() or not saves_dir.is_dir():
        raise FileNotFoundError("Account database and saves directory must exist")
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing backup")
    if not output.parent.is_dir():
        raise FileNotFoundError("Backup parent directory does not exist")

    with tempfile.TemporaryDirectory(prefix="revival-backup-", dir=output.parent) as temp:
        db_copy = Path(temp) / "accounts.sqlite3"
        with sqlite3.connect(db_path) as current:
            if current.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Account database integrity check failed")
            with sqlite3.connect(db_copy) as backup:
                current.backup(backup)
        with sqlite3.connect(db_copy) as offline:
            account_villages = {
                row[0] for row in offline.execute("SELECT village_id FROM accounts")
            }
        files = sorted(saves_dir.glob("*.save.json"))
        saves = {}
        for file in files:
            if file.is_symlink() or not file.is_file():
                raise ValueError(f"Unsafe save file: {file}")
            village_id = file.name.removesuffix(".save.json")
            if "/" in village_id or not village_id:
                raise ValueError(f"Unexpected save name: {file.name}")
            payload = file.read_bytes()
            obj = json.loads(payload)
            if obj.get("playerInfo", {}).get("pid") != village_id:
                raise ValueError(f"Village identity mismatch: {file.name}")
            saves[village_id] = payload
        missing = account_villages.difference(saves)
        if missing:
            raise ValueError(f"Missing saves for {len(missing)} registered accounts; backup aborted")

        manifest = {
            "format": 1,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "account_count": len(account_villages),
            "save_count": len(saves),
            "sha256": {
                "accounts.sqlite3": hashlib.sha256(db_copy.read_bytes()).hexdigest(),
                **{
                    f"saves/{name}.save.json": hashlib.sha256(data).hexdigest()
                    for name, data in saves.items()
                },
            },
        }
        handle, temporary = tempfile.mkstemp(
            prefix=".revival-archive-", suffix=".zip", dir=output.parent
        )
        try:
            if hasattr(os, 'fchmod'):
                os.fchmod(handle, 0o600)
            with os.fdopen(handle, "wb") as writer:
                with zipfile.ZipFile(writer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(db_copy, "accounts.sqlite3")
                    for name, data in saves.items():
                        archive.writestr(f"saves/{name}.save.json", data)
                    archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Path to accounts.sqlite3")
    sub = parser.add_subparsers(dest="action", required=True)
    grant = sub.add_parser("grant-admin", help="Grant admin status through local CLI")
    grant.add_argument("--username", required=True)
    backup = sub.add_parser("backup", help="Offline account + village ZIP")
    backup.add_argument("--saves", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument(
        "--server-stopped", action="store_true",
        help="Confirm the game server process has been fully stopped",
    )
    args = parser.parse_args()
    if args.action == "grant-admin":
        changed = promote_admin(args.db, args.username)
        print("Admin role granted" if changed else "Already an admin")
    else:
        if not args.server_stopped:
            parser.error("Stop the game server; then pass --server-stopped")
        result = snapshot(args.db, args.saves, args.output)
        print(f"Backup complete: {result['account_count']} accounts, {result['save_count']} saves")


if __name__ == "__main__":
    main()

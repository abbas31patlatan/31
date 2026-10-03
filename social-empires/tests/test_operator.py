"""Offline operator regression tests with temporary accounts and villages."""

import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "operator_tool", ROOT / "tools" / "server_operator.py"
)
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = root / "accounts.sqlite3"
        self.saves = root / "saves"
        self.saves.mkdir()
        self.dest = root / "backup.zip"
        with sqlite3.connect(self.db) as db:
            db.execute("""CREATE TABLE accounts (
                account_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                village_id TEXT NOT NULL UNIQUE,
                is_admin INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute(
                "INSERT INTO accounts(username,village_id) VALUES(?,?)",
                ("alice", "village-1"),
            )

    def _save(self, pid="village-1"):
        path = self.saves / (pid + ".save.json")
        path.write_text(json.dumps({"playerInfo": {"pid": pid}, "maps": []}))
        return path

    def test_offline_admin_grant(self):
        self.assertEqual(operator.promote_admin(self.db, "Alice"), 1)
        self.assertEqual(operator.promote_admin(self.db, "alice"), 0)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT is_admin FROM accounts WHERE username='alice'"
            ).fetchone()[0], 1)
        with self.assertRaises(ValueError):
            operator.promote_admin(self.db, "unknown")

    def test_verified_backup_includes_db_and_save(self):
        self._save()
        result = operator.snapshot(self.db, self.saves, self.dest)
        self.assertEqual(result["account_count"], 1)
        self.assertEqual(result["save_count"], 1)
        self.assertTrue(self.dest.is_file())
        with zipfile.ZipFile(self.dest) as z:
            self.assertEqual(
                sorted(z.namelist()),
                ["MANIFEST.json", "accounts.sqlite3", "saves/village-1.save.json"],
            )
            self.assertEqual(json.loads(z.read("MANIFEST.json"))["account_count"], 1)
        with self.assertRaises(FileExistsError):
            operator.snapshot(self.db, self.saves, self.dest)

    def test_missing_or_corrupt_saves_fail_closed(self):
        with self.assertRaises(ValueError):
            operator.snapshot(self.db, self.saves, self.dest)
        self.assertFalse(self.dest.exists())
        damaged = self._save("different-id")
        damaged.rename(self.saves / "village-1.save.json")
        with self.assertRaises(ValueError):
            operator.snapshot(self.db, self.saves, self.dest)
        self.assertFalse(self.dest.exists())
        (self.saves / "village-1.save.json").write_text("{broken")
        with self.assertRaises(json.JSONDecodeError):
            operator.snapshot(self.db, self.saves, self.dest)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the read-only source inventory tool."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "audit_upstream.py"
spec = importlib.util.spec_from_file_location("audit_upstream", TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AuditTests(unittest.TestCase):
    def test_missing_source_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            report = module.audit(Path(temp))
            self.assertEqual(report["route_count"], 0)
            self.assertEqual(set(report["missing_required_files"]), set(module.REQUIRED))
            self.assertFalse(any(report["indicators"].values()))

    def test_detects_known_patterns_and_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in module.REQUIRED:
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("", encoding="utf-8")
            (root / "server.py").write_text(
                "host = '127.0.0.1'\n"
                "@app.route('/hello')\n"
                "@app.route('/hello', methods=['POST'])\n"
                "@app.route('/world')\n"
                "def login(): return request.form['USERID']\n"
                "# socialpointgames.com\nurllib.request.urlretrieve(source, destination)\n",
                encoding="utf-8",
            )
            (root / "sessions.py").write_text(
                "def backup_session(user):\n    # TODO\n    pass\n"
                "def save_session(user):\n    json.dump(village, handle)\n",
                encoding="utf-8",
            )
            (root / "templates/play.html").write_text(
                "http://{{SERVERIP}}:5050/game.swf", encoding="utf-8"
            )
            report = module.audit(root)
            self.assertEqual(report["missing_required_files"], [])
            self.assertEqual(report["route_count"], 2)
            self.assertEqual(report["routes"], ["/hello", "/world"])
            self.assertTrue(all(report["indicators"].values()))

    def test_does_not_report_unseen_patterns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in module.REQUIRED:
                f = root / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("safe fixture", encoding="utf-8")
            report = module.audit(root)
            self.assertFalse(any(report["indicators"].values()))


if __name__ == "__main__":
    unittest.main()

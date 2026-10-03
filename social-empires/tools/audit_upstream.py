"""Produce a conservative, read-only audit of a local Social Emperors source tree.

The checks identify potentially risky implementation patterns, NOT exploitation.
No game files are modified or uploaded.
"""

import argparse
import json
import re
from pathlib import Path

REQUIRED = (
    "server.py",
    "sessions.py",
    "templates/play.html",
    "templates/ruffle.html",
    "requirements.txt",
)


def audit(root: Path) -> dict:
    root = root.resolve()
    texts = {}
    missing = []
    for relative in REQUIRED:
        path = root / relative
        if path.is_file():
            texts[relative] = path.read_text(encoding="utf-8", errors="replace")
        else:
            texts[relative] = ""
            missing.append(relative)

    server = texts["server.py"]
    sessions = texts["sessions.py"]
    templates = texts["templates/play.html"] + "\n" + texts["templates/ruffle.html"]
    routes = sorted(set(re.findall(r"""@app\.route\(\s*['"]([^'"]+)""", server)))
    indicators = {
        "loopback_only_binding": bool(re.search(r"""(?m)^\s*host\s*=\s*['"]127\.0\.0\.1['"]""", server)),
        "form_selected_userid": "request.form['USERID']" in server or 'request.form["USERID"]' in server,
        "json_file_saves": "json.dump(village" in sessions,
        "backup_todo": bool(re.search(r"def backup_session\(", sessions)) and "# TODO" in sessions,
        "http_loopback_client_urls": "http://{{SERVERIP}}:5050" in templates,
        "legacy_socialpoint_paths": "socialpointgames.com" in server or "socialpoint.es" in server,
        "flash_client_reference": ".swf" in templates.lower(),
        "remote_asset_fallback": "urlretrieve(" in server,
    }
    return {
        "source_path": str(root),
        "missing_required_files": missing,
        "route_count": len(routes),
        "routes": routes,
        "indicators": indicators,
        "caveat": "Source-pattern inventory only; not a security certification or gameplay test.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True, help="Upstream source directory")
    parser.add_argument("--output", type=Path, help="Optional output JSON file")
    args = parser.parse_args()
    report = audit(args.path)
    result = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")
    return 2 if report["missing_required_files"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

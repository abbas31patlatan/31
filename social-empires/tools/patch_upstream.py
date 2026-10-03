"""Install the revival gateway into an authorized local copy of Social Emperors.

Keeps the original public repository untouched. Checks precise source anchors to
avoid silently applying modifications to incompatible upstream releases.
"""

import argparse
import shutil
from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(source: str, old: str, new: str, count: int, label: str) -> str:
    actual = source.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} anchors; found {actual}. No changes applied.")
    return source.replace(old, new)


def patch_sources(target: Path, gateway: Path) -> dict:
    source_paths = (
        "server.py", "sessions.py", "command.py", "get_player_info.py",
        "stub/crossdomain.xml",
        "templates/play.html", "templates/ruffle.html",
    )
    target = target.resolve()
    gateway = gateway.resolve()
    original = {}
    for name in source_paths:
        p = target / name
        if not p.is_file():
            raise PatchError(f"Missing original upstream file: {name}")
        original[name] = p.read_text(encoding="utf-8")
        if "# revival installed" in original[name]:
            raise PatchError("Already patched; restore a clean upstream copy")

    patched = dict(original)
    server = patched["server.py"]
    server = replace_exact(
        server, "from flask.debughelpers import attach_enctype_error_multidict\n",
        "", 1, "removed Flask helper",  # unused older Flask private import
    )
    server = replace_exact(
        server, "SERVERIP=host", 'SERVER_ORIGIN=os.environ.get("REVIVAL_PUBLIC_ORIGIN") or request.host_url.rstrip("/")',
        2, "absolute server URL context",
    )
    server = replace_exact(
        server, "return (get_neighbor_info(user, map), 200)",
        "return get_neighbor_info(user, map)", 2, "neighbor response shape",
    )
    server = replace_exact(
        server, "    app.secret_key = 'SECRET_KEY'\n",
        "    # Secret is provided by revival gateway.\n",
        1, "hard-coded upstream cookie signing key",
    )
    server = replace_exact(
        server, "\nif __name__ == '__main__':",
        "\n# revival installed — identity gateway, requires secure configuration\n"
        "from pathlib import Path as _RevivalPath\n"
        "import sys as _revival_sys\n"
        "_revival_sys.path.insert(0, str(_RevivalPath(__file__).resolve().parent / '_revival'))\n"
        "from revival_gateway import install_revival\n"
        "install_revival(app, new_village)\n"
        "\nif __name__ == '__main__':",
        1, "gateway installation",
    )
    server = replace_exact(
        server,
        'return render_template("ruffle.html", save_info=save_info(USERID),',
        'return render_template("ruffle.html", friendsInfo=fb_friends_str(USERID), save_info=save_info(USERID),',
        1, "Ruffle friend data",
    )
    patched["server.py"] = server

    logout = (
        '(<form method="post" action="/signout" style="display:inline">'
        '<input type="hidden" name="csrf" value="{{csrf_token}}">'
        '<button type="submit">logout</button></form>)'
    )
    for template in ("templates/play.html", "templates/ruffle.html"):
        s = patched[template]
        occurrences = s.count("http://{{SERVERIP}}:5050")
        if occurrences < 3:
            raise PatchError(f"{template}: expected >=3 localhost URL references; found {occurrences}")
        s = s.replace("http://{{SERVERIP}}:5050", "{{SERVER_ORIGIN}}")
        s = replace_exact(s, "user_key=123456789", "user_key={{revival_game_key}}", 1, f"{template} signed session key")
        s = replace_exact(s, '(<a href="/">logout</a>)', logout, 1, f"{template} logout")
        if template == "templates/ruffle.html":
            # Upstream sends a concatenated escaped string, including a malformed
            # friendsInfo field, not the parameter object expected by Ruffle.
            start = s.find("                parameters: '")
            end = s.find("\n                });", start)
            if start < 0 or end < start:
                raise PatchError("Unknown Ruffle player.load parameters layout")
            params = (
                '                parameters: {\n'
                '                    spdebug: "notnull",\n'
                '                    staticUrl: "{{SERVER_ORIGIN}}/default01.static.socialpointgames.com/static/socialempires/",\n'
                '                    dynamicUrl: "{{SERVER_ORIGIN}}/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/",\n'
                '                    fb_sig_user: {{save_info.userid|tojson}},\n'
                '                    user_key: {{revival_game_key|tojson}},\n'
                '                    language: "en",\n'
                '                    accessToken: "revival-not-facebook",\n'
                '                    friendsInfo: {{friendsInfo|tojson|tojson}},\n'
                '                    serverTime: {{serverTime|tojson}},\n'
                '                    forceSyncError: "1",\n'
                '                    forceAttackReload: "0",\n'
                '                    forceQuestReload: "0"\n'
                '                }'
            )
            s = s[:start] + params + s[end:]
        else:
            # Remove the historical Facebook-looking dummy token; it is not a
            # valid credential and cannot authorize gameplay on our server.
            s = replace_exact(
                s,
                "accessToken=AAABbZAm0wdMUBALsOrR0Ho68CLjaOT8SV3vftKg9mbo1zZColaW5FljRVaLxPGxXXnm1M98mTZCAttcQ4GHwvSyXfsyxYmvKMH8Hmn5iliSPnjvIsZA6",
                "accessToken=revival-not-facebook",
                1, "remove dummy Facebook access token",
            )
        patched[template] = s

    # A complete JSON replacement avoids truncated/corrupted village files on
    # process interruption. This is NOT cross-process transactional gameplay.
    sessions = patched["sessions.py"]
    old_write = (
        "    with open(os.path.join(SAVES_DIR, file), 'w') as f:\n"
        "        json.dump(village, f, indent=4)"
    )
    atomic_write = (
        "    import tempfile\n"
        "    dest = os.path.join(SAVES_DIR, file)\n"
        "    fd, temporary = tempfile.mkstemp(prefix='.village-', suffix='.tmp', dir=SAVES_DIR)\n"
        "    try:\n"
        "        with os.fdopen(fd, 'w', encoding='utf-8') as f:\n"
        "            json.dump(village, f, indent=4)\n"
        "            f.flush()\n"
        "            os.fsync(f.fileno())\n"
        "        os.replace(temporary, dest)\n"
        "    finally:\n"
        "        if os.path.exists(temporary):\n"
        "            os.unlink(temporary)"
    )
    sessions = replace_exact(sessions, old_write, atomic_write, 1, "atomic save")
    # Neighbor summaries should not modify live playerInfo dictionaries.
    sessions = replace_exact(sessions, '        neigh = vill["playerInfo"]',
                             '        neigh = copy.deepcopy(vill["playerInfo"])',
                             2, "neighbor copy")
    patched["sessions.py"] = sessions

    # Never permit a wildcard Flash policy on the protected account server.
    policy = patched["stub/crossdomain.xml"]
    if 'domain="*"' not in policy:
        raise PatchError("Unexpected Flash cross-domain policy")
    patched["stub/crossdomain.xml"] = (
        '<?xml version="1.0"?>\n'
        '<cross-domain-policy>\n'
        '  <site-control permitted-cross-domain-policies="none"/>\n'
        '</cross-domain-policy>\n'
    )

    # Neighbor visits are readable but may not disclose the other player's
    # private state (quest data, game economy, timers and saved secrets).
    neighbor = target / "get_player_info.py"
    if not neighbor.is_file():
        raise PatchError("Missing upstream get_player_info.py")
    player_info = neighbor.read_text(encoding="utf-8")
    player_info = replace_exact(
        player_info,
        '        "privateState": neighbor_session(userid)["privateState"],',
        '        "privateState": {"strategy": neighbor_session(userid)["privateState"].get("strategy", 8)},',
        1, "neighbor private state disclosure",
    )
    player_info = replace_exact(
        player_info,
        '    neighbor_info = {\n',
        '    if neighbor_session(userid) is None or not isinstance(map_number, int) or map_number < 0 or map_number >= len(neighbor_session(userid)["maps"]):\n'
        '        return {"result": "error", "message": "Neighbor not found"}, 404\n'
        '    neighbor_info = {\n',
        1, "unknown neighbor error",
    )
    patched["get_player_info.py"] = player_info

    command = patched["command.py"]
    command = replace_exact(
        command, "def command(USERID, data):", "def _unlocked_command(USERID, data):",
        1, "command entrypoint",
    )
    command += (
        "\n\n# revival installed: serialize command batches within a single process.\n"
        "import threading as _revival_threading\n"
        "_revival_command_lock = _revival_threading.RLock()\n"
        "def command(USERID, data):\n"
        "    with _revival_command_lock:\n"
        "        return _unlocked_command(USERID, data)\n"
    )
    patched["command.py"] = command

    # Validate every input before writing any patched original.
    if not gateway.is_file():
        raise PatchError(f"Gateway file not found: {gateway}")
    compiled_files = {}
    for filename, source in patched.items():
        if filename.endswith(".py"):
            compile(source, filename, "exec")
        compiled_files[filename] = source

    for filename, source in compiled_files.items():
        (target / filename).write_text(source, encoding="utf-8")
    out = target / "_revival"
    out.mkdir(exist_ok=True)
    shutil.copy2(gateway, out / "revival_gateway.py")
    safe_commands = gateway.parent / "revival_safe_commands.py"
    if not safe_commands.is_file():
        raise PatchError("Missing validated command module")
    shutil.copy2(safe_commands, out / "revival_safe_commands.py")
    return {
        "patched_files": list(compiled_files),
        "gateway": "_revival/revival_gateway.py",
        "warning": "Development adapter only. Do not expose publicly until gameplay validation passes.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    default_gateway = Path(__file__).resolve().parents[1] / "overlay" / "revival_gateway.py"
    parser.add_argument("--gateway", type=Path, default=default_gateway)
    args = parser.parse_args()
    print(patch_sources(args.path, args.gateway))


if __name__ == "__main__":
    main()

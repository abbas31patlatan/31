"""Smoke-test patched real upstream modules without serving a public port.

Run only against a disposable checkout of the upstream source with the
revival patch installed; will create saves in the checkout's saves directory.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def run(source):
    source = source.resolve()
    import_secrets = __import__("secrets")
    with tempfile.TemporaryDirectory() as t:
        os.environ["REVIVAL_SECRET_KEY"] = import_secrets.token_hex(32)
        os.environ["REVIVAL_DB"] = str(Path(t) / "accounts.sqlite3")
        os.environ["REVIVAL_REQUIRE_HTTPS"] = "0"
        os.environ["REVIVAL_ALLOWED_HOSTS"] = "localhost,127.0.0.1"
        os.environ.pop("REVIVAL_ALLOW_UNVALIDATED_COMMANDS", None)
        os.chdir(source)
        sys.path.insert(0, str(source))
        import server
        from sessions import all_saves_userid

        app = server.app
        app.testing = True
        a, b = app.test_client(), app.test_client()

        def create(client, name):
            res = client.get("/register")
            assert res.status_code == 200, ("registration page", res.status_code)
            with client.session_transaction() as s:
                csrf = s["revival_csrf"]
            res = client.post("/register", data={
                "username": name,
                "password": "this-is-a-long-passphrase",
                "csrf": csrf,
            })
            assert res.status_code == 303, ("register", name, res.status_code)
            with client.session_transaction() as s:
                pid = s["USERID"]
            return pid

        alice, bob = create(a, "Alice"), create(b, "Bob")
        assert alice != bob
        assert alice in all_saves_userid() and bob in all_saves_userid()
        assert a.get("/play.html").status_code == 200
        assert b.get("/play.html").status_code == 200
        assert alice.encode() in a.get("/play.html").data
        assert bob.encode() not in a.get("/play.html").data

        endpoint = (
            "/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/"
            "srvempires/get_player_info.php"
        )
        base = {"user_key": "legacy", "language": "en", "client_id": "test"}
        assert a.post(endpoint, data={**base, "USERID": alice}).status_code == 200
        assert b.post(endpoint, data={**base, "USERID": bob}).status_code == 200
        assert a.post(endpoint, data={**base, "USERID": bob}).status_code == 403

        command = endpoint.replace("get_player_info.php", "command.php")
        assert a.post(command, data={"USERID": alice}).status_code == 503

        # Save files are valid JSON and retain distinct player identifiers.
        for pid in (alice, bob):
            village = json.loads((source / "saves" / f"{pid}.save.json").read_text())
            assert village["playerInfo"]["pid"] == pid
        assert not list((source / "saves").glob(".village-*.tmp"))
        print("PASS: real upstream imports, account pages, separate villages, game read, isolation and atomic saves")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()
    run(args.path)

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
        os.environ["REVIVAL_ENABLE_SAFE_COMMANDS"] = "1"
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
        # Neighbor IDs are deliberately included in friendsInfo.
        # Only the signed-in identity (fb_sig_user) must stay separate.
        assert b"fb_sig_user=" + alice.encode() in a.get("/play.html").data
        assert b"fb_sig_user=" + bob.encode() not in a.get("/play.html").data
        assert b"fb_sig_user=" + bob.encode() in b.get("/play.html").data

        # Game templates must not leak old Facebook-looking access tokens or
        # emit malformed Ruffle string parameters.
        ruffle = a.get("/ruffle.html")
        assert ruffle.status_code == 200, ("ruffle", ruffle.status_code)
        assert b"parameters: {" in ruffle.data
        assert b"friendsInfo:" in ruffle.data
        assert b"accessToken: \\"revival-not-facebook\\"" not in ruffle.data or b"AAABbZ" not in ruffle.data
        assert b"AAABbZ" not in ruffle.data
        policy = a.get("/crossdomain.xml")
        assert policy.status_code == 200
        assert b'permitted-cross-domain-policies="none"' in policy.data
        assert b'domain="*"' not in policy.data

        endpoint = (
            "/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/"
            "srvempires/get_player_info.php"
        )
        from _revival.revival_gateway import _game_key
        with a.session_transaction() as sess:
            key_a = _game_key(alice, sess["revival_account_id"])
        with b.session_transaction() as sess:
            key_b = _game_key(bob, sess["revival_account_id"])
        base = {"language": "en", "client_id": "test"}
        assert a.post(endpoint, data={**base, "USERID": alice, "user_key": key_a}).status_code == 200
        assert b.post(endpoint, data={**base, "USERID": bob, "user_key": key_b}).status_code == 200
        assert a.post(endpoint, data={**base, "USERID": bob, "user_key": key_a}).status_code == 403
        assert a.post(endpoint, data={**base, "USERID": alice, "user_key": "123456789"}).status_code == 403

        # Other players may be visited but not inspect their private state.
        neighbor = a.post(endpoint, data={**base, "USERID": alice,
                                          "user_key": key_a, "user": bob, "map": "0"})
        assert neighbor.status_code == 200, ("neighbor", neighbor.status_code)
        other = neighbor.get_json()
        assert other["playerInfo"]["pid"] == bob
        assert "completedMissions" not in other["privateState"]
        unknown = a.post(endpoint, data={**base, "USERID": alice,
                                          "user_key": key_a, "user": "bad-neighbor", "map": "0"})
        assert unknown.status_code == 404

        command = endpoint.replace("get_player_info.php", "command.php")
        assert a.post(command, data={"USERID": alice, "user_key": key_a}).status_code == 400
        packet = "a" * 64 + ";" + json.dumps({"commands": [
            {"cmd": "name_map", "args": [0, "New Alpha Village"]},
            {"cmd": "buy", "args": [1, 60, 60, 0, 0, 0, 1, 0]},
            {"cmd": "collect_new", "args": [50, 58, 0, 19, 0, 1, 0]}
        ]})
        result = a.post(command, data={"USERID": alice, "user_key": key_a, "data": packet})
        assert result.status_code == 200, ("command", result.status_code, result.data[:400])
        # A repeat packet at the same location must be refused, not double-charge.
        assert a.post(command, data={"USERID": alice, "user_key": key_a,
                                     "data": packet}).status_code == 400
        assert b.post(command, data={"USERID": alice, "user_key": key_b,
                                     "data": packet}).status_code == 403
        assert a.post(command, data={"USERID": alice, "user_key": key_a,
                          "data": "a" * 64 + ";" + json.dumps({"commands": [
                              {"cmd": "win_bonus", "args": [1000000, 0, 0, 0, 0]}
                          ]})}).status_code == 400
        from sessions import session as village_session
        assert village_session(alice)["playerInfo"]["map_names"][0] == "New Alpha Village"
        assert village_session(alice)["maps"][0]["wood"] < village_session(bob)["maps"][0]["wood"]

        # Save files are valid JSON and retain distinct player identifiers.
        for pid in (alice, bob):
            village = json.loads((source / "saves" / f"{pid}.save.json").read_text())
            assert village["playerInfo"]["pid"] == pid
        assert not list((source / "saves").glob(".village-*.tmp"))
        assert not list((source / "saves").glob(".revival-*.tmp"))
        # Emulate an application restart's persisted-village reload.
        from sessions import load_saved_villages, session as current_village
        load_saved_villages()
        assert current_village(alice)["playerInfo"]["map_names"][0] == "New Alpha Village"
        assert current_village(bob)["playerInfo"]["map_names"][0] == "My Empire"
        print("PASS: real upstream imports, separate accounts, neighbor privacy, signed game APIs, validated purchases and saves")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()
    run(args.path)

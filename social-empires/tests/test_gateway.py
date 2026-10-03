"""Integration checks for the separate-account gateway; no game asset dependency."""

import importlib.util
import itertools
import os
import tempfile
import unittest
from pathlib import Path

from flask import Flask, request, session


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "revival_gateway", ROOT / "overlay" / "revival_gateway.py"
)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

GAME_PATH = "/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires"


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        overrides = {
            "REVIVAL_DB": str(Path(self.tmp.name) / "accounts.sqlite3"),
            "REVIVAL_SECRET_KEY": "alpha-secret-for-tests-not-deployment-000000000",
            "REVIVAL_REQUIRE_HTTPS": "0",
            "REVIVAL_ALLOWED_HOSTS": "localhost,127.0.0.1",
            "REVIVAL_ALLOW_UNVALIDATED_COMMANDS": "",
        }
        old = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)
        def restore():
            for key, previous in old.items():
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous
        self.addCleanup(restore)
        self.ids = itertools.count(1)
        self.app = self.make_app()
        self.client = self.app.test_client()

    def make_app(self):
        app = Flask(__name__)
        @app.route("/", methods=["GET", "POST"])
        def login():
            return "INSECURE LEGACY LANDING"
        @app.route("/new.html")
        def new():
            return "INSECURE LEGACY VILLAGE"
        @app.route("/play.html")
        def play():
            return "village=" + session["USERID"]
        @app.route("/ruffle.html")
        def ruffle():
            return "village=" + session["USERID"]
        @app.route(GAME_PATH + "/get_player_info.php", methods=["POST"])
        def get_player_info_response():
            return "user=" + request.values["USERID"]
        @app.route(GAME_PATH + "/command.php", methods=["POST"])
        def command_response():
            return "unsafe-game-command"
        gateway.install_revival(app, lambda: f"village-{next(self.ids)}")
        app.testing = True
        return app

    def token(self, client, page="/register"):
        response = client.get(page)
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as state:
            return state["revival_csrf"]

    def register(self, client, name, password="long-password-012345"):
        return client.post(
            "/register",
            data={"csrf": self.token(client), "username": name, "password": password},
        )

    def test_new_account_has_own_village_and_legacy_picker_disabled(self):
        self.assertEqual(self.client.post("/", data={"USERID": "victim"}).status_code, 405)
        self.assertEqual(self.client.get("/new.html").status_code, 404)
        self.assertEqual(self.register(self.client, "Alice").status_code, 303)
        self.assertEqual(self.client.get("/play.html").data, b"village=village-1")
        second = self.app.test_client()
        self.assertEqual(self.register(second, "Bob").status_code, 303)
        self.assertEqual(second.get("/play.html").data, b"village=village-2")

    def test_private_identity_enforced_on_game_api(self):
        self.register(self.client, "Alice")
        self.assertEqual(
            self.client.post(GAME_PATH + "/get_player_info.php", data={"USERID": "village-1"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(GAME_PATH + "/get_player_info.php", data={"USERID": "village-2"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(GAME_PATH + "/get_player_info.php", data={}).status_code,
            400,
        )
        other = self.app.test_client()
        self.assertEqual(
            other.post(GAME_PATH + "/get_player_info.php", data={"USERID": "village-1"}).status_code,
            401,
        )

    def test_game_commands_are_gated_by_default(self):
        self.register(self.client, "Alice")
        endpoint = GAME_PATH + "/command.php"
        self.assertEqual(self.client.post(endpoint, data={"USERID": "village-1"}).status_code, 503)
        self.assertEqual(self.client.post(endpoint, data={"USERID": "village-2"}).status_code, 403)

    def test_signin_signout_csrf_and_duplicate_names(self):
        self.assertEqual(
            self.client.post("/register", data={"username": "Alice", "password": "a" * 12}).status_code,
            400,
        )
        self.assertEqual(self.register(self.client, "Alice").status_code, 303)
        other = self.app.test_client()
        self.assertEqual(self.register(other, "ALICE").status_code, 409)
        self.assertEqual(self.client.post("/signout").status_code, 400)
        self.assertEqual(
            self.client.post("/signout", data={"csrf": self.token(self.client, "/signin")}).status_code,
            303,
        )
        self.assertEqual(self.client.get("/play.html").status_code, 302)
        token = self.token(self.client, "/signin")
        self.assertEqual(
            self.client.post("/signin", data={
                "csrf": token, "username": "Alice", "password": "bad-password-xxx"
            }).status_code, 401,
        )
        self.assertEqual(
            self.client.post("/signin", data={
                "csrf": token, "username": "Alice", "password": "long-password-012345"
            }).status_code, 303,
        )
        self.assertEqual(self.client.get("/play.html").data, b"village=village-1")

    def test_account_lookup_persists_across_gateway_recreation(self):
        self.register(self.client, "Alice")
        restarted_app = self.make_app()
        later = restarted_app.test_client()
        token = self.token(later, "/signin")
        self.assertEqual(later.post("/signin", data={
            "csrf": token, "username": "Alice", "password": "long-password-012345",
        }).status_code, 303)
        self.assertEqual(later.get("/play.html").data, b"village=village-1")

    def test_invalid_registration_and_weak_secret_fail_closed(self):
        self.assertEqual(self.register(self.client, "x").status_code, 400)
        self.assertEqual(self.register(self.client, "alice", password="short").status_code, 400)
        os.environ["REVIVAL_SECRET_KEY"] = "SECRET_KEY"
        with self.assertRaises(RuntimeError):
            self.make_app()


if __name__ == "__main__":
    unittest.main()

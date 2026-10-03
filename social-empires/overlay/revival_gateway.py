"""Account/session gateway for the original Social Emperors Flask application.

Security boundary: this is a *development* adapter. Upstream gameplay command
validation is incomplete; multiplayer Internet deployment is intentionally gated.
"""

from datetime import timedelta
import hashlib
import time
from html import escape
import hmac
import os
import re
import secrets
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort, g, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash


_USER_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,23}$")
_REGISTRATION_LOCK = threading.RLock()
_DYNAMIC_PREFIX = "/dynamic.flash1.dev.socialpoint.es/"
_GAME_VERSION = "SocialEmpires0926bsec.swf"


def _required_secret():
    key = os.environ.get("REVIVAL_SECRET_KEY", "")
    if len(key) < 32 or key in ("SECRET_KEY", "change-this-secret", "password"):
        raise RuntimeError("Set REVIVAL_SECRET_KEY to a strong random string (at least 32 characters)")
    return key


def _db_path():
    return Path(os.environ.get("REVIVAL_DB", "revival-data/accounts.sqlite3")).resolve()


def _connect():
    conn = sqlite3.connect(str(_db_path()), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _init_db():
    path = _db_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS accounts (
            account_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            village_id TEXT NOT NULL UNIQUE,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            disabled_at TEXT DEFAULT NULL
        )""")
        # Upgrade databases created before disabled_at existed.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
        if "disabled_at" not in columns:
            db.execute("ALTER TABLE accounts ADD COLUMN disabled_at TEXT DEFAULT NULL")


def _csrf():
    if "revival_csrf" not in session:
        session["revival_csrf"] = secrets.token_urlsafe(32)
    return session["revival_csrf"]


def _check_csrf():
    supplied = request.form.get("csrf", "")
    if not supplied or not hmac.compare_digest(_csrf(), supplied):
        abort(400, description="Invalid form token")


def _page(title, body, code=200):
    # Body is authored markup; all user-controlled substitutions are escaped.
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + escape(title) + '</title>'
        '<style>body{background:#15221e;color:#f5f5ec;font:16px system-ui;'
        'max-width:480px;margin:8vh auto;padding:1.5rem}'
        'input,button{font:inherit;padding:.7rem;margin:.4rem 0;width:100%;'
        'box-sizing:border-box}a{color:#addfc9}button{cursor:pointer}'
        '.error{color:#ffaeae}</style><h1>Social Empires</h1>'
        + body + '</html>', code,
        {"Content-Type": "text/html; charset=utf-8"},
    )


def _form(action, label, error="", status=200):
    token = escape(_csrf(), quote=True)
    feedback = '<p class="error">' + escape(error) + '</p>' if error else ""
    return _page(
        label,
        feedback + '<form method="post" action="' + action + '">'
        '<input type="hidden" name="csrf" value="' + token + '">'
        '<label>Username<input name="username" autocomplete="username" '
        'minlength="3" maxlength="24" required></label>'
        '<label>Password<input name="password" type="password" '
        'autocomplete="' + ("new-password" if action == "/register" else "current-password") +
        '" minlength="12" maxlength="128" required></label>'
        '<button type="submit">' + label + '</button></form>'
        + ('<a href="/signin">Sign in instead</a>' if action == "/register"
           else '<a href="/register">Create account</a>'),
        code=status,
    )


def _username(raw):
    if not isinstance(raw, str) or not _USER_RE.fullmatch(raw):
        return None
    return raw.casefold()


def _logged_in_account():
    account_id = session.get("revival_account_id")
    village_id = session.get("USERID")
    if not isinstance(account_id, int) or not isinstance(village_id, str):
        return None
    with _connect() as db:
        row = db.execute(
            "SELECT account_id, village_id, is_admin, disabled_at FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
    if row is None or row["disabled_at"] is not None or not hmac.compare_digest(row["village_id"], village_id):
        return None
    return row


def _game_key(village_id, account_id):
    payload = f"{account_id}:{village_id}".encode("utf-8")
    return hmac.new(_required_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def install_revival(app, create_village):
    """Attach account routes to an existing Flask app before it is served.

    This function replaces the upstream insecure village picker; no upstream
    admin endpoints are exposed or silently trusted.
    """
    app.secret_key = _required_secret()
    origin = os.environ.get("REVIVAL_PUBLIC_ORIGIN")
    if origin:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or origin.rstrip("/") != f"https://{parsed.hostname}"
        ):
            raise RuntimeError("REVIVAL_PUBLIC_ORIGIN must be an HTTPS origin without a path")
        allowed = set(os.environ.get("REVIVAL_ALLOWED_HOSTS", "").split(","))
        if parsed.hostname not in allowed:
            raise RuntimeError("Include REVIVAL_PUBLIC_ORIGIN hostname in REVIVAL_ALLOWED_HOSTS")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("REVIVAL_REQUIRE_HTTPS", "1") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        TRUSTED_HOSTS=[
            host.strip() for host in
            os.environ.get("REVIVAL_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
            if host.strip()
        ],
    )
    _init_db()

    @app.context_processor
    def revival_template_context():
        row = _logged_in_account()
        return {
            "csrf_token": _csrf(),
            "revival_game_key": _game_key(row["village_id"], row["account_id"]) if row else "",
        }

    @app.before_request
    def protect_game():
        path = request.path
        if path not in ("/play.html", "/ruffle.html", "/null") and not path.startswith(_DYNAMIC_PREFIX):
            return None
        row = _logged_in_account()
        if row is None:
            if path in ("/play.html", "/ruffle.html"):
                return redirect("/signin")
            abort(401, description="Authentication required")

        if path.startswith(_DYNAMIC_PREFIX):
            supplied_id = request.values.get("USERID")
            # Some telemetry endpoints report "user_id" instead of USERID.
            if supplied_id is None and path.endswith(("track_game_status.php",)):
                supplied_id = request.values.get("user_id")
            if supplied_id is not None and not hmac.compare_digest(str(row["village_id"]), supplied_id):
                abort(403, description="Village identifier mismatch")
            if supplied_id is None and not path.endswith(("track_game_status.php",)):
                abort(400, description="Missing village identifier")
            # Bind the legacy game API to a signed in-game session.
            if path.endswith(("/get_player_info.php", "/get_game_config.php",
                              "/command.php", "/get_continent_ranking.php")):
                provided = request.values.get("user_key", "")
                correct = _game_key(row["village_id"], row["account_id"])
                if not hmac.compare_digest(provided, correct):
                    abort(403, description="Invalid game session key")

            if path.endswith("/command.php") and (
                os.environ.get("REVIVAL_ENABLE_SAFE_COMMANDS") != "1"
            ):
                abort(503, description="Validated commands not yet enabled")
        return None

    if os.environ.get("REVIVAL_ENABLE_SAFE_COMMANDS") == "1":
        if "command_response" not in app.view_functions:
            raise RuntimeError("Unsupported upstream command endpoint")
        from revival_safe_commands import execute, PacketRejected
        from sessions import session as get_village_session
        from bundle import SAVES_DIR
        from get_game_config import get_item_from_id

        def validated_command():
            account = _logged_in_account()
            if account is None:
                abort(401)
            try:
                result = execute(
                    account["village_id"], request.values.get("data"),
                    get_village_session, get_item_from_id, SAVES_DIR, time.time,
                )
            except PacketRejected:
                return {"result": "error", "message": "Command rejected"}, 400
            return result, 200

        app.view_functions["command_response"] = validated_command

    def old_landing():
        if request.method != "GET":
            abort(405)
        return redirect("/play.html" if _logged_in_account() else "/signin")

    def old_new_village():
        abort(404, description="Register an account to start a village")

    # Original route entries remain but their handlers are replaced.
    if "login" not in app.view_functions or "new" not in app.view_functions:
        raise RuntimeError("Unsupported upstream server routes")
    app.view_functions["login"] = old_landing
    app.view_functions["new"] = old_new_village

    @app.route("/register", methods=["GET", "POST"])
    def revival_register():
        if request.method == "GET":
            return _form("/register", "Create account")
        _check_csrf()
        username = _username(request.form.get("username"))
        password = request.form.get("password", "")
        if username is None or not 12 <= len(password) <= 128:
            return _form("/register", "Create account", "Invalid username or password", status=400)
        with _REGISTRATION_LOCK:
            with _connect() as db:
                exists = db.execute(
                    "SELECT 1 FROM accounts WHERE username=?", (username,)
                ).fetchone()
                if exists:
                    return _form("/register", "Create account", "Username unavailable", status=409)
                # Password hashing and a new independent village are only created
                # after the duplicate-name check. Single-worker alpha deployment
                # is mandatory while upstream's save store remains in memory.
                hashed = generate_password_hash(password, method="scrypt")
                village_id = create_village()
                db.execute(
                    "INSERT INTO accounts(username,password_hash,village_id) VALUES(?,?,?)",
                    (username, hashed, village_id),
                )
                row = db.execute(
                    "SELECT account_id FROM accounts WHERE username=?", (username,)
                ).fetchone()
                account_id = int(row["account_id"])
            _activate(account_id, village_id)
        return redirect("/play.html", code=303)

    def _activate(account_id, village_id):
        session.clear()
        session["revival_account_id"] = account_id
        session["USERID"] = village_id
        session["GAMEVERSION"] = _GAME_VERSION
        session.permanent = True
        _csrf()

    @app.route("/signin", methods=["GET", "POST"])
    def revival_signin():
        if request.method == "GET":
            return _form("/signin", "Sign in")
        _check_csrf()
        username = _username(request.form.get("username"))
        password = request.form.get("password", "")
        if username is None or not password or len(password) > 128:
            return _form("/signin", "Sign in", "Invalid credentials", status=401)
        with _connect() as db:
            row = db.execute(
                "SELECT account_id, village_id, password_hash, disabled_at FROM accounts WHERE username=?",
                (username,),
            ).fetchone()
        if not row or row["disabled_at"] is not None or not check_password_hash(row["password_hash"], password):
            return _form("/signin", "Sign in", "Invalid credentials", status=401)
        _activate(row["account_id"], row["village_id"])
        return redirect("/play.html", code=303)

    @app.route("/signout", methods=["POST"])
    def revival_signout():
        _check_csrf()
        session.clear()
        return redirect("/signin", code=303)

    @app.route("/admin", methods=["GET"])
    def revival_admin():
        operator = _logged_in_account()
        if operator is None or operator["is_admin"] != 1:
            abort(403)
        with _connect() as db:
            rows = db.execute(
                "SELECT account_id, username, village_id, is_admin, disabled_at "
                "FROM accounts ORDER BY account_id DESC LIMIT 200"
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        csrf = escape(_csrf(), quote=True)
        cells = []
        for row in rows:
            # Admins may not disable themselves. No public administration
            # endpoint is exposed until the owner explicitly grants admin.
            can_change = row["account_id"] != operator["account_id"]
            disabled = row["disabled_at"] is not None
            control = ""
            if can_change:
                new_disabled = "0" if disabled else "1"
                action = "Enable" if disabled else "Disable"
                control = (
                    '<form method="post" action="/admin/account-state">'
                    '<input type="hidden" name="csrf" value="' + csrf + '">'
                    '<input type="hidden" name="account_id" value="' + str(row["account_id"]) + '">'
                    '<input type="hidden" name="disabled" value="' + new_disabled + '">'
                    '<button type="submit">' + action + '</button></form>'
                )
            cells.append(
                "<tr><td>" + escape(row["username"]) + "</td><td>" +
                escape(row["village_id"]) + "</td><td>" +
                ("Disabled" if disabled else "Active") + "</td><td>" + control + "</td></tr>"
            )
        body = (
            "<p>Accounts: " + str(total) + " (showing most recent 200). "
            "Administrative backups remain offline-only.</p>"
            '<table><tr><th>Player</th><th>Village</th><th>Status</th><th>Action</th></tr>' +
            "".join(cells) + "</table>"
        )
        return _page("Admin", body)

    @app.route("/admin/account-state", methods=["POST"])
    def revival_account_state():
        operator = _logged_in_account()
        if operator is None or operator["is_admin"] != 1:
            abort(403)
        _check_csrf()
        try:
            account_id = int(request.form["account_id"])
        except (ValueError, KeyError, TypeError):
            abort(400)
        disabled = request.form.get("disabled")
        if disabled not in ("0", "1") or account_id == operator["account_id"]:
            abort(400)
        with _connect() as db:
            row = db.execute("SELECT is_admin FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if row is None or row["is_admin"]:
                # Admins can be managed from the host machine only.
                abort(403)
            db.execute(
                "UPDATE accounts SET disabled_at=CASE WHEN ?='1' "
                "THEN CURRENT_TIMESTAMP ELSE NULL END WHERE account_id=?",
                (disabled, account_id),
            )
        return redirect("/admin", code=303)

    @app.route("/healthz", methods=["GET"])
    def revival_health():
        return {"ok": True}, 200

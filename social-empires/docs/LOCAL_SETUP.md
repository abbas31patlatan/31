# Local-only Social Empires revival test (development alpha)

**Never expose this alpha service publicly.** Account authentication is implemented,
but the original game commands still trust client-supplied reward, resource, and
XP inputs. Multi-worker and public deployments are not supported yet.

## Requirements

- Python 3.11+ and a system able to run the original Flash client.
- A working, authorized copy of the Social Emperors upstream
  https://github.com/AcidCaos/socialemperors
  source and required game assets. Game assets are **not** included here.
- This branch's social-empires directory.

Use an isolated virtual environment and a supported host OS. The Flash runtime
and third-party game assets need their own security and legal review.

## Patch a clean copy

Download or check out upstream source. Integration testing targets revision:
f642e0bae5a341f48e73b58f2e6d33a8436992c1. Keep a clean backup.

    python social-empires/tools/patch_upstream.py --path /path/to/socialemperors

A patch error means upstream changed or files are missing. Do **not** bypass
the verification by blindly replacing text. The patch installer is not
idempotent; restore a clean upstream copy to reapply it.

## Configure and run the local alpha

From the patched upstream's working directory:

    python -m pip install -r requirements.txt

Set environment variables before launching (the examples below show Bash;
use the corresponding PowerShell environment syntax on Windows):

    export REVIVAL_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    export REVIVAL_REQUIRE_HTTPS=0
    export REVIVAL_ALLOWED_HOSTS="localhost,127.0.0.1"
    export REVIVAL_DB="./revival-data/accounts.sqlite3"

To test construction, harvesting and normal game commands **only on a
trusted, local offline environment**:

    export REVIVAL_ALLOW_UNVALIDATED_COMMANDS=1

Then launch, from the original game's working directory:

    python server.py

Browse to http://127.0.0.1:5050/register using a vetted Flash-capable
environment. A new account gets a distinct village. Sign in with an existing
account at /signin. Existing villages are not automatically assigned to new
accounts: no secure migration tool exists yet.

Without REVIVAL_ALLOW_UNVALIDATED_COMMANDS, /command.php returns HTTP 503.
This is deliberate; the upstream economic and combat commands are not
server-authoritative. Do not use these insecure test settings through a
Cloudflare tunnel or from an untrusted network.

## Data

- Accounts: REVIVAL_DB (SQLite).
- Game progress: original upstream saves directory (one JSON per village),
  now replaced atomically to lower corruption risks.
- Database and villages **must be backed up together**. Do not commit saves,
  credentials, tokens, account data or game binaries.
- Only a **single server process** is supported. The game command lock covers
  threads within that one process, not cross-process coordination.

## Planned gates before any public launch

Command validation, transactionality across account and game state, unique
admin enrollment, abuse/rate limits, CSRF/origin review for Flash endpoints,
friend/attack privacy, data consistency and backups under concurrency, HTTPS,
proxy headers, runtime compatibility, and explicit rights for all assets.

REVIVAL_REQUIRE_HTTPS=1 and explicit REVIVAL_ALLOWED_HOSTS are needed for
HTTPS deployment, but setting those alone does **not** pass the gates.

## Offline operator controls

Create the owner's normal account via /register, then grant it the admin flag
from the hosting computer. This is deliberately NOT a public admin panel:

    python social-empires/tools/server_operator.py --db /path/to/accounts.sqlite3 grant-admin --username ownername

Stop the running game server before taking a complete backup. The command
requires explicit confirmation that the process is stopped:

    python social-empires/tools/server_operator.py --db /path/to/accounts.sqlite3 backup --saves /path/to/saves --output /safe/path/revival-2026.zip --server-stopped

This produces a local ZIP with an SQLite backup, matching village saves and
checksums. The archive contains personal account data and password hashes;
secure it privately and never commit or publish it. Restore is intentionally
manual until a verified restore test is implemented. Admin role is stored
but full in-game administration controls are still under development.

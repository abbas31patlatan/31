# Social Empires — online revival workspace

Status: **investigation and test harness; NOT multiplayer-ready**.

This project lives on an isolated branch of an existing GitHub repository. The original main branch is unrelated and must not be modified. The upstream [Social Emperors](https://github.com/AcidCaos/socialemperors) preservation project is the technical reference, **not** a production-ready multiplayer server.

## Objectives

1. Allow distinct users to register and sign in using independent credentials.
2. Keep each player's village private and durable across restarts.
3. Make player interactions and combat server-authoritative with meaningful validation.
4. Host the game service on the owner's computer, with an authenticated admin interface, backups, monitoring and safe deployment.
5. Support outside clients over HTTPS, without exposing unprotected internal endpoints.
6. Confirm that a viable Flash-compatible player and the required assets can be used legally and safely.

## Verified starting limitations

- Upstream server.py binds to 127.0.0.1:5050, and its play templates construct absolute HTTP URLs referencing that server.
- The login form chooses an existing USERID and saves it into the Flask session; that is **not** secure Internet-facing account authentication.
- sessions.py stores active saves in process memory and writes individual JSON files without concurrency-safe transactions. backup_session is a TODO.
- The Flash frontend includes legacy Facebook/Socialpoint-style endpoint paths. These must be mapped, isolated or replaced before public deployment.
- The upstream README documents local play rather than Internet-facing multiplayer.

These are verified code observations, **not** claims that every gameplay function is broken or that all mechanics have been restored.

## Development phases

- **P0 / audit**: inventory upstream routes, asset dependencies and game commands; establish a repeatable test baseline.
- **P1 / accounts**: unique accounts, password hashing, verified sessions, access controls, rate limiting and admin roles.
- **P2 / persistence**: database-backed villages, schema migrations, atomic saves, backups and recovery tests.
- **P3 / gameplay**: normalize multiplayer data paths; implement server-side validation, friend visits and battle consistency tests.
- **P4 / deployment**: local server hardening, trusted reverse proxy or tunnel, HTTPS, health checks, monitoring and restore drills.
- **P5 / acceptance**: two-device test with separate accounts, fresh villages, persistence across restart and repeatable friend/combat flows.

## Audit utility

From the workspace root, after obtaining an authorized local copy of the upstream source:

    python social-empires/tools/audit_upstream.py --path /path/to/socialemperors

Unit tests (do not need game assets):

    python -m unittest discover -s social-empires/tests -v

## Legal and safety considerations

Upstream's source is marked GPL-3.0; preserve the GPL obligations for copied or modified covered source. Its game artwork, SWF files, third-party Flash runtimes and trademarks may have distinct rights. Do not republish proprietary game assets without checking authorization. Never directly expose the alpha server to the public Internet.

See [initial audit](docs/INITIAL_AUDIT.md).
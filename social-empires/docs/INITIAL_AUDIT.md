# Initial technical assessment

Source reviewed: https://github.com/AcidCaos/socialemperors — publicly visible main branch at project inception.
Audit level: **source review only**. No local Flash runtime, browser, game session or multiplayer endpoint has been tested. Results are preliminary.

| Area | Observation | Risk | Next verification |
| --- | --- | --- | --- |
| Host & URLs | server.py sets host to 127.0.0.1 and port to 5050; play.html/ruffle.html interpolate SERVERIP into absolute HTTP asset/API requests | Remote players cannot reach the default instance; reverse proxy alone may not repair generated URLs | Isolate base URL and test remote browser + Flash request routing |
| Identity | POST / accepts a supplied USERID and GAMEVERSION and stores both in Flask session | Existing village identity can be selected from a list; unsuitable as Internet authentication | Implement accounts and authorize every player operation |
| Storage | sessions.py has a global save dictionary and JSON-per-village writes; backup_session has a TODO | Writes can race or be interrupted; process restarts/recovery need tests | Transactional data store, backup + restore drills, concurrency tests |
| Friend data | fb_friends_str derives other saved players/static villagers | Neighbor listings alone do not establish secure multiuser combat | Two-user interaction and authorization tests |
| Legacy API | server.py declares paths containing old Socialpoint hostnames | Legacy protocol conventions remain part of client interface | Enumerate route/command matrix; map current caller to handler |
| Flash | play.html embeds SWFs with legacy flashvars; ruffle.html uses Ruffle | Runtime compatibility and secure HTTPS/mixed-content behavior are unknown | Test representative browsers, versions and gameplay |
| External assets | server.py contains a fallback fetch to an older external CDN | Missing or unavailable assets may break loading; use rights review | Asset manifest and offline determinism checks |

## Release gate (all must pass before public exposure)

1. User A cannot read, impersonate, modify or delete User B's village.
2. Game commands authenticate users and validate resource consumption, rewards and time rules on the server.
3. Simultaneous saves do not lose progress; restart and backup-restore tests are repeatable.
4. Friend visits, combat, building, harvesting and synchronization work across distinct machines.
5. No client secrets are exposed; HTTPS and proxy trust are explicitly configured and audited.
6. Game assets and third-party client/runtimes are used under appropriate rights and conditions.

## Exclusions for this branch stage

No game binaries or captured credentials are included. No public service is running. This assessment must not be confused with a functioning online version.
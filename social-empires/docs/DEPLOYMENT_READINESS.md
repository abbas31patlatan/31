# Deployment and acceptance gates

**Current status: private/local ALPHA; public exposure prohibited.**

The original Flash game was designed around a discontinued backend,
browser runtime and asset URLs. GitHub Actions proves the server modules can
run with two distinct accounts, not that the complete Flash client or PvP
simulation works. Never advertise this as full Social Empires multiplayer.

## What the checks currently exercise

- Separate account registration, login, and hashed credentials.
- Owner-only read/disable/enable account administration (local CLI grants admin).
- Signed in-game API key and cross-user identity rejection.
- Neighbor visit with private state removed.
- Simple server-priced purchases, move, orient, map name and sale checks.
- Conservative harvest amounts from the original item definitions, with
  a **temporary** five-minute cooldown, not verified against all game rules.
- All-or-nothing command validation and atomic JSON saves.
- Save reload, login persistence, SQLite + village offline backup tests.
- HTML templates/Ruffle player.load argument rendering and deny-all Flash
  crossdomain.xml policy.

## Known launch blockers

1. **Combat**: server-driven troop stats, troop existence in an opponent's
   map, defenses, damage and reward accounting are not implemented.
2. **Full command coverage**: missions, gifts, skills, monsters, expansion,
   achievements, PvP rewards and original event triggers remain unvalidated.
3. **Exact time-based economy**: source assets don't specify all cooldown
   rules; current harvest delay is provisional.
4. **Map mechanics**: collision/footprint, placement prerequisites,
   tile unlock rules and traversal require work before trusting the public.
5. **End-to-end Flash testing**: SWF loader, plugin/FlashBrowser/Ruffle
   compatibility, interactions and renders are not tested in a real browser.
6. **Operations**: account/login throttling, single-process consistency,
   security logging, restore drills, load/stress testing and monitoring
   require additional validation.
7. **Rights**: third-party SWF, art, runtime, music and trademark publication
   rights are separate from the GPL-3.0 source license.

Until these are addressed and verified, **do not run a public server**.

## Preparation for local PC-hosted testing

1. Make a backup of the existing Social Emperors installation and saves.
2. Follow [LOCAL_SETUP.md](LOCAL_SETUP.md) using a clean upstream copy.
3. Give your own account admin with server_operator.py (only via local CLI).
4. Set REVIVAL_ENABLE_SAFE_COMMANDS=1 for the limited test mode.
5. Leave the service bound to 127.0.0.1:5050 and test two different
   browser sessions on the same trusted PC first.
6. Run server_operator.py backup with the process stopped; verify the ZIP
   can be read and the account/village manifest is consistent.
7. Run an actual Flash/Ruffle compatible browser and capture local HTTP
   and console logs if the loader, UI or a gameplay command fails.

## HTTPS origin design (not live yet)

Cloudflare Pages with its pages.dev address is suitable for a static web
front end but does not operate the game backend on your PC. A Cloudflare
Tunnel can securely forward a chosen HTTPS hostname to 127.0.0.1:5050 when
a stable hostname is available; this is **future deployment**, not an
instruction to expose the alpha now. If the tunnel is used for local and
restricted testing, include the assigned hostname in
REVIVAL_ALLOWED_HOSTS and configure REVIVAL_PUBLIC_ORIGIN with the complete
https://hostname address. Both game SWF and dynamic API endpoints should
remain on the same HTTPS origin to avoid mixed content and Flash policy
issues. Test cookies and proxy headers rather than trusting arbitrary
X-Forwarded-* inputs. Cloudflare authentication and abuse controls are
additional defenses, not substitutes for game-side verification.

## Release acceptance (all must be independently reproduced)

- Two new players can load the client on distinct devices and browsers,
  create villages and interact after a server restart.
- Prices, cooldowns, XP, quest payouts and battle outcomes are derived
  server-side and cannot be increased by modified client requests.
- No account can mutate or inspect another account's private state.
- PvP battles execute reliably with both outcomes and no duplicated prizes.
- Backups recover both villages with zero unexpected rollback.
- A reboot, disconnection, repeated requests or parallel clients cannot
  corrupt the database or produce free resources.
- Assets are properly licensed for the intended publication.

Do not call the server production-ready until all release gates pass.

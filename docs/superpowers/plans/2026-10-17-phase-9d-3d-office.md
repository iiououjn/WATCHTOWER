# Phase 9d: the 3D office (frontend only)

Branch `phase-9d-3d-office`, tag `phase-9d-3d-office`. Replaces the 2D canvas scene of 9c. Backend, audit, gates: unchanged.

## Goal
`watchtower dashboard` shows the tower as a real 3D lighthouse you can orbit and zoom. Every floor is a furnished office
(desks, chairs, monitors, shelves, racks, boardroom table...) with that floor's agents sitting at desks when awake and
wandering when idle. Job packets ride a lift between floors, deployed apps are boats with `127.0.0.1:<port>` text. The
backdrop switches between Scotland, Wales, Mumbai, Japan, Korea, USA, Dubai and open ocean, lit by a real-clock sky
(or a time slider), plus the owner's own panorama photos.

## Decisions
| Question | Ruling |
|---|---|
| 3D library | three.js 0.186.1 (MIT), vendored in `web/vendor/three/`, pinned by npm integrity and a `SHA256SUMS` file the tests check. No CDN, no runtime network. |
| "Real" backgrounds | I cannot ship photographs. Each place is built in 3D with its landmarks and lit physically (sky shader, IBL, shadows, water shader, bloom). True photographic backgrounds: the owner drops equirectangular images in `<home>/backdrops/` and they appear as places; the photo also lights the scene. |
| CSP | `script-src 'nonce-X' 'self'`, `img-src 'self'`. Only whitelisted `.js` under `web/` and verified image files under `<home>/backdrops/` are served (no decoding, no listing, no symlink out, magic-number check, size cap). |
| Untrusted text | Still only `textContent`/canvas `fillText`; tests ban `innerHTML` and friends across all app files. |
| Reactive | Page polls `/api/state` every 3 s (unchanged, cached server side); the scene reacts to each state. Push (SSE) deferred: it widens the threaded server's attack surface for little gain on loopback. |

## Files (each under 500 lines)
`web/app/`: `main.js` (renderer, loop, wiring), `tower.js` (island, shell, lantern, beam), `offices.js` + `furniture.js`
(floor themes and props), `people.js` (humanoids, walk/sit/type), `sky.js`, `water.js`, `envs.js` + `env_kit.js` +
`env_nature.js` + `env_cities.js` (places), `hud.js` (DOM controls), `logic.js` (pure rules), `util.js`.
`assets.py` (safe static + backdrop serving), `page.py` (import map, ledger drawer), `server.py` (routes, CSP).

## Verification
Tests: assets/traversal/symlink/oversize/magic-number, CSP, import graph resolves and is served, vendor hashes, banned
patterns, 500-line cap, node `--check` on every module, pure rules in node. By eye in the browser pane: every place, day
and night, a user panorama, hover tooltip, floor focus. Not covered by tests: the rendered look itself.

## Review focus
Anything a state string can reach besides `textContent`/`fillText`; the static/backdrop routes (traversal, symlinks,
type confusion, huge files); the `'self'` script allowance; GPU/CPU cost on an 8 GB Mac (shadow map, bloom, DPR cap 2).

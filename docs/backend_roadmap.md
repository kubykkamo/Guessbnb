# Guessbnb — Backend Roadmap

The journey from the current state (data layer + ETL only) to a running event-driven WebSocket backend. The phases are sequential, and each ends with something runnable and demonstrable.

Context: requirements in `Guessbnb.docx`, architecture in `Component.drawio` and `Sequential.drawio` (both diagrams have the raw Mermaid source embedded in the `mermaidData` attribute), alongside `UseCase.drawio` for roles and `Informational.drawio` for screens.

## Current State

The repository only contains the data layer and ETL:

- `src/models/` — pydantic v2 models `Listing`, `Photo`, `User`
- `src/repositories/` — raw async SQL over `aiosqlite`, module-level functions without classes
- `scraper.py` — sync ETL that deliberately bypasses the repository

Missing: entry point, web layer, WebSocket layer, tests, Dockerfile. The live DB has 2,000 listings across four cities and 12,777 photos.

The target architecture isn't a new design — `Component.drawio` maps it out: **FastAPI + WebSocket Manager with in-memory state, SQLite (aiosqlite/WAL), Auth0, Cloudflare R2, all in a single Docker container.** This roadmap just breaks it down into actionable phases.

## Decisions

| Area | Decision | Why |
|---|---|---|
| Scaling | Single process, in-memory room state. No Redis or broker. | `Component.drawio` maps the WS manager inside a single container. |
| | `Bus` abstraction (protocol), no direct calls. | Future switch to Redis pub/sub won't touch game logic. |
| | `uvicorn --workers 1` | More workers = more copies of the room registry = split games. |
| Game loop | Real-time, the server is the single clock. Round ends = all connected players guessed OR timer. | `Guessbnb.docx`: "system detects unexpected disconnects and prevents the game from freezing". |
| Durability | The game lives in RAM, a restart is allowed to kill it. Only the result is saved to `users.global_score`. | `src/models/__init__.py`: "The game itself lives only in RAM." |
| Scoring | `points = round(100 * exp(-2.3 * |guess-real| / real))` | See [Deviation from specs](#deviation-from-specs). |
| Map | `latitude`/`longitude` rounded to 3 decimal places (~100 m), `neighbourhood` is sent. | Exact fix is a price hint that local players could exploit. |
| Solo | Solo = a room where the host is the only player. No bots. | "Everyone submitted" simply narrows down to "you submitted", using the exact same state machine. |
| Auth | `DEV_AUTH` stub first, verifying Auth0 signature later. | Otherwise, an Auth0 tenant blocks every phase. |
| Tests | pytest from phase 1, priority is the game actor without a socket and without real clocks. | Race conditions can't be verified manually. |

Constants go to `src/config.py`:

```python
ROOM_CODE_LENGTH = 6      # wireframes show 5, RoomCode in ERD says 6 → 6, a constant is one line
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # excluding I, O, 0, 1
ROUNDS_RANGE = (3, 10)    # wireframe range, default 5 according to Sequential.drawio
MAX_PLAYERS = 10          # Connected players (3 / 10) from wireframes
ROUND_SECONDS = 30        # loop in Sequential.drawio
REVEAL_SECONDS = 8        # mock says "Next round in 5...", keeping 8s for reading
PRICE_BAND = (500, 20_000)
```

## Core: message-based actor

**One `asyncio.Task` per room, one `asyncio.Queue` for commands, the task is the only entity touching the state.** No locks, no shared mutable state, no `asyncio.gather` across game logic.

Most importantly: **the deadline is a message in the queue, not a callback.**

```python
while True:
    timeout = room.deadline - self.clock.now() if room.deadline else None
    try:
        cmd = await asyncio.wait_for(self.queue.get(), timeout)
    except TimeoutError:
        cmd = DeadlineReached(token=room.round_token)   # same path as a submitted guess
    events = await room.handle(cmd)
    await self.emit(events)
```

`handle()` is a pure function `Command -> list[Event]` that validates `room.phase` and `round_token` before computing anything. A round cannot be evaluated twice because a single task evaluates it, one message at a time. The side effect is the most useful part of this entire construct: game logic can be driven by direct `room.handle(cmd)` calls injecting a `FakeClock` — without sockets, without a DB, and without waiting 30 seconds.

The second fail-safe is `round_token`: each `round_started` gets a token, carried by both timers and guesses. A guess or timer carrying an old round's token is discarded, even if it arrives a millisecond after a state switch.

### Races it prevents

| Race | Prevention |
|---|---|
| Timer vs. late guess | Both are messages in the same queue, `handle()` checks `phase` and `round_token`. |
| Guess for an already finished round | `error: STALE_ROUND`, state doesn't change. |
| Disconnect mid-round | `PeerLeft` marks `connected=False` and **leaves the player in the roster** — score and previous guesses remain. The round only waits for connected players. Cleanup happens after a grace period or game end. |
| Reconnect | `resume {player_id, last_seq}` → replay from a circular buffer of the last ~200 events. If they slipped out, a full `room_state` snapshot is sent. |
| Empty room leaking forever | `RoomSupervisor` kills actors without players after a TTL and on `close_room`. |
| Double `start_game` | Transition is state-conditional → `error: INVALID_STATE`. |
| Host leaves mid-game | Host status transfers to the oldest connected player, the game doesn't end. |

### Room states

```text
LOBBY ──start_game──> STARTING ──> ROUND_OPEN ──all guesses / timer──> REVEALING
  ^                                                                        |
  |                     round < rounds_total                               |
  └──────────── restart_game <── GAME_OVER <── FINISHING <────────────────┤
                                        ^                                 |
                                        └──── last round ─────────────────┘
```

`start_game` and `set_settings` are only available in `LOBBY` and only for the host. `submit_guess` only in `ROUND_OPEN`. `REVEALING` closes itself after `REVEAL_SECONDS`, so the game doesn't get stuck waiting for the host; `next_round` shortens it on demand. Both `start_game` and `restart_game` work even for a single-player room — that's the entire solo mode.

## Protocol

Envelope: `{"t": "<type>", "seq": <int>, "data": {...}}`. Pydantic discriminated union on `t`, each field with `Field(..., ge=/le=/max_length=, description=)` like the rest of the project. `seq` is a monotonic room event number, used for `resume`. Wire times are epoch ms integers, not ISO strings — so the frontend doesn't have to parse SQLite's `strftime` format.

### Commands client → server

| `t` | Payload | Auth / state |
|---|---|---|
| `create_room` | `{display_name, token?}` | anyone |
| `join_room` | `{code, display_name, token?}` | anyone, `phase == LOBBY` |
| `resume` | `{player_id, token, last_seq}` | player already seated |
| `set_settings` | `{city, rounds}` | host, `LOBBY` |
| `start_game` | `{}` | host, `LOBBY` |
| `submit_guess` | `{round, price}` | player, `ROUND_OPEN`, `round == round_token` |
| `next_round` | `{}` | host, `REVEALING` |
| `leave_room` | `{}` | player, any state |
| `close_room` | `{}` | host, any state |
| `token_refresh` | `{token}` | login mid-game |

### Events server → client

| `t` | Payload |
|---|---|
| `room_joined` | `{you: {player_id, role, display_name}, room_state}` |
| `lobby_updated` | `{players[], settings}` |
| `game_started` | `{rounds_total, city}` |
| `round_started` | `{round_no, rounds_total, listing: ListingPublic, photos[], deadline_ms, round}` |
| `guess_ack` | `{round_no}` — just confirmation the guess arrived |
| `guess_count` | `{n, of}` — how many submitted, not the values |
| `round_ended` | `{actual_price, results[], standings[]}` |
| `game_finished` | `{standings[], persisted}` |
| `player_joined` / `player_left` / `player_reconnected` | `{player_id, display_name}` |
| `room_closed` | `{reason}` |
| `error` | `{code, message}` |

`guess_count` intentionally omits guess values — otherwise, it would leak where the rest of the room is aiming mid-round.

Close codes: `4003` room already running (client gets a "game in progress" screen, not a kick), `4004` room full, `4008` invalid token.

## Deviation from specs

`Sequential.drawio` and `Guessbnb.docx` dictate `abs/real * 100`. As the formula is written, **this is an error margin in percent, not points** — it grows beyond 100% indefinitely, meaning:

- the least accurate player wins the round and the whole game (guess 30,000 for a 1,000 flat = 2900),
- the dominant strategy is to always guess 1 CZK, because the error is always just under 100%,
- ties are frequent and impossible to break.

Therefore, points are calculated as `round(100 * exp(-2.3 * |guess-real| / real))` — finite within 0–100, monotonically decreasing, never zero, so even a bad guess can be ranked.

| guess | real | displayed error | points |
|---|---|---|---|
| 1000 | 1000 | 0.0 % | 100 |
| 1100 | 1000 | 10.0 % | 79 |
| 1300 | 1000 | 30.0 % | 50 |
| 700 | 1000 | 30.0 % | 50 |
| 2000 | 1000 | 100.0 % | 10 |
| 1 | 1000 | 99.9 % | 10 |

Symmetry is intentional: overvaluing by 30% costs the same as undervaluing by 30%.
`abs/real*100` from the diagram remains as the displayed percentage error, so the mandated calculation is visible in the game — it just doesn't yield the score. No guess = 0 points for the round.

## What is missing in the current code

1. **`price` is a secret.** `Listing` contains it and the model is used everywhere, so any `model_dump()` on the socket leaks the game result. We'll introduce `ListingPublic(ListingCreate)` without `price` — we will not filter dicts at the socket layer.
2. **Game core query is missing.** "N random listings in city X, each with a photo" doesn't exist in `listing_repository.py` and `list_listings` has no city filter at all. The SQL only lives as a one-liner in `README.md:200`. We will add `draw_listings(conn, city, count, price_band)`. Listings for the entire game are drawn **once at startup**, not per round.
3. **Price outliers.** The data contains prices over 1,158,408 CZK/night. The `price BETWEEN 500 AND 20_000` band drops 54 out of 2,000 listings, including all castles. If we want an exceptionally luxurious round, the right shape is a weighted draw with a "wildcard round", not removing the band entirely.

## Phases

### F0 — runnable skeleton

**Add:** `requirements-dev.txt`, `src/config.py`, `src/api/{__init__,main}.py`
**Change:** `requirements.txt` (`fastapi`, `uvicorn[standard]`, `httpx`, `PyJWT[crypto]`, `cachetools`; to dev `pytest`, `pytest-asyncio`, `websockets`)

FastAPI app whose lifespan owns `await connect()` from `src/repositories/db.py` on `app.state.conn` — no pool or session factory, `db.py` handles it this way deliberately. Room registries and `RoomSupervisor` on `app.state` as well. `GET /healthz`, `GET /api/cities`.

*Demo:* `uvicorn src.api.main:app --workers 1` → `/healthz` returns 200.
*Acceptance:* `/api/cities` returns Berlin, London, New York, Prague from the live DB.

### F1 — pure actor, no sockets

The riskiest part right away, while it's cheap to rewrite. **No WebSockets.**

**Add:** `src/game/{__init__,state,scoring}.py`, `tests/{conftest,test_state,test_scoring}.py`, `pytest.ini`

`Room` as `@dataclass`, `Phase` enum, `handle(cmd) -> list[Event]`. `FakeClock` with `now()`/`advance()`. Fixture `seed_listings` builds the DB via `db.connect(":memory:")` — `data/` is in `.gitignore`, so tests must never touch the live DB.

*Acceptance:*
- two players submit → round evaluates
- only one submits and `clock.advance(30)` → round evaluates **exactly once** and the other gets 0
- `submit_guess` with an old round's `round` → `STALE_ROUND`, score doesn't change
- second `start_game` → `INVALID_STATE`
- property test on `scoring`: points are always in 0–100 and decrease as deviation increases
- submission + deadline in the exact same ms → round evaluates once

### F2 — transport and lobby

**Add:** `src/api/ws.py`, `src/game/{bus,protocol}.py`, `tests/test_ws_lobby.py`

`/ws` endpoint, envelope codec, connection registries, `InProcessBus` (per-room list of queues, one per connection). `create_room`, `join_room`, `set_settings`, `leave_room`, `close_room`, `lobby_updated`.

*Demo:* two `websocat` windows see each other in the same lobby via room code.
*Acceptance:* host sees `player_joined`, closing connection yields `player_left`; `set_settings` from host changes city and rounds; from non-host or from host in `ROUND_OPEN` returns `error` without crashing the game; joining an already running room gets `4003`.

### F3 — orchestrated real-time game

**Add:** `src/game/{room,selection}.py`, `src/models/listing_public.py`, `tests/test_game_flow.py`
**Change:** `src/repositories/listing_repository.py` (adding `draw_listings`, existing functions untouched)

Actor loop with `loop.call_at` timer and `round_token`. `start_game` → `draw_listings`, `round_started` / `submit_guess` / `guess_count` / `round_ended`, `ListingPublic`.

*Demo:* a five-round game where round 1 closes after ~4s because everyone submitted, round 2 runs the full 30s, evaluation switches automatically, and final standings appear without clicking.
*Acceptance:* **total SQL queries for the whole game = 2** (assert via a counting wrapper around the connection), no listing repeats within a game, late guess is rejected.

### F4 — chaos resilience

**Add:** `scripts/soak.py`, `tests/{test_resume,test_no_price_leak}.py`
**Change:** `src/game/room.py` (reconnect, grace period, host transfer, cleanup)

`resume` + `seq` + circular buffer, disconnect doesn't block the round, `RoomSupervisor` cleans up idle rooms, host status transfers. `soak.py` spins up 10 rooms × 6 clients using stdlib `websockets`.

*Demo:* kill one client mid-round, the game continues; they return and `resume` puts them in the correct state.
*Acceptance:* soak runs with 0 duplicate `seq` and 0 gaps, RSS growth under ~5 MB per room; price-leak test green.

### F5 — game over, results, "Play again"

**Add:** `src/repositories/game_result_repository.py`, `tests/test_persistence.py`
**Change:** `src/repositories/{schema,user_repository}.py`, `src/game/state.py`, `src/api/{ws,rest}.py`

Two new tables (`game_result`, `game_result_player`) — new tables are safe according to the migration policy in `schema.py`, no `ALTER` statements. `record_results` writes multiple queries in a single commit and is idempotent via `(room_code, game_no)`. `add_global_score` uses `UPDATE users SET global_score = global_score + ?` instead of read-modify-write via `update_user`. `GET /api/leaderboard`. A logged-in guest mid-game receives `token_refresh` and their seat is upgraded so the whole game is saved, not just the remainder.

*Acceptance:* `global_score` is an exact sum of round points (integer, no drift); repeated write of the same game changes nothing; host's "Play again" returns the whole room to the lobby with the same players; host leaves mid-game and the game continues with a new host; host's `close_room` closes the room and disconnects everyone; a host without `auth0_id` doesn't get persisted to the DB.

### F6 — Auth0 + deployment

**Add:** `src/api/auth.py`, `Dockerfile`, `.dockerignore`, `tests/test_auth.py`
**Change:** `src/api/{main,deps,ws}.py`, `requirements.txt`, `README.md`

Auth0 signature verification using `PyJWT[crypto]`, `cachetools.TTLCache` for JWKS (10 min), `kid` rotation without restart, `alg: none` rejected. `DEV_AUTH` is toggleable and must reject `X-Dev-User` in prod. Message rate limiting per connection, `Origin` allowlist. `SIGTERM` handler: broadcast `room_closed{server_shutdown}`, one attempt to flush pending results, cancel timers, close connection. `Dockerfile` on python:3.11-slim, non-root user, `--workers 1` directly in `CMD`.

*Acceptance:* real Auth0 token passes, expired token returns an error and `optional_identity` logs a warning; `docker stop` mid-round delivers `room_closed` to everyone and container exits with 0; `--workers 1` is visible in `docker inspect`; nothing from `data/` is in the image; `/healthz` is green within 2s of startup.

## What breaks existing conventions

Intentionally, to avoid surprises:

| | |
|---|---|
| `class Room`, `@dataclass`, `enum`, `Protocol` under `src/game/` and `src/api/` | The "no classes" rule only applies to `src/repositories/` — that remains 100% class-free. |
| New directories `src/api/`, `src/game/`, `tests/`, `scripts/` | Maps 1:1 to the two server boxes in `Component.drawio`. |
| `requirements.txt` goes from 4 to ~8 lines, first-time `requirements-dev.txt` and `pytest.ini` | The project currently has no tooling or dev/prod split. |
| `record_results` is not a `create/get/list/update/delete` quintet and batches queries into one commit | Precedent exists: `scraper.py:310` `insert_listing`. Reads remain commit-free. |
| `add_global_score` bypasses `update_user` | Read-modify-write drops concurrent writes. Unacceptable for scores. |
| `ListingPublic` is a read model, not a table row | `models/__init__.py` will adjust `__all__` accordingly. |
| We consciously **are not introducing** a `transaction()` unit-of-work wrapper over existing repositories | A deferred decision, not an oversight. We'll revisit once the game works. |

Intentionally preserved: Czech docstrings and comments in all new modules, `Field(..., ge=/le=/max_length=, description=)` on every wire model, `conn: aiosqlite.Connection` as the first parameter of all new repository functions, `SELECT *` + `Model(**dict(row))` for reads, migration policy as a document in `schema.py`.

## Risks and open questions

1. **`--workers 1` is a hard ceiling.** The day will come when this runs on a server and someone tries `--workers 4`. Let's document this in README and the `main.py` docstring.
2. **Scoring contradicts the assignment.** `Guessbnb.docx` is the authoritative document and dictates `abs/real*100`. The reasoning for the deviation is detailed above.
3. **Auth0: access token, or ID token?** The plan assumes an API identifier (`https://api.guessbnb.local`) and the SPA sends an `access_token` with an `aud` targeting it. If the SPA lacks a configured audience (default Auth0 SPA behavior), it sends an ID token with `aud = client_id` and every validation will fail. Decide before F6 — it's 10 minutes of work then, but a lost afternoon if found during testing.
4. **No durable write retries.** If the write fails at the end of the game, points are lost (players see them, the leaderboard doesn't). The correct fix is an outbox table, which violates the "game only in RAM" rule. We prioritized the game over the leaderboard; at least `game_finished{persisted: false}` will declare it loudly.
5. **Public leaderboard shows usernames.** `users.username` has no unique index or content moderation — today, two people can be named `You`. The name also comes from an Auth0 claim we don't control. The bare minimum is uniqueness + length constraint, but that's not a task for the backend itself. Guest names are never persisted.
6. **Single shared `aiosqlite` connection serializes DB work for all rooms onto a single thread.** Harmless at 2 queries per game — specifically because of the upfront batch draw. Escape hatch if queries slow down: a second read-only connection just for draws. Do not implement it yet.
7. **`scraper.py` is sync and shares `DB_PATH`** with the API. WAL handles it, but running the ETL during games can trigger `database is locked`. We assume the ETL is run offline — this maps to the Admin role in `UseCase.drawio`.
8. **No lint, type checker, or CI.** Phases only add pytest. `ruff` + `mypy` is cheap, but would flag things in existing repositories (`Listing(**dict(row))` is fundamentally untypable), so omitting them is a conscious standalone decision, not part of a phase.
9. **`data/` is in `.gitignore`** — any future CI must build fixtures via `db.connect(":memory:")`, never against the live DB.

## Verification

In this order, after completing F6 entirely:

1. `pytest` — actor tests (fake clocks, no sockets) fail whenever a round is evaluated twice or a guess is lost. Price-leak test verifies the absence of `price` in all outbound messages.
2. `uvicorn src.api.main:app --workers 1` + two WebSocket clients: create room → join via code → start → 2 rounds → `game_finished`. The script stays in `scripts/play_demo.py` and serves as manual acceptance for every subsequent phase.
3. Query `users.global_score` after the game and **again after a process restart** — the value must survive. This is the entire consequence of the "RAM only for game" rule.
4. `GET /api/leaderboard` matches the DB query and the guest isn't in it.
5. Kill a client mid-round: the game finishes without them, `resume` puts them back in state.
6. `python scripts/soak.py` — 10 rooms × 6 clients, 0 duplicate `seq`.
7. `docker build` + `docker run` + step 2 inside the container; `docker stop` mid-round.
# ARCHITECTURE

## Purpose

This document describes how the current NBA Playoff Pool implementation is structured in code and how the major runtime behaviors work.

The app is intentionally designed around:

1. deterministic scoring
2. commissioner control
3. recoverability
4. simple operations for a small private pool

## High-level architecture

The application is a server-rendered FastAPI app with four main domains:

- web and route orchestration
- deterministic scoring
- background automation
- recovery/export

### Request flow

1. browser sends request
2. FastAPI route resolves membership/session
3. route loads pool context from the database
4. deterministic scoring recomputes the current leaderboard
5. Jinja template renders the requested tab

### Background flow

1. APScheduler runs `process_windows`
2. eligible open boards get Monkey submissions if needed
3. expired windows are automatically locked and revealed
4. provider health status is recorded as a system result snapshot

## Main modules

### `app/main.py`

Primary orchestration layer.

Responsibilities:

- FastAPI app lifecycle
- route definitions
- session and role gating
- pool context building for templates
- bracket generation
- commissioner operations
- bulk player save flow
- bulk result save flow
- matchup/player detail pages

Important helper behaviors:

- `parse_iso_datetime`
  parses commissioner-entered datetimes as `Asia/Jerusalem`, then stores them in UTC
- `localize_datetime_input`
  formats stored timestamps back to Israel time for datetime inputs
- `load_pool_context`
  auto-locks expired windows before building the page context

### `app/domain/scoring.py`

Pure scoring layer.

Responsibilities:

- converts windows, submissions, and result snapshots into player state
- scores early picks, play-in, and playoff series
- applies exact-result bonuses
- applies tiebreak ordering
- computes projected ceiling
- normalizes timestamps for stable ordering

This module is the scoring source of truth. The app does not persist a mutable leaderboard.

### `app/models.py`

SQLAlchemy persistence model.

Tables:

- `Pool`
- `User`
- `Membership`
- `InviteLink`
- `BettingWindow`
- `PickSubmission`
- `ResultSnapshot`
- `EventLog`
- `PaymentLedgerEntry`

### `app/db.py`

Database bootstrap and session management.

Responsibilities:

- initialize SQLAlchemy engine/session
- normalize `postgres://` and `postgresql://` URLs to `postgresql+psycopg://`
- support SQLite and PostgreSQL

### `app/auth.py`

Cookie-backed membership session handling.

Implementation details:

- session cookie stores signed membership ID data
- signing uses `itsdangerous`
- the app authenticates a viewer to a pool through their `Membership`

### `app/services/automation.py`

Scheduler automation layer.

Responsibilities:

- Monkey auto-submission for newly available boards
- automatic lock/reveal of expired windows
- provider health snapshots

Important detail:

- the same auto-lock behavior is also called from request-time code, so expired windows do not stay open just because the scheduler has not run yet

### `app/services/recovery.py`

Recovery/export layer.

Responsibilities:

- bundle export
- workbook export
- CSV export
- JSON snapshot restore into a recovered pool

### `app/services/provider.py`

Light provider integration surface.

Current state:

- BallDontLie adapter exists
- provider healthcheck exists
- live provider sync is not the active source of truth in the current manual-mode app

### `app/data/nba_catalog.py`

Static catalog for:

- NBA teams
- conference membership
- current manual roster options used by dropdowns

This is the app’s active source for teams and players today.

## UI architecture

The app is server-rendered with Jinja templates.

### `app/templates/base.html`

Defines:

- global look and feel
- shared utility classes
- bracket board styling
- responsive layout shell

### `app/templates/index.html`

Landing page for:

- creating a pool
- listing existing pools

### `app/templates/invite.html`

Join page for invited players.

### `app/templates/pool.html`

The main dashboard template.

Tabs:

- `Overview`
- `Closed Bets`
- `Bracket`
- `Commissioner`

### `app/templates/player.html`

Player detail page.

Shows:

- leaderboard stats
- score breakdown table
- visible revealed picks
- boards still waiting on this player

### `app/templates/matchup.html`

Per-matchup revealed pick table.

## Domain model

## Pools and membership

- a pool has one commissioner and multiple players
- each viewer is authenticated by `Membership`
- one Monkey membership exists in every pool

## Betting windows

A `BettingWindow` is the prediction container used by both players and commissioners.

Window types:

- `early`
- `play_in`
- `series`

Shared properties:

- `opens_at`
- `locks_at`
- `is_locked`
- `is_revealed`
- `round_key`
- `config`
- `monkey_seed`

## Series structure

Series-like windows store one or more matchup definitions in `config["series"]`.

Each matchup can include:

- `series_key`
- `round`
- `conference`
- `label`
- `teams`
- `slots`
- `best_of`
- `exact_results`

`slots` drive the bracket resolution behavior.

Slot types currently used:

- `team`
- `seed`
- `winner_of`
- `loser_of`
- `play_in_seed`

## Render-time bracket state

At context-build time, each window gets `render_series`.

Each render series contains:

- resolved `teams`
- `resolved` boolean
- `team_details`
  includes:
  - abbreviation
  - display name
  - logo URL
  - seed text where applicable

This lets the UI show:

- real teams when known
- placeholders when unresolved
- seed labels like `7th`, `8 seed`, `Winner 9/10`

## Results model

Results are append-only snapshots.

Supported scopes:

- `early / season`
- `series / <series_key>`
- `system / provider_health`

The latest snapshot for a scope is treated as current truth when scoring is recomputed.

## Event model

The app writes `EventLog` rows for major actions such as:

- pool created
- player joined
- picks submitted
- window created
- window locked
- window reopened
- window schedule updated
- window deleted
- bracket generated
- results posted
- member renamed
- member deleted
- pool deleted
- monkey submitted

This supports auditability and recovery analysis.

## Bracket architecture

## Bracket generation

The commissioner supplies:

- East seeds 1-10
- West seeds 1-10
- open time
- lock time

The app generates:

- East 7 vs 8 play-in
- East 9 vs 10 play-in
- East 8-seed decider
- West 7 vs 8 play-in
- West 9 vs 10 play-in
- West 8-seed decider
- East Round 1
- West Round 1
- East Round 2 placeholders
- West Round 2 placeholders
- East Conference Finals
- West Conference Finals
- NBA Finals

## Bracket progression

Downstream windows use slot references to prior series.

When a result is saved:

1. the result snapshot is written
2. downstream windows are revisited
3. if both required participants are now known, the placeholder teams are materialized
4. Monkey auto-picks can then be generated for newly resolved windows

## Bracket presentation

The current bracket tab is a visual board with:

- West Play-In lane
- central playoff path
- East Play-In lane

It uses full-width bracket styling and seed labels for play-in and round-one matchups.

## Scheduling and timezone behavior

The app uses `Asia/Jerusalem` for commissioner-facing datetime inputs.

Input lifecycle:

1. commissioner enters local Israel time
2. app parses that input as `Asia/Jerusalem`
3. timestamp is stored in UTC
4. when rendered back into the form, the UTC value is converted back to Israel local time

Auto-lock behavior is enforced by:

- background scheduler
- request-time `load_pool_context`
- request-time player submission routes

That means a board cannot remain open after deadline just because the scheduler has not fired yet.

## Monkey behavior

One Monkey exists per pool.

Current behavior:

- submits early picks when the pool is created
- submits manual windows immediately when the board is eligible and both teams are known
- submits generated windows as the bracket resolves
- uses deterministic randomness based on the stored `monkey_seed`

## Recovery architecture

The app supports operational recovery through bundle export.

Artifacts:

- `snapshot.json`
- CSV files
- `fallback_workbook.xlsx`

`snapshot.json` is the authoritative restore input.

Restore behavior:

- creates a new recovered pool
- rehydrates pool state from the exported snapshot

## Deployment model

The app supports:

- local SQLite development
- Docker deployment
- Railway deployment with PostgreSQL

For Railway:

- Postgres URLs are normalized for SQLAlchemy/psycopg
- `/health` is used as the liveness check

## Known architectural constraints

- most logic currently lives in `app/main.py`; the app favors delivery speed and explicitness over heavy service abstraction
- live NBA provider sync is not the current source of truth
- the app depends on remote logo URLs rather than bundling local assets
- SQLite can return naive datetimes, so helper functions normalize them explicitly

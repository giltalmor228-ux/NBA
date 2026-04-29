# PROJECT GUIDE

## Product overview

`NBA Playoff Pool` is a private web app for running a playoff prediction competition for a small group of friends.

The current implementation is built for manual operation by a commissioner and includes:

- invite-only pool management
- commissioner and player roles
- one automated Monkey bot participant
- early picks
- play-in winner boards
- best-of-seven playoff series boards
- seeded bracket generation through the NBA Finals
- revealed bets and matchup tables
- detailed player pages
- backup and recovery tooling

## Product principles

The app is optimized for:

1. trust in the scoring
2. easy commissioner operations
3. continuity if the app needs recovery

## Main screens

## Home page

Used for:

- creating a new pool
- opening existing pools

## Invite page

Used for:

- joining a pool with nickname, email, and avatar

## Pool dashboard

The dashboard has four tabs.

### Overview

Shows:

- live standings
- projected ceiling
- first-place spotlight message
- active betting boards
- tie-break rules
- full scoring rules

Player-specific behavior:

- players can bulk-save all marked boards together
- if a board already has a pick, a banner says so
- if a board is locked, save attempts stay on the page and show an error message

### Closed Bets

Shows revealed picks only.

Includes:

- early picks as a table
- revealed matchup picks as tables
- point breakdown per matchup when results are posted

### Bracket

Shows:

- West Play-In
- East Play-In
- West Round 1
- East Round 1
- West Semifinals
- East Semifinals
- Conference Finals
- NBA Finals

The bracket uses seed labels for play-in and first-round lanes and resolves future matchups as results are posted.

### Commissioner

Used for:

- creating manual windows
- generating a seeded bracket
- posting early-pick season results
- bulk-saving official game/series results
- locking and reopening boards
- updating open/lock schedule times
- deleting windows
- renaming players
- removing players
- deleting the whole pool
- viewing the commissioner-only audit feed

## Roles

## Commissioner

The commissioner can:

- create and manage the pool
- generate playoff windows from seeded standings
- create manual boards
- update schedule times for any board
- lock or reopen a board
- delete a board
- post official results
- rename players
- remove players
- delete the pool

## Player

A player can:

- join via invite link
- submit picks in open windows
- bulk-save marked picks
- view standings
- view the bracket
- view revealed bets after lock/reveal
- view player detail pages

## Monkey

The Monkey:

- is created automatically in every pool
- participates as a normal entrant
- auto-submits when an eligible board becomes available
- uses deterministic random choices from `monkey_seed`

## Competition structure

## Early Picks

One board covering:

- East conference finalist
- West conference finalist
- East NBA finalist
- West NBA finalist
- NBA champion
- Finals MVP

## Play-In boards

Single-game winner boards for:

- 7 vs 8
- 9 vs 10
- No. 8 seed decider

## Playoff series boards

Best-of-seven boards for:

- Round 1
- Round 2
- Conference Finals
- NBA Finals

Each series board uses:

- winner
- total games

The scoring engine converts total games into an exact-result string internally.

For playoff series, the exact-result value is the total score for a perfect series call before any exact-result bonus is added.

## Typical commissioner workflow

## 1. Create the pool

When the commissioner creates a pool, the app also creates:

- commissioner user and membership
- Monkey user and membership
- invite link
- initial `Early Picks` window

## 2. Share the invite

Players join through the invite URL and receive a cookie-backed membership session.

## 3. Build the competition structure

The commissioner can either:

- create manual boards
- or generate the seeded bracket from top-10 conference standings

## 4. Adjust board schedule

In `Commissioner -> Window controls`, the commissioner can set:

- start time
- stop/lock time

The app treats these as Israel local time in the UI and stores them in UTC.

## 5. Let players submit picks

Players use the Overview page to mark multiple picks and save them together.

## 6. Lock/reveal boards

Boards can be locked:

- manually by the commissioner
- automatically by deadline

Once locked:

- new picks are rejected
- the board becomes revealed
- it moves into the revealed-bets experience

## 7. Post official results

Commissioner posts:

- early season results
- play-in winners
- playoff series outcomes

When results are posted:

- scores update
- downstream bracket placeholders resolve if both participants become known

## 8. Review standings and pages

The app updates:

- live standings
- player pages
- matchup tables
- bracket progression

## Bracket generation details

The commissioner enters the top 10 seeds from each conference.

The app generates:

- East and West play-in structure
- Round 1
- Round 2 placeholders
- Conference Finals placeholders
- NBA Finals placeholder

As upstream winners become known, downstream series receive their real teams automatically.

## Scheduling behavior

The schedule editor is located in `Commissioner -> Window controls`.

Rules:

- open time must be before lock time
- the UI uses Israel local time
- boards auto-lock once `locks_at` has passed
- request-time auto-lock protection prevents late submissions even if the scheduler has not ticked yet

## Scoring overview

See [RULEBOOK.md](./RULEBOOK.md) for the full rules.

Summary:

- Early Picks: 16 max points
- Play-In: winner only
- Series boards: weighted by round
- exact-result bonus based on how many players hit the exact result
- final standings use tiebreakers

## Player detail page

A player page shows:

- standings stats
- score breakdown summary table
- visible revealed picks
- boards still waiting on that player

## Recovery and continuity

Commissioners can export a recovery bundle containing:

- `snapshot.json`
- CSV files
- `fallback_workbook.xlsx`

The JSON snapshot is the restore source of truth.

## Current manual-mode assumptions

The app currently operates in manual mode for competition data.

That means:

- team and roster options come from the in-repo catalog
- BallDontLie adapter exists, but live sync is not the active source of truth
- official results are posted by the commissioner

## Testing strategy

### Unit/integration tests

Run:

```bash
.venv/bin/pytest -q
```

### Real-flow smoke test

Run:

```bash
.venv/bin/python scripts/smoke_new_features.py
```

The smoke test checks:

- pool creation
- invite/join
- bracket generation
- player bulk pick save
- locked-bet error behavior
- commissioner bulk result save
- saved-result badges
- member management
- pool deletion

## Deployment summary

### Local

```bash
uvicorn app.main:app --reload
```

### Docker

```bash
docker compose build
docker compose up -d
```

### Railway

- deploy via Dockerfile
- set `/health` as the healthcheck
- set the required env vars
- use Railway Postgres if you want managed Postgres

## Where to read next

- [README.md](./README.md)
- [RULEBOOK.md](./RULEBOOK.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)

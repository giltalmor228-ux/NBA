# PROJECT GUIDE

## Overview

`NBA Playoff Pool` is a private FastAPI web app for running an NBA postseason prediction league.

The app supports:

- invite-only pools
- commissioner and player roles
- early-pick boards
- play-in winner picks
- playoff series picks
- automated bot participation through `The Monkey`
- bracket generation from seeded standings
- deterministic leaderboard recomputation
- export and recovery workflows

## Product goals

The app is designed around three priorities:

1. reliable scoring
2. clear commissioner operations
3. recoverable competition state

## Tech stack

- Python 3
- FastAPI
- SQLAlchemy
- Jinja templates
- SQLite by default, PostgreSQL-ready through configuration
- pytest
- APScheduler
- openpyxl for fallback workbook generation

## Project structure

### `app/main.py`

Primary web application entrypoint.

Includes:

- routes
- session handling
- commissioner actions
- bracket generation
- player detail views
- overview/bets/bracket/commissioner tabs

### `app/domain/scoring.py`

Pure scoring logic.

Includes:

- early-pick scoring
- series scoring
- play-in scoring
- exact-result bonus logic
- tiebreak ranking

### `app/models.py`

Database tables for:

- pools
- users
- memberships
- betting windows
- pick submissions
- result snapshots
- event logs
- payment ledger entries

### `app/data/nba_catalog.py`

Static team and player catalog used by the current manual mode.

### `app/services/automation.py`

Background automation:

- monkey submissions
- lock/reveal deadline processing
- provider health snapshots

### `app/services/recovery.py`

Recovery and continuity tools:

- snapshot export
- workbook export
- CSV export
- JSON restore

### `app/templates/`

Main templates:

- `index.html`
- `invite.html`
- `pool.html`
- `player.html`

## Main user flows

## 1. Create pool

- commissioner creates a pool
- app creates:
  - commissioner user + membership
  - Monkey user + membership
  - invite link
  - initial early-picks window
- Monkey immediately submits early picks

## 2. Join pool

- player enters via invite link
- app creates user + membership
- session cookie is issued

## 3. Submit picks

- players submit picks in open windows
- early picks require all fields
- play-in requires winner
- playoff series require winner and total games

## 4. Lock and reveal

- commissioner can lock any window manually
- scheduler can also auto-lock at deadline
- revealed windows appear in `Closed Bets`

## 5. Post results

- commissioner can update season results one field at a time
- commissioner can post play-in or series outcomes
- downstream bracket placeholders materialize automatically

## 6. Inspect players

- leaderboard entries link to player detail pages
- player page shows:
  - score stats
  - breakdown
  - visible locked picks only

## 7. Export and recover

- commissioners can export a backup bundle
- bundle contains:
  - `snapshot.json`
  - CSVs
  - operator workbook
- recovery creates a new pool from the snapshot

## Tabs

### Overview

- current standings
- active windows
- tie-break rules
- full scoring rules

### Closed Bets

- all revealed picks grouped by game/window

### Bracket

- play-in layout
- first round
- second round placeholders
- winner progression

### Commissioner

- create windows
- generate seeded bracket
- save early results separately
- post official results
- lock/reopen windows
- delete windows
- commissioner-only result feed

## Monkey behavior

The Monkey is an automated participant.

Current behavior:

- created automatically with the pool
- submits early picks immediately
- submits newly created manual windows immediately when teams are known
- submits generated future bracket windows when upstream results materialize both teams
- uses deterministic randomness based on the stored `monkey_seed`

## Bracket generation logic

Commissioner enters top 10 East teams and top 10 West teams.

The app generates:

- East 7 vs 8
- East 9 vs 10
- East 8-seed decider
- West 7 vs 8
- West 9 vs 10
- West 8-seed decider
- East first-round windows
- West first-round windows
- East second-round placeholders
- West second-round placeholders
- East Conference Finals
- West Conference Finals
- NBA Finals

The bracket tab resolves placeholders as official results are posted.

## Scoring summary

### Early picks

- East conference finalist: 2
- West conference finalist: 2
- East NBA finalist: 3
- West NBA finalist: 3
- champion: 5
- Finals MVP: 1

### Play-In

- winner only: 1

### Series

- Round 1: winner 1, exact 3
- Round 2: winner 2, exact 5
- Conference Finals: winner 3, exact 8
- NBA Finals: winner 4, exact 10

### Exact-result bonus

- one exact winner: +2
- two exact winners: +1 each
- three or more: 0

## Current limitations

- static roster/team catalog is still the source for player names
- provider sync is not the active source of truth

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

## Docker run

```bash
docker compose build
docker compose up -d
```

Then open:

```text
http://YOUR_SERVER_IP:8000
```

## Tests

```bash
.venv/bin/pytest
```

## Related docs

- `README.md`
- `RULEBOOK.md`
- `ARCHITECTURE.md`

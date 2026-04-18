# NBA Playoff Pool

Private NBA postseason pool web app built with FastAPI, SQLAlchemy, Jinja templates, and a deterministic scoring engine.

## What the app does

- creates invite-only pools
- supports commissioner and player roles
- includes `The Monkey` as an automated bot participant
- supports `Early Picks`, `Play-In`, and best-of-seven playoff boards
- generates a seeded bracket from the top 10 teams in each conference
- tracks standings, projected ceiling, tiebreaks, player pages, and revealed bets
- gives commissioners tools to manage windows, schedules, results, members, and recovery exports
- exports a full fallback bundle with JSON, CSV, and Excel workbook outputs

## Main docs

- [PROJECT_GUIDE.md](./PROJECT_GUIDE.md)
- [RULEBOOK.md](./RULEBOOK.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)

## Tech stack

- Python 3
- FastAPI
- SQLAlchemy
- Jinja templates + Tailwind CDN styling
- SQLite by default
- PostgreSQL-ready through `DATABASE_URL`
- APScheduler
- openpyxl
- pytest

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

## One-command local start

```bash
./scripts/start.sh
```

## Docker

```bash
docker compose build
docker compose up -d
```

The app binds to `0.0.0.0` inside the container and exposes port `8000` by default.

Open:

```text
http://YOUR_SERVER_IP:8000
```

Use a different host port if needed:

```bash
APP_PORT=8080 docker compose up -d
```

## Railway notes

For Railway:

- connect the repo to a Railway app service
- add a Railway Postgres service if you want managed Postgres
- set the healthcheck path to `/health`
- either leave the start command empty and use the Dockerfile `CMD`, or use a shell-aware command

Recommended env vars:

- `DATABASE_URL`
- `SECRET_KEY`
- `SCHEDULER_ENABLED=true`
- `NBA_PROVIDER_API_KEY=` if unused

## Environment variables

- `DATABASE_URL`
  Defaults to `sqlite:///./nba_pool.db`
- `SECRET_KEY`
  Used to sign the membership session cookie
- `NBA_PROVIDER_API_KEY`
  Optional; BallDontLie adapter exists but the app currently runs in manual mode
- `SCHEDULER_ENABLED`
  Enables the APScheduler background job

## Time handling

- commissioner schedule inputs are shown and parsed in `Asia/Jerusalem`
- stored timestamps are normalized to UTC
- windows are automatically locked when `locks_at` has passed
- auto-lock is enforced by both:
  - the scheduler
  - normal app request flow, so expired boards do not stay open just because the scheduler has not ticked yet

## Core user flows

### Commissioner

- create pool
- generate seeded bracket from top 10 East/West teams
- create manual boards
- update board start/stop times in `Window controls`
- lock, reopen, or delete any board
- rename or remove players
- delete the whole pool
- post early-pick season outcomes
- bulk-save official matchup results
- export a recovery bundle

### Player

- join by invite link
- submit early picks
- submit play-in and series picks
- bulk-save all currently marked picks
- view standings, bracket, revealed bets, and player pages
- see missing-pick reminders on the player page

## Health check

```bash
curl http://127.0.0.1:8000/health
```

## Tests

Run the test suite:

```bash
.venv/bin/pytest -q
```

Run the real-flow smoke test:

```bash
.venv/bin/python scripts/smoke_new_features.py
```

The smoke script exercises a realistic scenario including:

- pool creation
- player join
- bracket generation
- player bulk-save picks
- commissioner bulk-save results
- rename/delete player
- delete pool

## Recovery bundle

Exports include:

- `snapshot.json`
- CSV extracts
- `fallback_workbook.xlsx`

`snapshot.json` is the authoritative restore source.ב

## Important implementation notes

- the leaderboard is not stored as mutable truth
- scores are recomputed from windows, submissions, and result snapshots
- result snapshots are append-only
- The Monkey submits automatically when an eligible board becomes available
- team/player data is currently driven by the in-repo catalog, not live provider sync

## Project structure

### `app/main.py`

Primary web app entrypoint.

Includes:

- route handlers
- view-model assembly
- bracket generation
- commissioner actions
- session handling

### `app/domain/scoring.py`

Deterministic scoring engine.

### `app/models.py`

SQLAlchemy models for app state.

### `app/services/automation.py`

Scheduler logic for monkey submissions and auto-locking.

### `app/services/recovery.py`

Bundle export and JSON restore.

### `app/data/nba_catalog.py`

Static team and roster catalog used by the manual-mode app.

# NBA Playoff Pool

Private NBA postseason pool web app built with FastAPI, SQLAlchemy, Jinja templates, and a deterministic scoring engine.

## What the app does

- creates invite-only pools
- supports commissioner and player roles
- includes `The Monkey` as an automated bot participant
- supports early picks, play-in games, and playoff series boards
- shows a leaderboard, bracket, revealed bets, and player detail pages
- lets commissioners generate a seeded bracket through Round 2
- exports a full recovery bundle with JSON, CSV, and workbook outputs

## Main docs

- [PROJECT_GUIDE.md](./PROJECT_GUIDE.md)
- [RULEBOOK.md](./RULEBOOK.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000)

## One-command start

```bash
./scripts/start.sh
```

## Docker deployment

```bash
docker compose build
docker compose up -d
```

The app binds to `0.0.0.0` inside Docker and publishes port `8000` by default.

Open:

```text
http://YOUR_SERVER_IP:8000
```

Use a different host port if needed:

```bash
APP_PORT=8080 docker compose up -d
```

## Health check

```bash
curl http://127.0.0.1:8000/health
```

## Environment variables

- `DATABASE_URL`
- `SECRET_KEY`
- `NBA_PROVIDER_API_KEY`
- `SCHEDULER_ENABLED`

## Recovery bundle

Exports include:

- `snapshot.json`
- CSV extracts
- `fallback_workbook.xlsx`

The JSON snapshot is the authoritative restore source.

## Tests

```bash
.venv/bin/pytest
`
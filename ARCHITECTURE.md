# ARCHITECTURE

## Core principle

The app treats trust and recoverability as primary product features. Scores are not edited directly. The leaderboard is recomputed from:

- members
- windows
- pick submissions
- result snapshots

## Main layers

### Web layer

`app/main.py`

Responsibilities:

- session and role handling
- invite flow
- player/commissioner routes
- pool dashboard tabs
- bracket generation
- monkey auto-submission on live app actions

### Domain layer

`app/domain/scoring.py`

Responsibilities:

- deterministic pool scoring
- exact-result bonuses
- tie-break ordering
- projected ceiling math
- timestamp normalization for stable ordering

### Persistence layer

`app/models.py`

Stores:

- pools
- users
- memberships
- betting windows
- submissions
- result snapshots
- event logs
- payment ledger

### Automation layer

`app/services/automation.py`

Responsibilities:

- monkey auto-submission for open windows
- automatic lock/reveal at deadline
- provider health snapshots

### Recovery layer

`app/services/recovery.py`

Responsibilities:

- snapshot export
- workbook export
- CSV export
- JSON restore into a recovered pool

## Dashboard structure

The pool page is organized into tabs:

- `Overview`
  - leaderboard
  - tie-break rules
  - full scoring rules
  - active pick forms
- `Closed Bets`
  - revealed picks per window/game
- `Bracket`
  - play-in and playoff progression
- `Commissioner`
  - create/delete/reopen/lock windows
  - generate seeded bracket
  - post results
  - update early results field-by-field
  - commissioner-only audit feed

## Window model

Windows are generic containers around a prediction surface:

- `early`
- `play_in`
- `series`

Each window has:

- open and lock timestamps
- reveal state
- round key
- configuration payload
- deterministic monkey seed

Series windows store one or more matchup definitions, including:

- current teams
- bracket slots
- round metadata
- best-of setting

## Bracket model

Bracket windows can be generated from the top 10 seeds in each conference.

The generated graph includes:

- 7 vs 8 play-in
- 9 vs 10 play-in
- 8-seed decider
- Round 1 placeholders using play-in winners
- Round 2 placeholders using Round 1 winners
- Conference Finals placeholders using Round 2 winners
- NBA Finals placeholder using conference winners

When a result is saved, downstream placeholder matchups are materialized automatically if both participants become known.

## Result model

Results are append-only snapshots.

Supported scopes:

- `early / season`
- `series / <series_key>`
- `system / provider_health`

The latest snapshot for a scope wins.

## Visibility rules

- players can view the overview, bracket, closed bets, and player pages
- result feed is commissioner-only
- unrevealed windows do not expose picks in the closed-bets view
- player detail pages show only picks from revealed windows

## Recovery model

Exports include:

- `snapshot.json`
- CSV tables
- `fallback_workbook.xlsx`

The JSON snapshot is the restore source of truth. CSV and workbook exports are continuity tools for manual operations.

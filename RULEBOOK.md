# RULEBOOK

This file defines the live scoring and competition rules implemented by the app.

## 1. Competition format

- Pools are invite-only.
- Each pool contains human players plus one automated bot player called `The Monkey`.
- The Monkey appears in the leaderboard, submits picks automatically, and is payout eligible in the current implementation.
- The competition supports:
  - `Early picks`
  - `Play-In` winner picks
  - `Playoff series` picks for Round 1, Round 2, Conference Finals, and NBA Finals

## 2. Early picks scoring

Each player submits:

- East conference finalist
- West conference finalist
- East NBA finalist
- West NBA finalist
- NBA champion
- Finals MVP

Points:

- East conference finalist: `2`
- West conference finalist: `2`
- East NBA finalist: `3`
- West NBA finalist: `3`
- NBA champion: `5`
- Finals MVP: `1`

Maximum early-pick score: `16`.

## 3. Play-In scoring

Play-In windows are single-game winner picks.

Points:

- correct winner: `1`

No exact-result bonus applies to Play-In games.

## 4. Series scoring

For best-of-seven playoff rounds, each player submits:

- series winner
- exact result (`4-0`, `4-1`, `4-2`, `4-3`)

Round weights:

- Round 1: winner `1`, exact result `3`
- Round 2: winner `2`, exact result `5`
- Conference Finals: winner `3`, exact result `8`
- NBA Finals: winner `4`, exact result `10`

## 5. Exact-result bonus

- exactly 1 player gets the exact result: `+2`
- exactly 2 players get the exact result: `+1` each
- 3 or more players get the exact result: `0`

## 6. Tiebreakers

Final standings use this order:

1. total points
2. exact series hits
3. Finals MVP correct
4. earliest submission timestamp

## 7. Window behavior

- open windows accept picks
- locked windows reject new picks
- revealed windows show picks in the `Closed Bets` tab
- commissioners can lock and reopen any window, including early picks
- commissioners can delete a window; this also deletes submissions and result snapshots tied to that window

## 8. Season-result updates

Commissioners can update early results one field at a time:

- East conference finalist
- West conference finalist
- East NBA finalist
- West NBA finalist
- Champion
- Finals MVP

The latest saved snapshot becomes the active truth for scoring.

## 9. Bracket generation

Commissioners can enter the top 10 seeds in each conference and auto-generate:

- East Play-In
- West Play-In
- East Round 1
- West Round 1
- East Round 2 placeholders
- West Round 2 placeholders
- East Conference Finals
- West Conference Finals
- NBA Finals

As results are posted, the app materializes the next matchup teams in the bracket.

## 10. Monkey behavior

- one Monkey exists per pool
- it auto-submits early picks when the pool is created
- it auto-submits on newly created windows when both teams are known
- it auto-submits on generated future windows after bracket resolution makes both teams known
- its picks are deterministic from the stored `monkey_seed`

## 11. Recovery

- `snapshot.json` is the authoritative restore file
- CSV and workbook exports are operator-friendly fallback views
- recovery creates a new pool suffixed with `(Recovered)`

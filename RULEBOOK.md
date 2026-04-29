# RULEBOOK

This document describes the current competition rules implemented by the app.

## 1. Competition format

- pools are invite-only
- each pool contains human players and one automated bot player called `The Monkey`
- the competition currently supports:
  - `Early Picks`
  - `Play-In` winner boards
  - `Playoff series` boards for Round 1, Round 2, Conference Finals, and NBA Finals

## 2. Entrants

### Human players

- join through an invite link
- can submit picks only while a board is open

### The Monkey

- one Monkey exists per pool
- it is created automatically
- it auto-submits when an eligible board becomes available
- it currently appears in standings and participates like a normal entrant in the implementation

## 3. Window lifecycle

Each board is represented as a betting window.

States:

- open
- locked
- revealed

Rules:

- open boards accept picks
- locked boards reject new picks
- when a board locks, it is also revealed
- revealed boards appear in the `Closed Bets` area
- commissioners can manually lock or reopen any board
- commissioners can update board start/stop times in the Commissioner tab
- if the stop time has passed, the board auto-locks

## 4. Timezone rules

- commissioner-facing datetime inputs are shown in `Asia/Jerusalem`
- stored timestamps are normalized to UTC
- lock timing is enforced by both scheduler and request-time checks

## 5. Early Picks

The early board requires all of the following:

- East conference finalist
- West conference finalist
- East NBA finalist
- West NBA finalist
- NBA champion
- Finals MVP

### Early Picks scoring

- East conference finalist: `2`
- West conference finalist: `2`
- East NBA finalist: `3`
- West NBA finalist: `3`
- NBA champion: `5`
- Finals MVP: `1`

Maximum early-pick score: `16`

## 6. Play-In scoring

Play-In boards are single-game winner picks.

### Required player input

- game winner

### Scoring

- correct winner: `1`

No exact-result bonus applies to Play-In boards.

## 7. Series board scoring

For best-of-seven boards, each player submits:

- series winner
- total games

Internally the app translates total games to exact result:

- `4 games` -> `4-0`
- `5 games` -> `4-1`
- `6 games` -> `4-2`
- `7 games` -> `4-3`

### Round weights

- Round 1: winner `1`, exact result total `3`
- Round 2: winner `2`, exact result total `5`
- Conference Finals: winner `3`, exact result total `8`
- NBA Finals: winner `4`, exact result total `10`

If a player gets the exact result, that total already includes the winner points before any exact-result bonus is added.

## 8. Exact-result bonus

- exactly 1 player gets the exact result: `+2`
- exactly 2 players get the exact result: `+1` each
- 3 or more players get the exact result: `0`

## 9. Tiebreakers

Final standings are ordered by:

1. total points
2. exact series hits
3. correct Finals MVP pick
4. earliest submission timestamp

## 10. Visibility rules

- players can see overview, bracket, closed bets, and player pages
- the commissioner-only audit/result feed is hidden from players
- unrevealed windows do not expose picks in revealed-bets views
- player detail pages only show picks from revealed windows
- matchup drilldown pages are only available after reveal

## 11. Player submission rules

- players can save one board directly or bulk-save multiple marked boards
- incomplete marked boards are skipped during bulk save
- valid marked boards are still saved
- locked boards reject submission attempts and return the user to the same page with an error message

## 12. Commissioner result rules

Commissioners can save:

- early season outcomes
- play-in outcomes
- series outcomes

Bulk result save behavior:

- valid marked results are saved
- incomplete marked results are skipped
- the response explains how many were saved and how many were skipped

## 13. Bracket generation rules

The commissioner can enter the top 10 teams in each conference.

The app generates:

- East 7 vs 8
- East 9 vs 10
- East No. 8 seed decider
- West 7 vs 8
- West 9 vs 10
- West No. 8 seed decider
- East Round 1
- West Round 1
- East Round 2 placeholders
- West Round 2 placeholders
- East Conference Finals
- West Conference Finals
- NBA Finals

## 14. Bracket progression rules

As official results are posted:

- downstream placeholder teams are materialized automatically
- future windows become real matchups once both teams are known
- Monkey can then auto-submit if the board is eligible

## 15. Finals MVP options

The Finals MVP picker is constrained by the finalist-team player pool used by the app’s roster catalog.

## 16. Member and pool management

The commissioner can:

- rename players
- remove players
- delete a board
- delete the entire pool

Deleting a board also deletes:

- submissions tied to that board
- result snapshots tied to that board

## 17. Recovery rules

Exports include:

- `snapshot.json`
- CSV tables
- `fallback_workbook.xlsx`

Recovery behavior:

- `snapshot.json` is the restore source of truth
- restoring creates a new recovered pool

## 18. Current implementation constraints

- roster and team data are currently served from the in-repo catalog
- BallDontLie provider support exists but is not the active live sync source
- team logos are loaded from ESPN URL patterns with specific slug overrides where needed

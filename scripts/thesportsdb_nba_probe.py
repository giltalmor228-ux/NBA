from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class EventSummary:
    event_id: str
    date: str
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    winner: str | None
    status: str


def is_nba_event(event: dict[str, Any]) -> bool:
    sport = str(event.get("strSport") or "").strip().lower()
    league = str(event.get("strLeague") or "").strip().lower()
    return sport == "basketball" and "nba" in league


def team_played(event: dict[str, Any], team_name: str) -> bool:
    normalized = team_name.strip().casefold()
    return normalized in {
        str(event.get("strHomeTeam") or "").strip().casefold(),
        str(event.get("strAwayTeam") or "").strip().casefold(),
    }


def _parse_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(str(value))
    except (TypeError, ValueError):
        return None


def summarize_event(event: dict[str, Any]) -> EventSummary:
    home_team = str(event.get("strHomeTeam") or "").strip()
    away_team = str(event.get("strAwayTeam") or "").strip()
    home_score = _parse_int(event.get("intHomeScore"))
    away_score = _parse_int(event.get("intAwayScore"))
    winner = None
    if home_score is not None and away_score is not None:
        if home_score > away_score:
            winner = home_team
        elif away_score > home_score:
            winner = away_team
    return EventSummary(
        event_id=str(event.get("idEvent") or ""),
        date=str(event.get("dateEvent") or ""),
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        winner=winner,
        status=str(event.get("strStatus") or "").strip(),
    )


def extract_player_stats_from_payload(payload: dict[str, Any], player_name: str) -> dict[str, Any] | None:
    normalized = player_name.strip().casefold()
    for event in payload.get("events", []):
        for player_stats in event.get("playerStats", []):
            if str(player_stats.get("strPlayer") or "").strip().casefold() == normalized:
                return player_stats
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Best-effort TheSportsDB NBA event probe")
    parser.add_argument("--date", default="2026-04-15")
    parser.add_argument("--team", default="Portland Trail Blazers")
    parser.add_argument("--player", default="Deni Avdija")
    args = parser.parse_args()

    result = {
        "date": args.date,
        "team": args.team,
        "player": args.player,
        "note": "This standalone probe is a parsing scaffold. Live TheSportsDB requests were intentionally left out of the checked-in script.",
        "event": None,
        "player_stats": None,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

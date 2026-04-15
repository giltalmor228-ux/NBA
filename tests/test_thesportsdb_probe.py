from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "thesportsdb_nba_probe.py"
SPEC = importlib.util.spec_from_file_location("thesportsdb_nba_probe", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_is_nba_event_and_portland_filtering() -> None:
    event = {
        "strSport": "Basketball",
        "strLeague": "NBA",
        "strHomeTeam": "Portland Trail Blazers",
        "strAwayTeam": "Los Angeles Lakers",
    }
    assert MODULE.is_nba_event(event) is True
    assert MODULE.team_played(event, "Portland Trail Blazers") is True
    assert MODULE.team_played(event, "Boston Celtics") is False


def test_summarize_event_extracts_winner_and_score() -> None:
    event = {
        "idEvent": "12345",
        "dateEvent": "2026-04-15",
        "strHomeTeam": "Portland Trail Blazers",
        "strAwayTeam": "Golden State Warriors",
        "intHomeScore": "112",
        "intAwayScore": "105",
        "strStatus": "Match Finished",
    }
    summary = MODULE.summarize_event(event)
    assert summary.event_id == "12345"
    assert summary.home_score == 112
    assert summary.away_score == 105
    assert summary.winner == "Portland Trail Blazers"


def test_extract_player_stats_from_payload_finds_named_row() -> None:
    payload = {
        "events": [
            {
                "idEvent": "12345",
                "playerStats": [
                    {
                        "strPlayer": "Deni Avdija",
                        "intPoints": "24",
                        "intRebounds": "7",
                        "intAssists": "5",
                    }
                ],
            }
        ]
    }
    stats = MODULE.extract_player_stats_from_payload(payload, "Deni Avdija")
    assert stats is not None
    assert stats["strPlayer"] == "Deni Avdija"
    assert stats["intPoints"] == "24"

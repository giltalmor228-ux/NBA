#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite:///./smoke_nba_pool.db")
os.environ.setdefault("SECRET_KEY", "smoke-secret")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from app.db import SessionLocal, init_db
from app.main import app
from app.models import BettingWindow, Membership, User


def expect(label: str, ok: bool, details: str = "") -> bool:
    state = "PASS" if ok else "FAIL"
    suffix = f" - {details}" if details else ""
    print(f"[{state}] {label}{suffix}")
    return ok


def main() -> None:
    Path("smoke_nba_pool.db").unlink(missing_ok=True)
    init_db()

    commissioner = TestClient(app)
    player = TestClient(app)

    response = commissioner.post(
        "/pools",
        data={
            "name": "Smoke Feature Pool",
            "season_label": "2025-26 / 2026 Playoffs",
            "commissioner_nickname": "Gil",
            "commissioner_email": "gil@example.com",
            "avatar": "🏀",
        },
        follow_redirects=False,
    )
    pool_url = response.headers["location"].split("?")[0]
    pool_id = pool_url.rsplit("/", 1)[-1]

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner.get(f"{pool_url}?tab=overview").text).group(1)
    player.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"},
        follow_redirects=False,
    )

    for round_key, bet_type, team_one, team_two in [
        ("play_in", "play_in", "ATL", "ORL"),
        ("round_1", "series", "BOS", "NYK"),
        ("round_2", "series", "OKC", "DEN"),
        ("conference_finals", "series", "MIN", "LAL"),
        ("finals", "series", "BOS", "OKC"),
    ]:
        commissioner.post(
            f"{pool_url}/windows",
            data={
                "name": "",
                "round_key": round_key,
                "bet_type": bet_type,
                "opens_at": "2026-04-14T12:00",
                "locks_at": "2026-04-18T19:00",
                "team_one": team_one,
                "team_two": team_two,
                "series_key": "",
                "next_tab": "commissioner",
            },
            follow_redirects=False,
        )

    with SessionLocal() as session:
        play_in_window = session.scalar(
            select(BettingWindow).where(BettingWindow.pool_id == pool_id, BettingWindow.round_key == "play_in", BettingWindow.name.like("%Atlanta Hawks%"))
        )
        early_window = session.scalar(select(BettingWindow).where(BettingWindow.pool_id == pool_id, BettingWindow.bet_type == "early"))
        player_membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "Avi")
        )

    player_bulk = player.post(
        f"{pool_url}/submit-all",
        data={
            "winner_play_in-ATL-ORL": "ATL",
            "winner_round_1-BOS-NYK": "BOS",
            "games_count_round_1-BOS-NYK": "6",
        },
        follow_redirects=True,
    )
    overview_page = player.get(f"{pool_url}?tab=overview")

    expect("Bet banner appears after player submits a game", "You already bet this game." in overview_page.text)
    expect("Player can save multiple marked pick boards together", "Saved 2 marked pick board(s)." in player_bulk.text)

    ordering_labels = [
        "Early Picks",
        "Play-In: Atlanta Hawks vs Orlando Magic",
        "Round 1: Boston Celtics vs New York Knicks",
        "West Semifinal: Oklahoma City Thunder vs Denver Nuggets",
        "West Conference Finals: Minnesota Timberwolves vs Los Angeles Lakers",
        "NBA Finals: Boston Celtics vs Oklahoma City Thunder",
    ]
    ordering_positions = [overview_page.text.find(label) for label in ordering_labels]
    ordering_ok = all(position != -1 for position in ordering_positions) and ordering_positions == sorted(ordering_positions)
    expect("Overview window ordering matches requested sequence", ordering_ok, str(ordering_positions))

    for field_name, field_value in [
        ("conference_finalists_east", "BOS"),
        ("conference_finalists_west", "OKC"),
        ("nba_finalists_east", "BOS"),
        ("nba_finalists_west", "OKC"),
        ("champion", "BOS"),
        ("finals_mvp", "Jayson Tatum"),
    ]:
        commissioner.post(
            f"{pool_url}/results/early-field",
            data={"field_name": field_name, "field_value": field_value},
            follow_redirects=False,
        )
    commissioner.post(f"{pool_url}/windows/{early_window.id}/submit", data={
        "conference_finalists_east": "BOS",
        "conference_finalists_west": "OKC",
        "nba_finalists_east": "BOS",
        "nba_finalists_west": "OKC",
        "champion": "BOS",
        "finals_mvp": "Jayson Tatum",
    }, follow_redirects=False)
    commissioner.post(f"{pool_url}/windows/{early_window.id}/lock", follow_redirects=False)
    player.post(f"{pool_url}/windows/{early_window.id}/submit", data={
        "conference_finalists_east": "ATL",
        "conference_finalists_west": "DEN",
        "nba_finalists_east": "NYK",
        "nba_finalists_west": "MIN",
        "champion": "MIN",
        "finals_mvp": "Anthony Edwards",
    }, follow_redirects=False)
    locked_attempt = player.post(
        f"{pool_url}/windows/{early_window.id}/submit",
        data={
            "conference_finalists_east": "BOS",
            "conference_finalists_west": "OKC",
            "nba_finalists_east": "BOS",
            "nba_finalists_west": "OKC",
            "champion": "BOS",
            "finals_mvp": "Jayson Tatum",
        },
        follow_redirects=True,
    )
    expect("Locked bet stays on page with error banner", "The bet is closed, you can bag to Gil" in locked_attempt.text)

    leader_message_page = commissioner.post(
        f"{pool_url}/leader-message",
        data={"message": "Smoke spotlight"},
        follow_redirects=True,
    )
    expect("First-place spotlight message appears in live standings", "Smoke spotlight" in leader_message_page.text)

    result_save = commissioner.post(
        f"{pool_url}/results",
        data={
            "result_winner_play_in-ATL-ORL": "ATL",
            "display_score_play_in-ATL-ORL": "111-104",
            "result_winner_round_1-BOS-NYK": "BOS",
            "result_games_count_round_1-BOS-NYK": "6",
            "display_score_round_1-BOS-NYK": "Boston won 4-2",
        },
        follow_redirects=True,
    )
    expect("Bulk save results flash appears", "Saved 2 marked result(s)." in result_save.text)
    expect("Commissioner sees saved-result badge for play-in", "Saved result: 111-104" in result_save.text)
    expect("Commissioner sees saved-result badge for round 1", "Saved result: Boston won 4-2" in result_save.text)

    rename_page = commissioner.post(
        f"/pools/{pool_id}/members/{player_membership.id}/rename",
        data={"nickname": "Avi Prime"},
        follow_redirects=True,
    )
    expect("Commissioner can rename player", "Updated Avi Prime." in rename_page.text)

    delete_member_page = commissioner.post(
        f"/pools/{pool_id}/members/{player_membership.id}/delete",
        follow_redirects=True,
    )
    expect("Commissioner can delete player", "Removed Avi Prime from the tournament." in delete_member_page.text)

    with SessionLocal() as session:
        commissioner_membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "Gil")
        )
        commissioner_member_id = commissioner_membership.id

    player_page = commissioner.get(f"{pool_url}/players/{commissioner_member_id}")
    expect("Player page shows missing picks section", "Boards still waiting on this player" in player_page.text)

    delete_pool_response = commissioner.post(f"{pool_url}/delete", follow_redirects=False)
    homepage = commissioner.get(delete_pool_response.headers.get("location", "/")) if delete_pool_response.status_code == 303 else None
    expect("Commissioner can delete pool", delete_pool_response.status_code == 303 and homepage is not None and homepage.status_code == 200)


if __name__ == "__main__":
    main()

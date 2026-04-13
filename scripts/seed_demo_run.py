#!/usr/bin/env python3
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.data.nba_catalog import TEAM_BY_CODE, players_for_teams, teams_by_conference
from app.db import SessionLocal, init_db
from app.main import app, load_pool_context
from app.models import BettingWindow, Membership, PickSubmission, User


RNG = random.Random(20260413)


def create_pool(client: TestClient, name: str) -> str:
    response = client.post(
        "/pools",
        data={
            "name": name,
            "season_label": "2025-26 / 2026 Playoffs",
            "commissioner_nickname": "Demo Commissioner",
            "commissioner_email": "demo-commissioner@example.com",
            "avatar": "🏀",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, f"Pool creation failed: {response.status_code}"
    return response.headers["location"].split("?")[0]


def pool_id_from_url(pool_url: str) -> str:
    return pool_url.rsplit("/", 1)[-1]


def fetch_windows(pool_id: str) -> list[BettingWindow]:
    with SessionLocal() as session:
        return session.scalars(select(BettingWindow).where(BettingWindow.pool_id == pool_id).order_by(BettingWindow.opens_at, BettingWindow.created_at)).all()


def find_window_by_name(pool_id: str, name: str) -> BettingWindow:
    for window in fetch_windows(pool_id):
        if window.name == name:
            return window
    raise RuntimeError(f"Window named {name!r} was not found.")


def find_window_by_series_key(pool_id: str, series_key: str) -> BettingWindow:
    for window in fetch_windows(pool_id):
        if any(series.get("series_key") == series_key for series in window.config.get("series", [])):
            return window
    raise RuntimeError(f"Window for series key {series_key!r} was not found.")


def monkey_has_submission(pool_id: str, window_id: str) -> bool:
    with SessionLocal() as session:
        monkey_membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.is_monkey.is_(True))
        )
        if not monkey_membership:
            return False
        submission = session.scalar(
            select(PickSubmission).where(PickSubmission.window_id == window_id, PickSubmission.member_id == monkey_membership.id)
        )
        return submission is not None


def submit_early_picks(client: TestClient, pool_url: str, window_id: str, east_teams: list[str], west_teams: list[str], entrant_index: int) -> None:
    east_cf = east_teams[entrant_index % len(east_teams)]
    west_cf = west_teams[(entrant_index + 1) % len(west_teams)]
    east_final = east_teams[0 if entrant_index % 2 == 0 else 1]
    west_final = west_teams[0 if entrant_index % 2 == 0 else 1]
    finals_pool = players_for_teams([east_final, west_final])
    finals_mvp = finals_pool[entrant_index % len(finals_pool)]
    response = client.post(
        f"{pool_url}/windows/{window_id}/submit",
        data={
            "conference_finalists_east": east_cf,
            "conference_finalists_west": west_cf,
            "nba_finalists_east": east_final,
            "nba_finalists_west": west_final,
            "champion": east_final if entrant_index % 2 == 0 else west_final,
            "finals_mvp": finals_mvp,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, f"Early picks save failed with status {response.status_code}"


def submit_series_pick(client: TestClient, pool_url: str, window: BettingWindow, entrant_index: int, actual_winner: str, actual_games_count: int) -> None:
    series = window.config["series"][0]
    series_key = series["series_key"]
    teams = [team for team in series.get("teams", []) if team and team != "TBD"]
    assert len(teams) == 2, f"{series_key} is not resolved enough to accept picks."
    if entrant_index in {0, 1, 2}:
        winner = actual_winner
    elif entrant_index % 2 == 0:
        winner = teams[0]
    else:
        winner = teams[1]
    data = {f"winner_{series_key}": winner}
    if window.bet_type != "play_in":
        if entrant_index == 0:
            games_count = actual_games_count
        elif entrant_index in {1, 2}:
            games_count = 4 + ((actual_games_count - 3 + entrant_index) % 4)
        else:
            games_count = 4 + (entrant_index % 4)
        data[f"games_count_{series_key}"] = str(games_count)
    response = client.post(f"{pool_url}/windows/{window.id}/submit", data=data, follow_redirects=False)
    assert response.status_code == 303, f"Prediction save failed for {series_key}: {response.status_code}"


def lock_window(client: TestClient, pool_url: str, window: BettingWindow) -> None:
    response = client.post(f"{pool_url}/windows/{window.id}/lock", follow_redirects=False)
    assert response.status_code == 303, f"Lock failed for {window.name}: {response.status_code}"


def unlock_window(client: TestClient, pool_url: str, window: BettingWindow) -> None:
    response = client.post(f"{pool_url}/windows/{window.id}/unlock", follow_redirects=False)
    assert response.status_code == 303, f"Unlock failed for {window.name}: {response.status_code}"


def save_series_result(client: TestClient, pool_url: str, window: BettingWindow, winner: str, games_count: int | None = None) -> None:
    series = window.config["series"][0]
    team_names = {team: TEAM_BY_CODE.get(team, None).name if TEAM_BY_CODE.get(team) else team for team in series.get("teams", [])}
    if window.bet_type == "play_in":
        display_score = f"{team_names.get(winner, winner)} advanced"
    else:
        display_score = f"{team_names.get(winner, winner)} won 4-{(games_count or 6) - 4}"
    data = {
        "scope_type": "series",
        "scope_key": series["series_key"],
        "result_winner": winner,
        "bet_type": window.bet_type,
        "display_score": display_score,
        "source": "manual",
    }
    if window.bet_type != "play_in":
        data["result_games_count"] = str(games_count or 6)
    response = client.post(f"{pool_url}/results", data=data, follow_redirects=False)
    assert response.status_code == 303, f"Result save failed for {series['series_key']}: {response.status_code}"


def save_early_results(client: TestClient, pool_url: str, east_final: str, west_final: str, champion: str) -> None:
    finals_pool = players_for_teams([east_final, west_final])
    updates = [
        ("conference_finalists_east", east_final),
        ("conference_finalists_west", west_final),
        ("nba_finalists_east", east_final),
        ("nba_finalists_west", west_final),
        ("champion", champion),
        ("finals_mvp", finals_pool[0]),
    ]
    for field_name, field_value in updates:
        response = client.post(
            f"{pool_url}/results/early-field",
            data={"field_name": field_name, "field_value": field_value},
            follow_redirects=False,
        )
        assert response.status_code == 303, f"Early result update failed for {field_name}: {response.status_code}"


def assert_pages_render(commissioner_client: TestClient, player_client: TestClient, pool_url: str) -> None:
    for tab in ("overview", "bets", "bracket", "commissioner"):
        response = commissioner_client.get(f"{pool_url}?tab={tab}")
        assert response.status_code == 200, f"Commissioner tab {tab} returned {response.status_code}"
        assert "Internal Server Error" not in response.text, f"Commissioner tab {tab} rendered an internal error."
    for tab in ("overview", "bets", "bracket"):
        response = player_client.get(f"{pool_url}?tab={tab}")
        assert response.status_code == 200, f"Player tab {tab} returned {response.status_code}"
        assert "Internal Server Error" not in response.text, f"Player tab {tab} rendered an internal error."


def main() -> None:
    init_db()
    commissioner_client = TestClient(app)
    player_clients = [TestClient(app) for _ in range(10)]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    pool_name = f"Dashboard Demo Run {timestamp}"
    pool_url = create_pool(commissioner_client, pool_name)
    pool_id = pool_id_from_url(pool_url)

    grouped = teams_by_conference()
    east_seeds = [team.code for team in RNG.sample(grouped["East"], 10)]
    west_seeds = [team.code for team in RNG.sample(grouped["West"], 10)]

    overview_page = commissioner_client.get(f"{pool_url}?tab=overview")
    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", overview_page.text).group(1)
    joined_clients = [commissioner_client]
    player_identities: list[tuple[str, str]] = [("Demo Commissioner", "demo-commissioner@example.com")]
    for index, client in enumerate(player_clients, start=1):
        nickname = f"Demo Player {index}"
        email = f"demo-player-{index}@example.com"
        response = client.post(
            f"/invite/{invite_token}",
            data={"nickname": nickname, "email": email, "avatar": "🔥"},
            follow_redirects=False,
        )
        assert response.status_code == 303, f"Join failed for {nickname}: {response.status_code}"
        joined_clients.append(client)
        player_identities.append((nickname, email))

    bracket_response = commissioner_client.post(
        f"{pool_url}/generate-bracket",
        data={
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-16T19:00",
            **{f"east_seed_{index}": team for index, team in enumerate(east_seeds, start=1)},
            **{f"west_seed_{index}": team for index, team in enumerate(west_seeds, start=1)},
        },
        follow_redirects=False,
    )
    assert bracket_response.status_code == 303, f"Bracket generation failed: {bracket_response.status_code}"

    early_window = find_window_by_name(pool_id, "Early Picks")
    for entrant_index, client in enumerate(joined_clients):
        submit_early_picks(client, pool_url, early_window.id, east_seeds, west_seeds, entrant_index)
    assert monkey_has_submission(pool_id, early_window.id), "The Monkey did not submit early picks."

    initial_play_in_results = {
        "play_in-east-7v8": east_seeds[6],
        "play_in-east-9v10": east_seeds[8],
        "play_in-west-7v8": west_seeds[6],
        "play_in-west-9v10": west_seeds[9],
    }
    for series_key, winner in initial_play_in_results.items():
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(joined_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=1)
        assert monkey_has_submission(pool_id, window.id), f"The Monkey did not submit for {series_key}."
        lock_window(commissioner_client, pool_url, window)

    west_nine_ten = find_window_by_series_key(pool_id, "play_in-west-9v10")
    unlock_window(commissioner_client, pool_url, west_nine_ten)
    lock_window(commissioner_client, pool_url, west_nine_ten)
    lock_window(commissioner_client, pool_url, early_window)

    for series_key, winner in initial_play_in_results.items():
        save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, series_key), winner, games_count=1)

    decider_results = {
        "play_in-east-8seed": east_seeds[7],
        "play_in-west-8seed": west_seeds[9],
    }
    for series_key, winner in decider_results.items():
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(joined_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=1)
        assert monkey_has_submission(pool_id, window.id), f"The Monkey did not submit for {series_key}."
        lock_window(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=1)

    round_one_outcomes = {
        "round_1-east-1v8": (east_seeds[0], 5),
        "round_1-east-2v7": (east_seeds[1], 6),
        "round_1-east-3v6": (east_seeds[2], 4),
        "round_1-east-4v5": (east_seeds[4], 7),
        "round_1-west-1v8": (west_seeds[0], 5),
        "round_1-west-2v7": (west_seeds[6], 7),
        "round_1-west-3v6": (west_seeds[2], 6),
        "round_1-west-4v5": (west_seeds[3], 4),
    }
    for series_key, (winner, games_count) in round_one_outcomes.items():
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(joined_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=games_count)
        assert monkey_has_submission(pool_id, window.id), f"The Monkey did not submit for {series_key}."
        lock_window(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=games_count)

    round_two_outcomes = {
        "round_2-east-top": (east_seeds[0], 6),
        "round_2-east-bottom": (east_seeds[2], 7),
        "round_2-west-top": (west_seeds[0], 5),
        "round_2-west-bottom": (west_seeds[2], 6),
    }
    for series_key, (winner, games_count) in round_two_outcomes.items():
        window = find_window_by_series_key(pool_id, series_key)
        assert monkey_has_submission(pool_id, window.id), f"The Monkey did not submit for {series_key}."
        for entrant_index, client in enumerate(joined_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=games_count)
        lock_window(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=games_count)

    conference_finals_outcomes = {
        "conference_finals-east": (east_seeds[0], 6),
        "conference_finals-west": (west_seeds[0], 7),
    }
    for series_key, (winner, games_count) in conference_finals_outcomes.items():
        window = find_window_by_series_key(pool_id, series_key)
        assert monkey_has_submission(pool_id, window.id), f"The Monkey did not submit for {series_key}."
        for entrant_index, client in enumerate(joined_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=games_count)
        lock_window(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=games_count)

    finals_window = find_window_by_series_key(pool_id, "finals-nba")
    assert monkey_has_submission(pool_id, finals_window.id), "The Monkey did not submit for the NBA Finals."
    for entrant_index, client in enumerate(joined_clients):
        submit_series_pick(client, pool_url, finals_window, entrant_index, east_seeds[0], actual_games_count=7)
    lock_window(commissioner_client, pool_url, finals_window)
    save_series_result(commissioner_client, pool_url, finals_window, east_seeds[0], games_count=7)

    save_early_results(commissioner_client, pool_url, east_seeds[0], west_seeds[0], east_seeds[0])

    assert_pages_render(commissioner_client, player_clients[0], pool_url)

    with SessionLocal() as session:
        context = load_pool_context(session, pool_id)
        leaderboard = context["leaderboard"]
        overview_names = [entry.display_name for entry in leaderboard[:5]]
        monkey_rank = next(entry.rank for entry in leaderboard if entry.is_monkey)

    print("")
    print("Demo dashboard run created successfully.")
    print(f"Pool name: {pool_name}")
    print(f"Pool URL: {pool_url}")
    print("")
    print("Use these credentials in the pool's 'Sign in to this pool' form:")
    print("Commissioner: Demo Commissioner / demo-commissioner@example.com")
    for nickname, email in player_identities[1:]:
        print(f"Player: {nickname} / {email}")
    print("")
    print(f"Monkey rank in this run: {monkey_rank}")
    print(f"Top 5 leaderboard names: {', '.join(overview_names)}")
    print("")
    print("Seeded conferences used:")
    print("East:", ", ".join(f"{index}. {TEAM_BY_CODE[team].name}" for index, team in enumerate(east_seeds, start=1)))
    print("West:", ", ".join(f"{index}. {TEAM_BY_CODE[team].name}" for index, team in enumerate(west_seeds, start=1)))


if __name__ == "__main__":
    main()

import io
import json
import os
import random
import re
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import select
from fastapi.testclient import TestClient


Path("test_nba_pool.db").unlink(missing_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///./test_nba_pool.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SCHEDULER_ENABLED"] = "false"

from app.data.nba_catalog import TEAM_BY_CODE, players_for_teams, teams_by_conference  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app, load_pool_context, localize_datetime_display, localize_datetime_input, parse_iso_datetime, team_logo  # noqa: E402
from app.models import BettingWindow, Membership, PickSubmission, ResultSnapshot, SideBet, SideBetSubmission, User  # noqa: E402


init_db()


def create_pool(client: TestClient, name: str) -> str:
    response = client.post(
        "/pools",
        data={
            "name": name,
            "season_label": "2025-26 / 2026 Playoffs",
            "commissioner_nickname": "Gil",
            "commissioner_email": "gil@example.com",
            "avatar": "🏀",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("?")[0]


def pool_id_from_url(pool_url: str) -> str:
    return pool_url.rsplit("/", 1)[-1]


def fetch_windows(pool_id: str) -> list[BettingWindow]:
    with SessionLocal() as session:
        return session.scalars(select(BettingWindow).where(BettingWindow.pool_id == pool_id).order_by(BettingWindow.opens_at, BettingWindow.created_at)).all()


def find_window_by_series_key(pool_id: str, series_key: str) -> BettingWindow:
    for window in fetch_windows(pool_id):
        if any(series.get("series_key") == series_key for series in window.config.get("series", [])):
            return window
    raise AssertionError(f"Window for series key {series_key} was not found.")


def find_window_by_name(pool_id: str, name: str) -> BettingWindow:
    for window in fetch_windows(pool_id):
        if window.name == name:
            return window
    raise AssertionError(f"Window named {name} was not found.")


def find_monkey_membership(pool_id: str) -> Membership:
    with SessionLocal() as session:
        membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.is_monkey.is_(True))
        )
        assert membership is not None
        return membership


def assert_monkey_submission(pool_id: str, window_id: str, label: str) -> None:
    monkey_membership = find_monkey_membership(pool_id)
    with SessionLocal() as session:
        submission = session.scalar(
            select(PickSubmission).where(PickSubmission.window_id == window_id, PickSubmission.member_id == monkey_membership.id)
        )
        assert submission is not None, f"The Monkey did not submit a pick for {label}."


def assert_result_exists(pool_id: str, scope_key: str, scope_type: str = "series") -> None:
    with SessionLocal() as session:
        result = session.scalar(
            select(ResultSnapshot).where(
                ResultSnapshot.pool_id == pool_id,
                ResultSnapshot.scope_type == scope_type,
                ResultSnapshot.scope_key == scope_key,
            )
        )
        assert result is not None, f"Missing {scope_type} result for {scope_key}."


def assert_core_pages_ok(client: TestClient, pool_url: str, commissioner: bool) -> None:
    pool_id = pool_id_from_url(pool_url)
    tabs = ["overview", "bets", "bracket"] + (["commissioner"] if commissioner else [])
    seen_player_pages: set[str] = set()
    for tab in tabs:
        response = client.get(f"{pool_url}?tab={tab}")
        assert response.status_code == 200, f"{tab} page returned {response.status_code}"
        assert "Internal Server Error" not in response.text, f"{tab} page rendered an internal server error."
        for member_id in re.findall(rf"/pools/{pool_id}/players/([a-f0-9-]+)", response.text):
            if member_id in seen_player_pages:
                continue
            player_page = client.get(f"/pools/{pool_id}/players/{member_id}")
            assert player_page.status_code == 200, f"Player page for {member_id} returned {player_page.status_code}"
            assert "Internal Server Error" not in player_page.text
            seen_player_pages.add(member_id)
            if len(seen_player_pages) >= 3:
                break


def submit_early_picks(client: TestClient, pool_url: str, window_id: str, east_teams: list[str], west_teams: list[str], entrant_index: int) -> None:
    east_cf = east_teams[entrant_index % len(east_teams)]
    west_cf = west_teams[(entrant_index + 1) % len(west_teams)]
    east_final = east_teams[0 if entrant_index % 2 == 0 else 1]
    west_final = west_teams[0 if entrant_index % 2 == 0 else 1]
    finals_mvp = players_for_teams([east_final, west_final])[entrant_index % len(players_for_teams([east_final, west_final]))]
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
    assert response.status_code == 303


def submit_series_pick(
    client: TestClient,
    pool_url: str,
    window: BettingWindow,
    entrant_index: int,
    actual_winner: str,
    actual_games_count: int,
) -> None:
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
    assert response.status_code == 303, f"Prediction save failed for {series_key} with status {response.status_code}."


def save_series_result(
    commissioner_client: TestClient,
    pool_url: str,
    window: BettingWindow,
    winner: str,
    games_count: int | None = None,
) -> None:
    series = window.config["series"][0]
    data = {
        "scope_type": "series",
        "scope_key": series["series_key"],
        "result_winner": winner,
        "bet_type": window.bet_type,
        "source": "manual",
    }
    if window.bet_type != "play_in":
        data["result_games_count"] = str(games_count or 6)
    response = commissioner_client.post(f"{pool_url}/results", data=data, follow_redirects=False)
    assert response.status_code == 303, f"Saving result failed for {series['series_key']} with status {response.status_code}."


def lock_window_and_assert_revealed(commissioner_client: TestClient, pool_url: str, window: BettingWindow) -> None:
    response = commissioner_client.post(f"{pool_url}/windows/{window.id}/lock", follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as session:
        refreshed = session.get(BettingWindow, window.id)
        assert refreshed is not None and refreshed.is_locked and refreshed.is_revealed


def unlock_window_and_assert_open(commissioner_client: TestClient, pool_url: str, window: BettingWindow) -> None:
    response = commissioner_client.post(f"{pool_url}/windows/{window.id}/unlock", follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as session:
        refreshed = session.get(BettingWindow, window.id)
        assert refreshed is not None and not refreshed.is_locked and not refreshed.is_revealed


def test_commissioner_can_update_window_times() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Window Timing Pool")
    pool_id = pool_id_from_url(pool_url)
    early_window = find_window_by_name(pool_id, "Early Picks")

    response = commissioner_client.post(
        f"{pool_url}/windows/{early_window.id}/schedule",
        data={"opens_at": "2026-04-15T10:00", "locks_at": "2026-04-16T21:30"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as session:
        refreshed = session.get(BettingWindow, early_window.id)
        assert refreshed is not None
        assert refreshed.opens_at.isoformat().startswith("2026-04-15T07:00:00")
        assert refreshed.locks_at.isoformat().startswith("2026-04-16T18:30:00")
        assert localize_datetime_input(refreshed.opens_at) == "2026-04-15T10:00"
        assert localize_datetime_input(refreshed.locks_at) == "2026-04-16T21:30"


def test_israel_timezone_roundtrip_for_schedule_inputs() -> None:
    parsed = parse_iso_datetime("2026-04-14T10:59")
    assert parsed.isoformat().startswith("2026-04-14T07:59:00")
    assert localize_datetime_input(parsed) == "2026-04-14T10:59"


def test_window_datetime_display_uses_two_line_israel_format() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Display Format Pool")
    pool_id = pool_id_from_url(pool_url)
    early_window = find_window_by_name(pool_id, "Early Picks")

    update_response = commissioner_client.post(
        f"{pool_url}/windows/{early_window.id}/schedule",
        data={"opens_at": "2026-04-14T11:44", "locks_at": "2026-04-15T05:00"},
        follow_redirects=False,
    )
    assert update_response.status_code == 303

    page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert page.status_code == 200
    assert "Opens 14-04-2026 11:44<br />" in page.text
    assert "Locks 15-04-2026 05:00" in page.text

    parsed_open = parse_iso_datetime("2026-04-14T11:44")
    parsed_lock = parse_iso_datetime("2026-04-15T05:00")
    assert localize_datetime_display(parsed_open) == "14-04-2026 11:44"
    assert localize_datetime_display(parsed_lock) == "15-04-2026 05:00"


def test_expired_window_auto_locks_before_player_submit() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Auto Lock Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    early_window = find_window_by_name(pool_id, "Early Picks")
    update_response = commissioner_client.post(
        f"{pool_url}/windows/{early_window.id}/schedule",
        data={"opens_at": "2026-04-10T10:00", "locks_at": "2026-04-11T10:00"},
        follow_redirects=False,
    )
    assert update_response.status_code == 303

    response = player_client.post(
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
    assert response.status_code == 200
    assert "The bet is closed, you can bag to Gil" in response.text

    with SessionLocal() as session:
        refreshed = session.get(BettingWindow, early_window.id)
        assert refreshed is not None
        assert refreshed.is_locked is True
        assert refreshed.is_revealed is True


def test_overview_prioritizes_open_games_by_lock_time() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Overview Ordering Pool")

    later = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "Later Lock Game",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-16T12:00",
            "locks_at": "2026-04-21T19:00",
            "team_one": "BOS",
            "team_two": "NYK",
            "series_key": "",
            "next_tab": "overview",
        },
        follow_redirects=False,
    )
    assert later.status_code == 303

    earlier = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "Earlier Lock Game",
            "round_key": "conference_finals",
            "bet_type": "series",
            "opens_at": "2026-04-16T12:00",
            "locks_at": "2026-04-17T13:00",
            "team_one": "OKC",
            "team_two": "MIN",
            "series_key": "",
            "next_tab": "overview",
        },
        follow_redirects=False,
    )
    assert earlier.status_code == 303

    page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert page.status_code == 200
    with SessionLocal() as session:
        ordered_names = [window.name for window in load_pool_context(session, pool_id_from_url(pool_url))["windows"]]
    earlier_index = ordered_names.index("West Conference Finals: Oklahoma City Thunder vs Minnesota Timberwolves")
    later_index = ordered_names.index("East Round 1: Boston Celtics vs New York Knicks")
    assert earlier_index < later_index


def leaderboard_points(pool_id: str) -> dict[str, int]:
    with SessionLocal() as session:
        context = load_pool_context(session, pool_id)
        return {row.member_id: row.total_points for row in context["leaderboard"]}


def test_create_pool_join_and_export_bundle() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Integration Pool")

    pool_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert pool_page.status_code == 200
    assert "Integration Pool" in pool_page.text

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", pool_page.text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    export_response = commissioner_client.get(f"{pool_url}/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"

    archive = ZipFile(io.BytesIO(export_response.content))
    names = set(archive.namelist())
    assert "snapshot.json" in names
    assert "fallback_workbook.xlsx" in names
    snapshot = json.loads(archive.read("snapshot.json").decode("utf-8"))
    assert snapshot["pool"]["name"] == "Integration Pool"


def test_team_logo_uses_utah_slug_override() -> None:
    assert team_logo("UTA").endswith("/utah.png")
    assert team_logo("BOS").endswith("/bos.png")


def test_team_and_player_dropdowns_cover_catalog() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Catalog Pool")

    pool_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert pool_page.status_code == 200
    assert "Atlanta Hawks" in pool_page.text
    assert "Utah Jazz" in pool_page.text

    create_window_response = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "Round 1: Celtics vs Magic",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-14T12:00:00+00:00",
            "locks_at": "2026-04-18T16:00:00+00:00",
            "team_one": "BOS",
            "team_two": "ORL",
            "series_key": "",
        },
        follow_redirects=False,
    )
    assert create_window_response.status_code == 303

    updated_pool_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert updated_pool_page.status_code == 200
    assert "Boston Celtics" in updated_pool_page.text
    assert "Orlando Magic" in updated_pool_page.text
    assert "How ties are resolved" in updated_pool_page.text

    commissioner_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert commissioner_page.status_code == 200
    assert 'type="datetime-local"' in commissioner_page.text
    finals_pool = players_for_teams(["BOS", "NYK"])
    assert "Nikola Vucevic" in finals_pool
    assert "Jordan Clarkson" in finals_pool
    assert "Hugo Gonzalez" in finals_pool


def test_create_window_generates_name_from_round_and_teams() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Window Pool")

    create_window_response = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-18T19:00",
            "team_one": "BOS",
            "team_two": "ORL",
            "series_key": "",
        },
        follow_redirects=False,
    )
    assert create_window_response.status_code == 303

    updated_pool_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert updated_pool_page.status_code == 200
    assert "Round 1: Boston Celtics vs Orlando Magic" in updated_pool_page.text


def test_existing_pool_opens_without_membership_session() -> None:
    commissioner_client = TestClient(app)
    viewer_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Open Pool")

    page = viewer_client.get(f"{pool_url}?tab=overview")
    assert page.status_code == 200
    assert "Open Pool" in page.text
    assert "Sign in first" in page.text
    assert "Sign in to this pool" in page.text
    assert "Overview" not in page.text


def test_join_and_resume_set_persistent_pool_cookie() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Cookie Pool")

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303
    set_cookie_header = join_response.headers.get("set-cookie", "")
    assert "Max-Age=" in set_cookie_header

    player_client.post(f"{pool_url}/signout", follow_redirects=False)
    resume_response = player_client.post(
        f"{pool_url}/resume",
        data={"nickname": "Avi", "email": "avi@example.com"},
        follow_redirects=False,
    )
    assert resume_response.status_code == 303
    assert "Max-Age=" in resume_response.headers.get("set-cookie", "")


def test_resume_requires_email_and_accepts_case_insensitive_match() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Resume Case Pool")

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "Avi@Example.com", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    player_client.post(f"{pool_url}/signout", follow_redirects=False)

    missing_email_response = player_client.post(
        f"{pool_url}/resume",
        data={"nickname": "Avi", "email": ""},
        follow_redirects=True,
    )
    assert missing_email_response.status_code == 200
    assert "Enter both the original nickname and email to sign in." in missing_email_response.text

    resume_response = player_client.post(
        f"{pool_url}/resume",
        data={"nickname": "aVi", "email": "avi@example.COM"},
        follow_redirects=True,
    )
    assert resume_response.status_code == 200
    assert "Welcome back, Avi. Your access has been restored." in resume_response.text
    assert "Signed in as" in resume_response.text


def test_commissioner_sees_missing_email_warning_and_can_add_email() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Missing Email Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "NoMail", "email": "", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    commissioner_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert commissioner_page.status_code == 200
    assert "missing an email" in commissioner_page.text
    assert "Email missing" in commissioner_page.text

    with SessionLocal() as session:
        membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "NoMail")
        )
        assert membership is not None
        member_id = membership.id

    update_response = commissioner_client.post(
        f"/pools/{pool_id}/members/{member_id}/email",
        data={"email": "nomail@example.com"},
        follow_redirects=True,
    )
    assert update_response.status_code == 200
    assert "Saved email for NoMail." in update_response.text

    updated_commissioner_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert updated_commissioner_page.status_code == 200
    assert "Email missing" not in updated_commissioner_page.text
    assert "nomail@example.com" in updated_commissioner_page.text

    player_client.post(f"{pool_url}/signout", follow_redirects=False)
    resume_response = player_client.post(
        f"{pool_url}/resume",
        data={"nickname": "nomail", "email": "NOMAIL@example.com"},
        follow_redirects=True,
    )
    assert resume_response.status_code == 200
    assert "Welcome back, NoMail. Your access has been restored." in resume_response.text


def test_sign_in_identifier_does_not_require_at_symbol() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Identifier Pool")

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi-login", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    player_client.post(f"{pool_url}/signout", follow_redirects=False)

    resume_response = player_client.post(
        f"{pool_url}/resume",
        data={"nickname": "AVI", "email": "AVI-LOGIN"},
        follow_redirects=True,
    )
    assert resume_response.status_code == 200
    assert "Welcome back, Avi. Your access has been restored." in resume_response.text


def test_resume_commissioner_access_restores_betting_window_controls() -> None:
    commissioner_client = TestClient(app)
    viewer_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Resume Pool")

    guest_page = viewer_client.get(f"{pool_url}?tab=overview")
    assert guest_page.status_code == 200
    assert "Commissioner controls are available in the Commissioner tab." not in guest_page.text

    resume_response = viewer_client.post(
        f"{pool_url}/resume",
        data={"nickname": "Gil", "email": "gil@example.com"},
        follow_redirects=False,
    )
    assert resume_response.status_code == 303
    assert "resume_status=success" in resume_response.headers["location"]

    resumed_page = viewer_client.get(resume_response.headers["location"])
    assert resumed_page.status_code == 200
    assert "Commissioner controls are available in the Commissioner tab." in resumed_page.text
    commissioner_page = viewer_client.get(f"{pool_url}?tab=commissioner")
    assert commissioner_page.status_code == 200
    assert "Create a betting window" in commissioner_page.text


def test_save_prediction_redirects_cleanly_after_submit() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Prediction Pool")

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    create_window_response = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-18T19:00",
            "team_one": "BOS",
            "team_two": "ORL",
            "series_key": "",
            "next_tab": "commissioner",
        },
        follow_redirects=False,
    )
    assert create_window_response.status_code == 303

    pool_page = player_client.get(f"{pool_url}?tab=overview")
    assert pool_page.status_code == 200

    assert 'action="/pools/' in pool_page.text
    assert f'action="/pools/{pool_id_from_url(pool_url)}/submit-all"' in pool_page.text

    save_response = player_client.post(
        f"{pool_url}/submit-all",
        data={
            "winner_round_1-BOS-ORL": "BOS",
            "games_count_round_1-BOS-ORL": "6",
        },
        follow_redirects=True,
    )
    assert save_response.status_code == 200
    assert "Internal Server Error" not in save_response.text
    assert "Boston Celtics" in save_response.text


def test_series_results_require_all_visible_fields() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Validation Pool")

    create_window_response = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-18T19:00",
            "team_one": "BOS",
            "team_two": "ORL",
            "series_key": "",
            "next_tab": "commissioner",
        },
        follow_redirects=False,
    )
    assert create_window_response.status_code == 303

    result_response = commissioner_client.post(
        f"{pool_url}/results",
        data={
            "scope_type": "series",
            "scope_key": "round_1-BOS-ORL",
            "result_winner": "BOS",
            "result_games_count": "6",
            "bet_type": "series",
            "source": "manual",
        },
        follow_redirects=False,
    )
    assert result_response.status_code == 303


def test_matchup_detail_and_closed_bets_tables_show_results_and_points() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Tables Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    early_window = find_window_by_name(pool_id, "Early Picks")
    for entrant_index, client in enumerate([commissioner_client, player_client]):
        submit_early_picks(client, pool_url, early_window.id, ["BOS", "NYK"], ["OKC", "DEN"], entrant_index)
    lock_window_and_assert_revealed(commissioner_client, pool_url, early_window)

    create_window_response = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-18T19:00",
            "team_one": "BOS",
            "team_two": "ORL",
            "series_key": "",
            "next_tab": "commissioner",
        },
        follow_redirects=False,
    )
    assert create_window_response.status_code == 303

    window = find_window_by_series_key(pool_id, "round_1-BOS-ORL")
    hidden_matchup_page = commissioner_client.get(f"/pools/{pool_id}/matchups/round_1-BOS-ORL")
    assert hidden_matchup_page.status_code == 403
    submit_series_pick(commissioner_client, pool_url, window, 0, "BOS", 6)
    submit_series_pick(player_client, pool_url, window, 3, "BOS", 6)
    lock_window_and_assert_revealed(commissioner_client, pool_url, window)

    series_result_response = commissioner_client.post(
        f"{pool_url}/results",
        data={
            "scope_type": "series",
            "scope_key": "round_1-BOS-ORL",
            "result_winner": "BOS",
            "result_games_count": "6",
            "bet_type": "series",
            "display_score": "Boston won 4-2",
            "source": "manual",
        },
        follow_redirects=False,
    )
    assert series_result_response.status_code == 303

    for field_name, value in [
        ("conference_finalists_east", "BOS"),
        ("conference_finalists_west", "OKC"),
        ("nba_finalists_east", "BOS"),
        ("nba_finalists_west", "OKC"),
        ("champion", "BOS"),
        ("finals_mvp", "Jayson Tatum"),
    ]:
        response = commissioner_client.post(
            f"{pool_url}/results/early-field",
            data={"field_name": field_name, "field_value": value},
            follow_redirects=False,
        )
        assert response.status_code == 303

    overview_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert overview_page.status_code == 200
    assert "Ceiling = current points plus the maximum points still available" in overview_page.text
    assert f"/pools/{pool_id}/matchups/round_1-BOS-ORL" in overview_page.text
    assert "Official result: Boston won 4-2" in overview_page.text

    closed_bets_page = commissioner_client.get(f"{pool_url}?tab=bets")
    assert closed_bets_page.status_code == 200
    assert "<table" in closed_bets_page.text
    assert "East CF" in closed_bets_page.text
    assert "Points from matchup" in closed_bets_page.text
    assert "Boston won 4-2" in closed_bets_page.text

    matchup_page = commissioner_client.get(f"/pools/{pool_id}/matchups/round_1-BOS-ORL")
    assert matchup_page.status_code == 200
    assert "Every player's bet and points" in matchup_page.text
    assert "Winner pick" in matchup_page.text
    assert "Point breakdown" in matchup_page.text
    assert "Winner pick: 1" in matchup_page.text
    assert "Exact result: 3" in matchup_page.text

    player_page = commissioner_client.get(re.search(rf"/pools/{pool_id}/players/([a-f0-9-]+)", overview_page.text).group(0))
    assert player_page.status_code == 200
    assert "Score breakdown" in player_page.text
    assert "Board" in player_page.text
    assert "Breakdown" in player_page.text


def test_first_place_player_can_post_highlighted_message() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Leader Message Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    join_response = player_client.post(
        f"/invite/{invite_token}",
        data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"},
        follow_redirects=False,
    )
    assert join_response.status_code == 303

    early_window = find_window_by_name(pool_id, "Early Picks")
    submit_early_picks(commissioner_client, pool_url, early_window.id, ["BOS", "NYK"], ["OKC", "DEN"], 0)
    submit_early_picks(player_client, pool_url, early_window.id, ["ORL", "PHI"], ["PHX", "MIN"], 1)
    lock_window_and_assert_revealed(commissioner_client, pool_url, early_window)
    for field_name, value in [
        ("conference_finalists_east", "BOS"),
        ("conference_finalists_west", "OKC"),
        ("nba_finalists_east", "BOS"),
        ("nba_finalists_west", "OKC"),
        ("champion", "BOS"),
        ("finals_mvp", "Jayson Tatum"),
    ]:
        response = commissioner_client.post(
            f"{pool_url}/results/early-field",
            data={"field_name": field_name, "field_value": value},
            follow_redirects=False,
        )
        assert response.status_code == 303

    page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert "Save highlighted message" in page.text

    message_response = commissioner_client.post(
        f"/pools/{pool_id}/leader-message",
        data={"message": "Still on top. Catch me if you can."},
        follow_redirects=False,
    )
    assert message_response.status_code == 303

    updated_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert "Still on top. Catch me if you can." in updated_page.text

    denied_response = player_client.post(
        f"/pools/{pool_id}/leader-message",
        data={"message": "I should not be allowed to post this."},
        follow_redirects=False,
    )
    assert denied_response.status_code == 403


def test_full_five_player_league_flow() -> None:
    commissioner_client = TestClient(app)
    other_clients = [TestClient(app) for _ in range(4)]
    pool_url = create_pool(commissioner_client, "Full League Pool")

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_names = ["Avi", "Ben", "Chen", "Dana"]
    all_clients = [commissioner_client]
    member_names = ["Gil"]
    for name, client in zip(player_names, other_clients, strict=False):
        join_response = client.post(
            f"/invite/{invite_token}",
            data={"nickname": name, "email": f"{name.lower()}@example.com", "avatar": "🔥"},
            follow_redirects=False,
        )
        assert join_response.status_code == 303
        all_clients.append(client)
        member_names.append(name)

    round_windows = [
        ("round_1", "BOS", "ORL"),
        ("round_2", "NYK", "MIL"),
        ("conference_finals", "CLE", "BOS"),
        ("finals", "BOS", "OKC"),
    ]
    for round_key, team_one, team_two in round_windows:
        create_window_response = commissioner_client.post(
            f"{pool_url}/windows",
            data={
                "name": "",
                "round_key": round_key,
                "bet_type": "series",
                "opens_at": "2026-04-14T12:00",
                "locks_at": "2026-04-18T19:00",
                "team_one": team_one,
                "team_two": team_two,
                "series_key": "",
                "next_tab": "commissioner",
            },
            follow_redirects=False,
        )
        assert create_window_response.status_code == 303

    first_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert first_page.status_code == 200
    pool_id = pool_id_from_url(pool_url)
    windows = fetch_windows(pool_id)
    early_window_id = next(window.id for window in windows if window.bet_type == "early")
    for client, name in zip(all_clients, member_names, strict=False):
        early_submit = client.post(
            f"{pool_url}/submit-all",
            data={
                "conference_finalists_east": "BOS",
                "conference_finalists_west": "OKC",
                "nba_finalists_east": "BOS",
                "nba_finalists_west": "OKC",
                "champion": "BOS",
                "finals_mvp": "Jayson Tatum",
            },
            follow_redirects=False,
        )
        assert early_submit.status_code == 303, name

    series_keys = [
        "round_1-BOS-ORL",
        "round_2-NYK-MIL",
        "conference_finals-CLE-BOS",
        "finals-BOS-OKC",
    ]
    for client, name in zip(all_clients, member_names, strict=False):
        payload = {}
        for series_key in series_keys:
            teams = series_key.split("-")[1:]
            winner = "BOS" if "BOS" in teams else teams[0]
            payload[f"winner_{series_key}"] = winner
            payload[f"games_count_{series_key}"] = "6"
        submit = client.post(f"{pool_url}/submit-all", data=payload, follow_redirects=False)
        assert submit.status_code == 303, name

    round_one_window_id = next(window.id for window in windows if any(series.get("series_key") == "round_1-BOS-ORL" for series in window.config.get("series", [])))
    lock_response = commissioner_client.post(f"{pool_url}/windows/{round_one_window_id}/lock", follow_redirects=False)
    assert lock_response.status_code == 303

    pool_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert pool_page.status_code == 200
    assert "Full League Pool" in pool_page.text

    for field_name, value in [
        ("conference_finalists_east", "BOS"),
        ("conference_finalists_west", "OKC"),
        ("nba_finalists_east", "BOS"),
        ("nba_finalists_west", "OKC"),
        ("champion", "BOS"),
        ("finals_mvp", "Jayson Tatum"),
    ]:
        early_result = commissioner_client.post(
            f"{pool_url}/results/early-field",
            data={"field_name": field_name, "field_value": value},
            follow_redirects=False,
        )
        assert early_result.status_code == 303

    for series_key in series_keys:
        teams = series_key.split("-")[1:]
        winner = "BOS" if "BOS" in teams else teams[0]
        result_response = commissioner_client.post(
            f"{pool_url}/results",
            data={
                "scope_type": "series",
                "scope_key": series_key,
                "result_winner": winner,
                "result_games_count": "6",
                "bet_type": "series",
                "source": "manual",
            },
            follow_redirects=False,
        )
        assert result_response.status_code == 303, series_key

        final_page = commissioner_client.get(f"{pool_url}?tab=overview")
        assert final_page.status_code == 200
        for name in member_names:
            assert name in final_page.text
        assert "The Monkey" in final_page.text
        assert "Save marked picks" in final_page.text


def test_monkey_auto_submits_and_sign_out_flow() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Monkey Pool")

    overview_page = commissioner_client.get(f"{pool_url}?tab=overview")
    assert overview_page.status_code == 200
    assert "Sign out" in overview_page.text

    commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "",
            "round_key": "play_in",
            "bet_type": "play_in",
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-14T19:00",
            "team_one": "ATL",
            "team_two": "ORL",
            "series_key": "",
            "next_tab": "commissioner",
        },
        follow_redirects=False,
    )
    actions = re.findall(r'action="([^"]+/lock)"', commissioner_client.get(f"{pool_url}?tab=overview").text)
    assert actions
    commissioner_client.post(actions[-1], follow_redirects=False)
    bets_page = commissioner_client.get(f"{pool_url}?tab=bets")
    assert "The Monkey" in bets_page.text

    sign_out = commissioner_client.post(f"{pool_url}/signout", follow_redirects=False)
    assert sign_out.status_code == 303
    guest_page = commissioner_client.get(sign_out.headers["location"])
    assert "Sign in to this pool" in guest_page.text


def test_generate_bracket_and_hide_result_feed_from_players() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Bracket Pool")
    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    data = {"opens_at": "2026-04-14T12:00", "locks_at": "2026-04-16T19:00"}
    east = ["CLE", "BOS", "NYK", "IND", "MIL", "DET", "ORL", "ATL", "CHI", "MIA"]
    west = ["OKC", "HOU", "LAL", "DEN", "MIN", "GSW", "MEM", "SAC", "DAL", "PHX"]
    for idx, team in enumerate(east, start=1):
        data[f"east_seed_{idx}"] = team
    for idx, team in enumerate(west, start=1):
        data[f"west_seed_{idx}"] = team
    response = commissioner_client.post(f"{pool_url}/generate-bracket", data=data, follow_redirects=False)
    assert response.status_code == 303

    bracket_page = commissioner_client.get(f"{pool_url}?tab=bracket")
    assert bracket_page.status_code == 200
    assert "East Play-In" in bracket_page.text
    assert "West Semifinals" in bracket_page.text
    assert "7th" in bracket_page.text
    assert "8 seed" in bracket_page.text
    assert "3rd" in bracket_page.text
    assert "6th" in bracket_page.text

    player_page = player_client.get(f"{pool_url}?tab=overview")
    assert player_page.status_code == 200
    assert "Commissioner-only audit log" not in player_page.text


def test_side_bets_tab_supports_create_submit_auto_lock_and_approval() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Side Bets Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    create_response = commissioner_client.post(
        f"{pool_url}/side-bets",
        data={
            "question": "Who scores first in Game 1?",
            "answer": "Deni Avdija",
            "points_value": "3",
            "opens_at": "2026-04-15T12:00",
            "locks_at": "2026-04-16T15:00",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    side_bets_page = commissioner_client.get(f"{pool_url}?tab=side_bets")
    assert side_bets_page.status_code == 200
    assert "Who scores first in Game 1?" in side_bets_page.text
    assert "Create side bet" in side_bets_page.text
    assert "Worth 3 points" in side_bets_page.text

    with SessionLocal() as session:
        context_before_submit = load_pool_context(session, pool_id)
        avi_before_submit = next(row for row in context_before_submit["leaderboard_rows"] if row["display_name"] == "Avi")
        assert avi_before_submit["projected_ceiling"] >= 19

    with SessionLocal() as session:
        side_bet = session.scalar(select(SideBet).where(SideBet.pool_id == pool_id))
        assert side_bet is not None
        side_bet_id = side_bet.id

    submit_response = player_client.post(
        f"{pool_url}/side-bets/{side_bet_id}/submit",
        data={"answer": "deni avdija"},
        follow_redirects=True,
    )
    assert submit_response.status_code == 200
    assert "Your side-bet answer was saved." in submit_response.text
    assert "You already answered this side bet. Current answer: deni avdija" in submit_response.text

    commissioner_review_page = commissioner_client.get(f"{pool_url}?tab=side_bets")
    assert commissioner_review_page.status_code == 200
    assert "Matches official answer" in commissioner_review_page.text
    assert "Auto match" in commissioner_review_page.text
    assert "Points From Bet" in commissioner_review_page.text
    assert "Approval override" in commissioner_review_page.text
    assert ">3<" in commissioner_review_page.text

    side_bet_table = commissioner_client.get(f"/pools/{pool_id}/side-bets/{side_bet_id}/table")
    assert side_bet_table.status_code == 200
    assert "Every player's side-bet answer and points" in side_bet_table.text
    assert "deni avdija" in side_bet_table.text

    with SessionLocal() as session:
        submission = session.scalar(select(SideBetSubmission).where(SideBetSubmission.side_bet_id == side_bet_id))
        assert submission is not None
        submission_id = submission.id

    approve_response = commissioner_client.post(
        f"/pools/{pool_id}/side-bets/{side_bet_id}/submissions/{submission_id}/approval",
        data={"decision": "approve"},
        follow_redirects=True,
    )
    assert approve_response.status_code == 200
    assert "Side-bet approval updated." in approve_response.text
    assert "Approved" in approve_response.text
    assert ">3<" in approve_response.text

    with SessionLocal() as session:
        context_after_approval = load_pool_context(session, pool_id)
        avi_after_approval = next(row for row in context_after_approval["leaderboard_rows"] if row["display_name"] == "Avi")
        assert avi_after_approval["total_points"] >= 3

    player_side_bet_table_hidden = player_client.get(f"/pools/{pool_id}/side-bets/{side_bet_id}/table")
    assert player_side_bet_table_hidden.status_code == 403
    player_side_bets_open_page = player_client.get(f"{pool_url}?tab=side_bets")
    assert "View pick table" not in player_side_bets_open_page.text

    schedule_response = commissioner_client.post(
        f"/pools/{pool_id}/side-bets/{side_bet_id}/schedule",
        data={"opens_at": "2026-04-10T10:00", "locks_at": "2026-04-11T10:00"},
        follow_redirects=False,
    )
    assert schedule_response.status_code == 303

    locked_submit = player_client.post(
        f"{pool_url}/side-bets/{side_bet_id}/submit",
        data={"answer": "someone else"},
        follow_redirects=True,
    )
    assert locked_submit.status_code == 200
    assert "This side bet is closed." in locked_submit.text

    with SessionLocal() as session:
        refreshed = session.get(SideBet, side_bet_id)
        assert refreshed is not None
        assert refreshed.is_locked is True

    player_side_bet_table_visible = player_client.get(f"/pools/{pool_id}/side-bets/{side_bet_id}/table")
    assert player_side_bet_table_visible.status_code == 200
    player_side_bets_locked_page = player_client.get(f"{pool_url}?tab=side_bets")
    assert "View pick table" in player_side_bets_locked_page.text


def test_commissioner_can_delete_side_bet() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Delete Side Bet Pool")
    pool_id = pool_id_from_url(pool_url)

    create_response = commissioner_client.post(
        f"{pool_url}/side-bets",
        data={
            "question": "First coach challenge?",
            "answer": "Portland Trail Blazers",
            "points_value": "2",
            "opens_at": "2026-04-15T12:00",
            "locks_at": "2026-04-16T15:00",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    with SessionLocal() as session:
        side_bet = session.scalar(select(SideBet).where(SideBet.pool_id == pool_id))
        assert side_bet is not None
        side_bet_id = side_bet.id

    delete_response = commissioner_client.post(
        f"/pools/{pool_id}/side-bets/{side_bet_id}/delete",
        follow_redirects=True,
    )
    assert delete_response.status_code == 200
    assert "Deleted side bet: First coach challenge?" in delete_response.text

    with SessionLocal() as session:
        assert session.get(SideBet, side_bet_id) is None


def test_downstream_window_names_update_after_progression() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Progression Names Pool")
    pool_id = pool_id_from_url(pool_url)

    data = {"opens_at": "2026-04-14T12:00", "locks_at": "2026-04-16T19:00"}
    east = ["BOS", "CLE", "NYK", "DET", "ORL", "PHI", "MIA", "CHA", "ATL", "TOR"]
    west = ["OKC", "DEN", "MIN", "LAL", "LAC", "GSW", "PHX", "POR", "HOU", "SAS"]
    for idx, team in enumerate(east, start=1):
        data[f"east_seed_{idx}"] = team
    for idx, team in enumerate(west, start=1):
        data[f"west_seed_{idx}"] = team
    response = commissioner_client.post(f"{pool_url}/generate-bracket", data=data, follow_redirects=False)
    assert response.status_code == 303

    east_8seed = find_window_by_series_key(pool_id, "play_in-east-8seed")
    east_round_1 = find_window_by_series_key(pool_id, "round_1-east-1v8")
    east_round_2 = find_window_by_series_key(pool_id, "round_2-east-top")
    finals_window = find_window_by_series_key(pool_id, "finals-nba")

    assert east_8seed.name == "East Play-In: No. 8 seed decider"
    assert east_round_1.name == "East Round 1: Boston Celtics vs East #8"
    assert east_round_2.name == "East Semifinal: Winner 1/8 vs Winner 4/5"
    assert finals_window.name == "NBA Finals"

    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "play_in-east-7v8"), "MIA")
    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "play_in-east-9v10"), "ATL")
    save_series_result(commissioner_client, pool_url, east_8seed, "ATL")

    east_8seed = find_window_by_series_key(pool_id, "play_in-east-8seed")
    east_round_1 = find_window_by_series_key(pool_id, "round_1-east-1v8")
    assert east_8seed.name == "East Play-In: Charlotte Hornets vs Atlanta Hawks"
    assert east_round_1.name == "East Round 1: Boston Celtics vs Atlanta Hawks"

    save_series_result(commissioner_client, pool_url, east_round_1, "BOS", 6)
    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "round_1-east-4v5"), "DET", 6)
    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "round_1-west-1v8"), "OKC", 6)
    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "round_1-west-4v5"), "LAL", 6)

    east_round_2 = find_window_by_series_key(pool_id, "round_2-east-top")
    west_round_2 = find_window_by_series_key(pool_id, "round_2-west-top")
    assert east_round_2.name == "East Semifinal: Boston Celtics vs Detroit Pistons"
    assert west_round_2.name == "West Semifinal: Oklahoma City Thunder vs Los Angeles Lakers"

    save_series_result(commissioner_client, pool_url, east_round_2, "BOS", 6)
    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "round_2-east-bottom"), "NYK", 6)
    save_series_result(commissioner_client, pool_url, west_round_2, "OKC", 6)
    save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, "round_2-west-bottom"), "MIN", 6)

    east_finals = find_window_by_series_key(pool_id, "conference_finals-east")
    west_finals = find_window_by_series_key(pool_id, "conference_finals-west")
    assert east_finals.name == "East Conference Finals: Boston Celtics vs New York Knicks"
    assert west_finals.name == "West Conference Finals: Oklahoma City Thunder vs Minnesota Timberwolves"

    save_series_result(commissioner_client, pool_url, east_finals, "BOS", 6)
    save_series_result(commissioner_client, pool_url, west_finals, "OKC", 6)

    finals_window = find_window_by_series_key(pool_id, "finals-nba")
    assert finals_window.name == "NBA Finals: Boston Celtics vs Oklahoma City Thunder"

    commissioner_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert commissioner_page.status_code == 200
    assert "East Round 1: Boston Celtics vs Atlanta Hawks" in commissioner_page.text
    assert "East Semifinal: Boston Celtics vs Detroit Pistons" in commissioner_page.text
    assert "NBA Finals: Boston Celtics vs Oklahoma City Thunder" in commissioner_page.text


def test_load_pool_context_repairs_stale_downstream_window_names() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Stale Names Pool")
    pool_id = pool_id_from_url(pool_url)

    data = {"opens_at": "2026-04-14T12:00", "locks_at": "2026-04-16T19:00"}
    east = ["BOS", "CLE", "NYK", "DET", "ORL", "PHI", "MIA", "CHA", "ATL", "TOR"]
    west = ["OKC", "DEN", "MIN", "LAL", "LAC", "GSW", "PHX", "POR", "SAS", "HOU"]
    for idx, team in enumerate(east, start=1):
        data[f"east_seed_{idx}"] = team
    for idx, team in enumerate(west, start=1):
        data[f"west_seed_{idx}"] = team
    response = commissioner_client.post(f"{pool_url}/generate-bracket", data=data, follow_redirects=False)
    assert response.status_code == 303

    west_7v8 = find_window_by_series_key(pool_id, "play_in-west-7v8")
    west_9v10 = find_window_by_series_key(pool_id, "play_in-west-9v10")
    west_2v7 = find_window_by_series_key(pool_id, "round_1-west-2v7")

    save_series_result(commissioner_client, pool_url, west_7v8, "POR")
    with SessionLocal() as session:
        stale_window = session.get(BettingWindow, west_2v7.id)
        assert stale_window is not None
        stale_window.name = "West Round 1: San Antonio Spurs vs West #7"
        session.commit()

    commissioner_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert commissioner_page.status_code == 200
    assert "West Round 1: Denver Nuggets vs Portland Trail Blazers" in commissioner_page.text
    assert "West Round 1: San Antonio Spurs vs West #7" not in commissioner_page.text


def test_full_random_bracket_simulation_through_finals() -> None:
    rng = random.Random(20260413)
    commissioner_client = TestClient(app)
    player_clients = [TestClient(app) for _ in range(10)]
    pool_url = create_pool(commissioner_client, "Full Bracket Simulation")
    pool_id = pool_id_from_url(pool_url)

    grouped_teams = teams_by_conference()
    east_seeds = [team.code for team in rng.sample(grouped_teams["East"], 10)]
    west_seeds = [team.code for team in rng.sample(grouped_teams["West"], 10)]

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    all_human_clients = [commissioner_client]
    for index, client in enumerate(player_clients, start=1):
        join_response = client.post(
            f"/invite/{invite_token}",
            data={"nickname": f"Player {index}", "email": f"player{index}@example.com", "avatar": "🔥"},
            follow_redirects=False,
        )
        assert join_response.status_code == 303
        all_human_clients.append(client)

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
    assert bracket_response.status_code == 303

    bracket_page = commissioner_client.get(f"{pool_url}?tab=bracket")
    assert bracket_page.status_code == 200
    assert TEAM_BY_CODE[east_seeds[6]].name in bracket_page.text
    assert TEAM_BY_CODE[west_seeds[9]].name in bracket_page.text
    assert "Conference Finals" in bracket_page.text
    assert "NBA Finals" in bracket_page.text

    windows = fetch_windows(pool_id)
    assert len(windows) == 22, f"Expected 22 windows including early picks, got {len(windows)}."

    early_window = find_window_by_name(pool_id, "Early Picks")
    for entrant_index, client in enumerate(all_human_clients):
        submit_early_picks(client, pool_url, early_window.id, east_seeds, west_seeds, entrant_index)
    assert_monkey_submission(pool_id, early_window.id, "Early Picks")

    initial_play_in_keys = [
        "play_in-east-7v8",
        "play_in-east-9v10",
        "play_in-west-7v8",
        "play_in-west-9v10",
    ]
    initial_play_in_results = {
        "play_in-east-7v8": east_seeds[6],
        "play_in-east-9v10": east_seeds[8],
        "play_in-west-7v8": west_seeds[6],
        "play_in-west-9v10": west_seeds[9],
    }
    for series_key in initial_play_in_keys:
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(all_human_clients):
            submit_series_pick(client, pool_url, window, entrant_index, initial_play_in_results[series_key], actual_games_count=1)
        assert_monkey_submission(pool_id, window.id, series_key)
        lock_window_and_assert_revealed(commissioner_client, pool_url, window)

    unlock_window_and_assert_open(commissioner_client, pool_url, find_window_by_series_key(pool_id, "play_in-west-9v10"))
    lock_window_and_assert_revealed(commissioner_client, pool_url, find_window_by_series_key(pool_id, "play_in-west-9v10"))

    closed_bets_after_play_in_lock = commissioner_client.get(f"{pool_url}?tab=bets")
    assert closed_bets_after_play_in_lock.status_code == 200
    assert "The Monkey" in closed_bets_after_play_in_lock.text

    lock_window_and_assert_revealed(commissioner_client, pool_url, early_window)

    points_before_results = leaderboard_points(pool_id)
    for series_key, winner in initial_play_in_results.items():
        save_series_result(commissioner_client, pool_url, find_window_by_series_key(pool_id, series_key), winner, games_count=1)
        assert_result_exists(pool_id, series_key)

    east_decider = find_window_by_series_key(pool_id, "play_in-east-8seed")
    west_decider = find_window_by_series_key(pool_id, "play_in-west-8seed")
    east_two_seven = find_window_by_series_key(pool_id, "round_1-east-2v7")
    west_two_seven = find_window_by_series_key(pool_id, "round_1-west-2v7")
    assert east_decider.config["series"][0]["teams"] == [east_seeds[7], east_seeds[8]], f"East 8-seed decider teams did not update correctly: {east_decider.config['series'][0]['teams']}"
    assert west_decider.config["series"][0]["teams"] == [west_seeds[7], west_seeds[9]], f"West 8-seed decider teams did not update correctly: {west_decider.config['series'][0]['teams']}"
    assert east_two_seven.config["series"][0]["teams"] == [east_seeds[1], east_seeds[6]]
    assert west_two_seven.config["series"][0]["teams"] == [west_seeds[1], west_seeds[6]]
    assert_monkey_submission(pool_id, east_decider.id, "play_in-east-8seed")
    assert_monkey_submission(pool_id, west_decider.id, "play_in-west-8seed")
    assert_monkey_submission(pool_id, east_two_seven.id, "round_1-east-2v7")
    assert_monkey_submission(pool_id, west_two_seven.id, "round_1-west-2v7")

    decider_results = {
        "play_in-east-8seed": east_seeds[7],
        "play_in-west-8seed": west_seeds[9],
    }
    for series_key, winner in decider_results.items():
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(all_human_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=1)
        lock_window_and_assert_revealed(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=1)
        assert_result_exists(pool_id, series_key)

    east_one_eight = find_window_by_series_key(pool_id, "round_1-east-1v8")
    west_one_eight = find_window_by_series_key(pool_id, "round_1-west-1v8")
    assert east_one_eight.config["series"][0]["teams"] == [east_seeds[0], east_seeds[7]]
    assert west_one_eight.config["series"][0]["teams"] == [west_seeds[0], west_seeds[9]]
    assert_monkey_submission(pool_id, east_one_eight.id, "round_1-east-1v8")
    assert_monkey_submission(pool_id, west_one_eight.id, "round_1-west-1v8")

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
        for entrant_index, client in enumerate(all_human_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=games_count)
        lock_window_and_assert_revealed(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=games_count)
        assert_result_exists(pool_id, series_key)

    round_two_expected = {
        "round_2-east-top": [east_seeds[0], east_seeds[4]],
        "round_2-east-bottom": [east_seeds[1], east_seeds[2]],
        "round_2-west-top": [west_seeds[0], west_seeds[3]],
        "round_2-west-bottom": [west_seeds[6], west_seeds[2]],
    }
    for series_key, teams in round_two_expected.items():
        window = find_window_by_series_key(pool_id, series_key)
        assert window.config["series"][0]["teams"] == teams, f"{series_key} did not update correctly. Expected {teams}, got {window.config['series'][0]['teams']}"
        assert_monkey_submission(pool_id, window.id, series_key)

    points_after_round_one = leaderboard_points(pool_id)
    assert any(points_after_round_one[member_id] > points_before_results.get(member_id, 0) for member_id in points_after_round_one), (
        "Scores did not increase after Play-In and Round 1 results."
    )

    round_two_outcomes = {
        "round_2-east-top": (east_seeds[0], 6),
        "round_2-east-bottom": (east_seeds[2], 7),
        "round_2-west-top": (west_seeds[0], 5),
        "round_2-west-bottom": (west_seeds[2], 6),
    }
    for series_key, (winner, games_count) in round_two_outcomes.items():
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(all_human_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=games_count)
        lock_window_and_assert_revealed(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=games_count)
        assert_result_exists(pool_id, series_key)

    conference_finals_expected = {
        "conference_finals-east": [east_seeds[0], east_seeds[2]],
        "conference_finals-west": [west_seeds[0], west_seeds[2]],
    }
    for series_key, teams in conference_finals_expected.items():
        window = find_window_by_series_key(pool_id, series_key)
        assert window.config["series"][0]["teams"] == teams, f"{series_key} did not update correctly. Expected {teams}, got {window.config['series'][0]['teams']}"
        assert_monkey_submission(pool_id, window.id, series_key)

    conference_finals_outcomes = {
        "conference_finals-east": (east_seeds[0], 6),
        "conference_finals-west": (west_seeds[0], 7),
    }
    for series_key, (winner, games_count) in conference_finals_outcomes.items():
        window = find_window_by_series_key(pool_id, series_key)
        for entrant_index, client in enumerate(all_human_clients):
            submit_series_pick(client, pool_url, window, entrant_index, winner, actual_games_count=games_count)
        lock_window_and_assert_revealed(commissioner_client, pool_url, window)
        save_series_result(commissioner_client, pool_url, window, winner, games_count=games_count)
        assert_result_exists(pool_id, series_key)

    finals_window = find_window_by_series_key(pool_id, "finals-nba")
    assert finals_window.config["series"][0]["teams"] == [east_seeds[0], west_seeds[0]], (
        f"NBA Finals teams did not update correctly: {finals_window.config['series'][0]['teams']}"
    )
    assert_monkey_submission(pool_id, finals_window.id, "finals-nba")

    for entrant_index, client in enumerate(all_human_clients):
        submit_series_pick(client, pool_url, finals_window, entrant_index, east_seeds[0], actual_games_count=7)
    lock_window_and_assert_revealed(commissioner_client, pool_url, finals_window)
    save_series_result(commissioner_client, pool_url, finals_window, east_seeds[0], games_count=7)
    assert_result_exists(pool_id, "finals-nba")

    finals_mvp_options = players_for_teams([east_seeds[0], west_seeds[0]])
    early_results = [
        ("conference_finalists_east", east_seeds[0]),
        ("conference_finalists_west", west_seeds[0]),
        ("nba_finalists_east", east_seeds[0]),
        ("nba_finalists_west", west_seeds[0]),
        ("champion", east_seeds[0]),
        ("finals_mvp", finals_mvp_options[0]),
    ]
    for field_name, field_value in early_results:
        response = commissioner_client.post(
            f"{pool_url}/results/early-field",
            data={"field_name": field_name, "field_value": field_value},
            follow_redirects=False,
        )
        assert response.status_code == 303, f"Saving early result field {field_name} failed with {response.status_code}."
    assert_result_exists(pool_id, "season", scope_type="early")

    points_after_early_results = leaderboard_points(pool_id)
    assert any(
        points_after_early_results[member_id] > points_after_round_one.get(member_id, 0)
        for member_id in points_after_early_results
    ), "Early-result updates did not change any leaderboard totals."

    assert_core_pages_ok(commissioner_client, pool_url, commissioner=True)
    assert_core_pages_ok(player_clients[0], pool_url, commissioner=False)

    export_response = commissioner_client.get(f"{pool_url}/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"


def test_commissioner_can_delete_a_window() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Delete Pool")

    create_window_response = commissioner_client.post(
        f"{pool_url}/windows",
        data={
            "name": "",
            "round_key": "round_1",
            "bet_type": "series",
            "opens_at": "2026-04-14T12:00",
            "locks_at": "2026-04-18T19:00",
            "team_one": "BOS",
            "team_two": "ORL",
            "series_key": "",
            "next_tab": "commissioner",
        },
        follow_redirects=False,
    )
    assert create_window_response.status_code == 303

    commissioner_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert "Round 1: Boston Celtics vs Orlando Magic" in commissioner_page.text

    delete_actions = re.findall(r'action="([^"]+/delete)"', commissioner_page.text)
    assert delete_actions
    delete_response = commissioner_client.post(delete_actions[-1], follow_redirects=False)
    assert delete_response.status_code == 303

    updated_page = commissioner_client.get(f"{pool_url}?tab=commissioner")
    assert updated_page.status_code == 200
    assert "Round 1: Boston Celtics vs Orlando Magic" not in updated_page.text


def test_locked_submit_redirects_back_with_message() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Locked Window Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    window = find_window_by_name(pool_id, "Early Picks")
    lock_window_and_assert_revealed(commissioner_client, pool_url, window)

    response = player_client.post(
        f"{pool_url}/windows/{window.id}/submit",
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
    assert response.status_code == 200
    assert "The bet is closed, you can bag to Gil" in response.text
    assert "Locked Window Pool" in response.text


def test_bulk_result_save_persists_multiple_marked_games_and_saved_badges() -> None:
    commissioner_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Bulk Results Pool")
    pool_id = pool_id_from_url(pool_url)

    for round_key, bet_type, team_one, team_two in [("play_in", "play_in", "ATL", "ORL"), ("round_1", "series", "BOS", "NYK")]:
        response = commissioner_client.post(
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
        assert response.status_code == 303

    save_response = commissioner_client.post(
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
    assert save_response.status_code == 200
    assert "Saved 2 marked result(s)." in save_response.text
    assert_result_exists(pool_id, "play_in-ATL-ORL")
    assert_result_exists(pool_id, "round_1-BOS-NYK")
    assert "111-104" in save_response.text
    assert "Saved result: Boston won 4-2" in save_response.text


def test_bulk_player_save_persists_valid_games_and_skips_incomplete_ones() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Bulk Player Picks Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    for team_one, team_two in [("BOS", "NYK"), ("CLE", "ORL")]:
        response = commissioner_client.post(
            f"{pool_url}/windows",
            data={
                "name": "",
                "round_key": "round_1",
                "bet_type": "series",
                "opens_at": "2026-04-14T12:00",
                "locks_at": "2026-04-18T19:00",
                "team_one": team_one,
                "team_two": team_two,
                "series_key": "",
                "next_tab": "overview",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    save_response = player_client.post(
        f"{pool_url}/submit-all",
        data={
            "winner_round_1-BOS-NYK": "BOS",
            "games_count_round_1-BOS-NYK": "6",
            "games_count_round_1-CLE-ORL": "7",
        },
        follow_redirects=True,
    )
    assert save_response.status_code == 200
    assert "Saved 1 marked pick board(s)." in save_response.text
    assert "Skipped 1 incomplete board(s)." in save_response.text
    assert "Cleveland Cavaliers vs Orlando Magic" in save_response.text

    with SessionLocal() as session:
        membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "Avi")
        )
        assert membership is not None
        saved_submission = session.scalar(
            select(PickSubmission).where(
                PickSubmission.member_id == membership.id,
                    PickSubmission.window_id == find_window_by_name(pool_id, "East Round 1: Boston Celtics vs New York Knicks").id,
            )
        )
        assert saved_submission is not None


def test_commissioner_can_manage_members_and_delete_pool() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Manage Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    with SessionLocal() as session:
        avi_membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "Avi")
        )
        assert avi_membership is not None
        avi_member_id = avi_membership.id

    rename_response = commissioner_client.post(
        f"/pools/{pool_id}/members/{avi_member_id}/rename",
        data={"nickname": "Avi Prime"},
        follow_redirects=True,
    )
    assert rename_response.status_code == 200
    assert "Updated Avi Prime." in rename_response.text

    delete_response = commissioner_client.post(
        f"/pools/{pool_id}/members/{avi_member_id}/delete",
        follow_redirects=True,
    )
    assert delete_response.status_code == 200
    assert "Removed Avi Prime from the tournament." in delete_response.text

    pool_delete = commissioner_client.post(f"/pools/{pool_id}/delete", follow_redirects=False)
    assert pool_delete.status_code == 303
    homepage = commissioner_client.get(pool_delete.headers["location"])
    assert homepage.status_code == 200
    assert "Manage Pool" not in homepage.text


def test_overview_ordering_saved_banners_and_player_missing_picks() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Ordering Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    setup_windows = [
        ("play_in", "play_in", "ATL", "ORL"),
        ("round_1", "series", "BOS", "NYK"),
        ("conference_finals", "series", "OKC", "MIN"),
    ]
    for round_key, bet_type, team_one, team_two in setup_windows:
        commissioner_client.post(
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

    play_in_window = find_window_by_series_key(pool_id, "play_in-ATL-ORL")
    player_client.post(f"{pool_url}/windows/{play_in_window.id}/submit", data={"winner_play_in-ATL-ORL": "ATL"}, follow_redirects=False)

    overview = player_client.get(f"{pool_url}?tab=overview")
    assert overview.status_code == 200
    early_idx = overview.text.index("Early Picks")
    play_in_idx = overview.text.index("Play-In: Atlanta Hawks vs Orlando Magic")
    round_one_idx = overview.text.index("Round 1: Boston Celtics vs New York Knicks")
    conference_idx = overview.text.index("Conference Finals: Oklahoma City Thunder vs Minnesota Timberwolves")
    assert early_idx < play_in_idx < round_one_idx < conference_idx
    assert "You already bet this game." in overview.text

    with SessionLocal() as session:
        player_membership = session.scalar(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "Avi")
        )
        assert player_membership is not None
        player_member_id = player_membership.id
    player_page = player_client.get(f"/pools/{pool_id}/players/{player_member_id}")
    assert player_page.status_code == 200
    assert "Boards still waiting on this player" in player_page.text
    assert "Boston Celtics vs New York Knicks" in player_page.text


def test_player_can_save_multiple_marked_pick_boards_together() -> None:
    commissioner_client = TestClient(app)
    player_client = TestClient(app)
    pool_url = create_pool(commissioner_client, "Bulk Picks Pool")
    pool_id = pool_id_from_url(pool_url)

    invite_token = re.search(r"/invite/([A-Za-z0-9_-]+)", commissioner_client.get(f"{pool_url}?tab=overview").text).group(1)
    player_client.post(f"/invite/{invite_token}", data={"nickname": "Avi", "email": "avi@example.com", "avatar": "🔥"}, follow_redirects=False)

    for round_key, bet_type, team_one, team_two in [("play_in", "play_in", "ATL", "ORL"), ("round_1", "series", "BOS", "NYK")]:
        commissioner_client.post(
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

    save_response = player_client.post(
        f"{pool_url}/submit-all",
        data={
            "winner_play_in-ATL-ORL": "ATL",
            "winner_round_1-BOS-NYK": "BOS",
            "games_count_round_1-BOS-NYK": "6",
        },
        follow_redirects=True,
    )
    assert save_response.status_code == 200
    assert "Saved 2 marked pick board(s)." in save_response.text

    with SessionLocal() as session:
        memberships = session.scalars(
            select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == pool_id, User.nickname == "Avi")
        ).all()
        assert memberships
        member_id = memberships[0].id
        windows = fetch_windows(pool_id)
        submissions = session.scalars(select(PickSubmission).where(PickSubmission.member_id == member_id)).all()
        saved_window_ids = {submission.window_id for submission in submissions}
        assert any(window.id in saved_window_ids and window.round_key == "play_in" for window in windows)
        assert any(window.id in saved_window_ids and window.round_key == "round_1" for window in windows)

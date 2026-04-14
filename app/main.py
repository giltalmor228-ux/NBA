from __future__ import annotations

import json
import random
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import decode_session, encode_session
from app.config import get_settings
from app.data.nba_catalog import TEAM_BY_CODE, TEAM_CATALOG, all_teams_grouped_for_select, players_for_teams
from app.db import get_session, init_db
from app.domain.scoring import MemberState, ResultEnvelope, SubmissionEnvelope, WindowEnvelope, leaderboard_as_dict, score_pool
from app.models import BettingWindow, EventLog, InviteLink, Membership, PaymentLedgerEntry, PickSubmission, Pool, ResultSnapshot, User
from app.services.automation import auto_lock_due_windows, start_scheduler
from app.services.recovery import export_bundle, restore_from_snapshot_json


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
settings = get_settings()
LOCAL_TZ = ZoneInfo("Asia/Jerusalem")

TEAM_NAMES = {team.code: team.name for team in TEAM_CATALOG}
TEAM_SELECT_GROUPS = all_teams_grouped_for_select()
ALL_PLAYER_OPTIONS = sorted({player for team in TEAM_CATALOG for player in team.players})
TEAM_PLAYER_LOOKUP = {team.code: list(team.players) for team in TEAM_CATALOG}
VALID_POOL_TABS = {"overview", "bets", "bracket", "commissioner"}
PLAY_IN_EXPLANATION = (
    "The NBA Play-In Tournament uses each conference's 7-10 seeds. The 7-vs-8 winner becomes the No. 7 seed, "
    "the 9-vs-10 loser is eliminated, and the loser of 7-vs-8 plays the winner of 9-vs-10 for the No. 8 seed."
)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    init_db()
    if settings.scheduler_enabled and not getattr(app_instance.state, "scheduler", None):
        app_instance.state.scheduler = start_scheduler()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static"), check_dir=False), name="static")


def team_name(abbreviation: str | None) -> str:
    if not abbreviation:
        return "TBD"
    normalized = abbreviation.upper()
    return TEAM_NAMES.get(normalized, normalized)


def team_logo(abbreviation: str | None) -> str:
    if not abbreviation:
        return "https://placehold.co/144x144/F2E8DE/5B5B5B?text=NBA"
    espn_slug_overrides = {
        "UTA": "utah",
    }
    normalized = abbreviation.upper()
    slug = espn_slug_overrides.get(normalized, normalized.lower())
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{slug}.png"


templates.env.globals["team_name"] = team_name
templates.env.globals["team_logo"] = team_logo


def current_membership(request: Request, session: Session) -> Membership | None:
    membership_id = decode_session(request.cookies.get(settings.session_cookie_name))
    if not membership_id:
        return None
    return session.get(Membership, membership_id)


def require_membership(request: Request, session: Session, pool_id: str) -> Membership:
    membership = current_membership(request, session)
    if not membership or membership.pool_id != pool_id:
        raise HTTPException(status_code=403, detail="Join the pool first.")
    return membership


def require_commissioner(request: Request, session: Session, pool_id: str) -> Membership:
    membership = require_membership(request, session, pool_id)
    if membership.role != "commissioner":
        raise HTTPException(status_code=403, detail="Commissioner access required.")
    return membership


def parse_iso_datetime(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(timezone.utc)


def local_input_value(offset_days: int = 0, hour: int = 12) -> str:
    local_dt = datetime.now(LOCAL_TZ).replace(minute=0, second=0, microsecond=0)
    local_dt = (local_dt + timedelta(days=offset_days)).replace(hour=hour)
    return local_dt.strftime("%Y-%m-%dT%H:%M")


def localize_datetime_input(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M")


def localize_datetime_display(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime("%d-%m-%Y %H:%M")


templates.env.globals["localize_datetime_display"] = localize_datetime_display


def generated_window_name(round_key: str, team_one: str, team_two: str) -> str:
    if round_key == "play_in":
        return f"Play-In: {team_name(team_one)} vs {team_name(team_two)}"
    round_label = round_key.replace("_", " ").title()
    if team_one and team_two:
        return f"{round_label}: {team_name(team_one)} vs {team_name(team_two)}"
    return round_label


def redirect_with_tab(pool_id: str, tab: str | None = None) -> str:
    safe_tab = tab if tab in VALID_POOL_TABS else "overview"
    return f"/pools/{pool_id}?tab={safe_tab}"


def redirect_with_message(pool_id: str, tab: str, status: str, message: str) -> str:
    query = urlencode({"tab": tab if tab in VALID_POOL_TABS else "overview", "flash_status": status, "flash_message": message})
    return f"/pools/{pool_id}?{query}"


def _series_priority(round_key: str, conference: str | None = None) -> int:
    if round_key == "play_in":
        return 0
    if round_key == "round_1":
        return 1
    if round_key == "round_2":
        return 2
    if round_key == "conference_finals":
        return 3 if (conference or "").lower() == "west" else 4
    if round_key == "finals":
        return 5
    return 6


def _window_sort_key(window: BettingWindow) -> tuple[int, int, int, datetime, datetime]:
    conference = None
    if window.config.get("series"):
        conference = window.config["series"][0].get("conference")
    is_early = 0 if window.bet_type == "early" else 1
    lock_group = 0 if not window.is_locked else 1
    return (is_early, lock_group, _series_priority(window.round_key, conference), window.opens_at, window.created_at)


def _matchup_row_sort_key(row: dict[str, Any]) -> tuple[int, int, int, datetime, datetime]:
    window = row["window"]
    conference = row.get("series", {}).get("conference") if row.get("series") else None
    is_early = 0 if row["type"] == "early" else 1
    lock_group = 0 if not window.is_locked else 1
    return (is_early, lock_group, _series_priority(window.round_key, conference), window.opens_at, window.created_at)


def latest_result_payloads(items: list[ResultSnapshot]) -> dict[tuple[str, str], dict[str, Any]]:
    payloads: dict[tuple[str, str], dict[str, Any]] = {}
    ordered = sorted(items, key=lambda item: (item.scope_type, item.scope_key, item.created_at, item.is_override))
    for item in ordered:
        payloads[(item.scope_type, item.scope_key)] = item.payload
    return payloads


def _slot_label(slot: dict[str, Any]) -> str:
    if slot["type"] == "team":
        return team_name(slot.get("team"))
    if slot["type"] == "seed":
        return f"{slot['conference']} #{slot['seed']}"
    if slot["type"] == "winner_of":
        return f"Winner of {slot['series_key']}"
    if slot["type"] == "loser_of":
        return f"Loser of {slot['series_key']}"
    if slot["type"] == "play_in_seed":
        return f"{slot['conference']} #{slot['seed']}"
    return "TBD"


def _seed_ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _slot_seed_text(slot: dict[str, Any]) -> str | None:
    slot_type = slot.get("type")
    if slot_type == "seed":
        seed = slot.get("seed")
        if seed:
            return _seed_ordinal(int(seed))
    if slot_type == "play_in_seed":
        seed = slot.get("seed")
        if seed:
            return f"{seed} seed"
    if slot_type == "winner_of":
        series_key = str(slot.get("series_key") or "")
        if series_key.endswith("7v8"):
            return "Winner 7/8"
        if series_key.endswith("9v10"):
            return "Winner 9/10"
    if slot_type == "loser_of":
        series_key = str(slot.get("series_key") or "")
        if series_key.endswith("7v8"):
            return "Loser 7/8"
        if series_key.endswith("9v10"):
            return "Loser 9/10"
    return None


def _series_key_seed_text(series_key: str, index: int) -> str | None:
    match = re.search(r"-(\d+)v(\d+)$", series_key)
    if not match:
        return None
    left_seed = int(match.group(1))
    right_seed = int(match.group(2))
    target_seed = left_seed if index == 0 else right_seed
    if "round_1" in series_key or series_key.endswith("7v8") or series_key.endswith("9v10"):
        return _seed_ordinal(target_seed)
    return None


def _resolve_slot(slot: dict[str, Any], result_payloads: dict[tuple[str, str], dict[str, Any]]) -> str | None:
    slot_type = slot.get("type")
    if slot_type == "team":
        return slot.get("team")
    if slot_type == "seed":
        return slot.get("team")
    if slot_type == "winner_of":
        return result_payloads.get(("series", slot["series_key"]), {}).get("winner")
    if slot_type == "loser_of":
        result = result_payloads.get(("series", slot["series_key"]), {})
        teams = slot.get("teams", [])
        winner = result.get("winner")
        if not winner or len(teams) != 2:
            return None
        return teams[0] if teams[1] == winner else teams[1]
    if slot_type == "play_in_seed":
        return result_payloads.get(("series", slot["series_key"]), {}).get("winner")
    return None


def _series_display_meta(series: dict[str, Any], result_payloads: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[str], list[str]]:
    slots = series.get("slots") or [{"type": "team", "team": team} for team in series.get("teams", [])]
    teams = [_resolve_slot(slot, result_payloads) for slot in slots]
    labels = [team_name(team) if team else _slot_label(slot) for team, slot in zip(teams, slots, strict=False)]
    return [team for team in teams if team], labels


def _series_display_name(series: dict[str, Any]) -> str:
    if series.get("team_details"):
        return f"{series['team_details'][0]['name']} vs {series['team_details'][1]['name']}"
    teams = series.get("teams", [])
    if len(teams) == 2:
        return f"{team_name(teams[0])} vs {team_name(teams[1])}"
    return series.get("label") or series.get("series_key", "this matchup")


def _generate_monkey_payload(window: BettingWindow) -> dict[str, Any]:
    rng = random.Random(window.monkey_seed or int(window.created_at.timestamp()))
    if window.bet_type == "early":
        config = window.config
        east_finalist = rng.choice(config.get("nba_finalist_options", {}).get("East", ["TBD"]))
        west_finalist = rng.choice(config.get("nba_finalist_options", {}).get("West", ["TBD"]))
        finals_mvp_options = players_for_teams([east_finalist, west_finalist]) or ALL_PLAYER_OPTIONS
        return {
            "conference_finalists": {
                "East": rng.choice(config.get("conference_finalist_options", {}).get("East", ["TBD"])),
                "West": rng.choice(config.get("conference_finalist_options", {}).get("West", ["TBD"])),
            },
            "nba_finalists": {"East": east_finalist, "West": west_finalist},
            "champion": rng.choice([east_finalist, west_finalist]),
            "finals_mvp": rng.choice(finals_mvp_options),
        }

    picks = {}
    for series in window.config.get("series", []):
        teams = [team for team in series.get("teams", []) if team and team != "TBD"]
        if len(teams) != 2:
            continue
        if window.bet_type == "play_in":
            picks[series["series_key"]] = {"winner": rng.choice(teams), "exact_result": "1-0"}
            continue
        exacts = series.get("exact_results", ["4-0", "4-1", "4-2", "4-3"])
        picks[series["series_key"]] = {
            "winner": rng.choice(teams),
            "exact_result": rng.choice(exacts),
        }
    return {"series": picks}


def _ensure_monkey_submission(session: Session, window: BettingWindow) -> None:
    monkey_member = session.scalar(
        select(Membership).join(User, Membership.user_id == User.id).where(Membership.pool_id == window.pool_id, User.is_monkey.is_(True))
    )
    if not monkey_member:
        return
    if any(team == "TBD" for series in window.config.get("series", []) for team in series.get("teams", [])):
        return
    existing = session.scalar(select(PickSubmission).where(PickSubmission.window_id == window.id, PickSubmission.member_id == monkey_member.id))
    payload = _generate_monkey_payload(window)
    if window.bet_type != "early" and not payload.get("series"):
        return
    if existing:
        existing.payload = payload
        existing.submitted_at = utcnow()
    else:
        session.add(PickSubmission(window_id=window.id, member_id=monkey_member.id, payload=payload, submitted_at=utcnow()))
    session.add(EventLog(pool_id=window.pool_id, actor_member_id=monkey_member.id, event_type="monkey_submitted", payload={"window_id": window.id}))


def _materialize_resolved_windows(session: Session, pool_id: str) -> None:
    windows = session.scalars(select(BettingWindow).where(BettingWindow.pool_id == pool_id).order_by(BettingWindow.opens_at)).all()
    results = session.scalars(select(ResultSnapshot).where(ResultSnapshot.pool_id == pool_id).order_by(ResultSnapshot.created_at)).all()
    result_payloads = latest_result_payloads(results)
    for window in windows:
        changed = False
        series_list = []
        for series in window.config.get("series", []):
            updated_series = dict(series)
            resolved_teams, _ = _series_display_meta(series, result_payloads)
            if len(resolved_teams) == 2 and updated_series.get("teams") != resolved_teams:
                updated_series["teams"] = resolved_teams
                changed = True
            series_list.append(updated_series)
        if changed:
            window.config = {**window.config, "series": series_list}
        _ensure_monkey_submission(session, window)


def _latest_early_payload(session: Session, pool_id: str) -> dict[str, Any]:
    results = session.scalars(
        select(ResultSnapshot).where(ResultSnapshot.pool_id == pool_id, ResultSnapshot.scope_type == "early").order_by(ResultSnapshot.created_at)
    ).all()
    payload = {
        "conference_finalists": {"East": "", "West": ""},
        "nba_finalists": {"East": "", "West": ""},
        "champion": "",
        "finals_mvp": "",
    }
    for item in results:
        payload = {
            "conference_finalists": {
                "East": item.payload.get("conference_finalists", {}).get("East", payload["conference_finalists"]["East"]),
                "West": item.payload.get("conference_finalists", {}).get("West", payload["conference_finalists"]["West"]),
            },
            "nba_finalists": {
                "East": item.payload.get("nba_finalists", {}).get("East", payload["nba_finalists"]["East"]),
                "West": item.payload.get("nba_finalists", {}).get("West", payload["nba_finalists"]["West"]),
            },
            "champion": item.payload.get("champion", payload["champion"]),
            "finals_mvp": item.payload.get("finals_mvp", payload["finals_mvp"]),
        }
    return payload


def _latest_leader_message(session: Session, pool_id: str) -> dict[str, Any] | None:
    events = session.scalars(
        select(EventLog)
        .where(EventLog.pool_id == pool_id, EventLog.event_type == "leader_message_updated")
        .order_by(EventLog.created_at)
    ).all()
    if not events:
        return None
    return events[-1].payload


def _finals_mvp_options_from_payload(payload: dict[str, Any]) -> list[str]:
    teams = [payload.get("nba_finalists", {}).get("East"), payload.get("nba_finalists", {}).get("West")]
    options = players_for_teams([team for team in teams if team])
    return options or ALL_PLAYER_OPTIONS


def _build_bracket_sections(windows: list[BettingWindow], results: list[ResultSnapshot]) -> list[dict[str, Any]]:
    result_payloads = latest_result_payloads(results)
    sections: list[dict[str, Any]] = []
    groups = [
        ("East Play-In", "East", "play_in"),
        ("West Play-In", "West", "play_in"),
        ("East First Round", "East", "round_1"),
        ("West First Round", "West", "round_1"),
        ("East Semifinals", "East", "round_2"),
        ("West Semifinals", "West", "round_2"),
        ("Conference Finals", None, "conference_finals"),
        ("NBA Finals", None, "finals"),
    ]
    for title, conference, round_key in groups:
        matchups = []
        for window in windows:
            if window.round_key != round_key:
                continue
            for series in window.config.get("series", []):
                if conference and series.get("conference") != conference:
                    continue
                _, labels = _series_display_meta(series, result_payloads)
                result = result_payloads.get(("series", series["series_key"]), {})
                matchups.append(
                    {
                        "title": series.get("label") or window.name,
                        "teams": labels,
                        "winner": team_name(result.get("winner")) if result.get("winner") else None,
                    }
                )
        if matchups:
            sections.append({"title": title, "matchups": matchups})
    return sections


def _build_bracket_board(windows: list[BettingWindow], results: list[ResultSnapshot]) -> dict[str, Any]:
    result_payloads = latest_result_payloads(results)
    series_lookup: dict[str, dict[str, Any]] = {}
    for window in windows:
        for series in getattr(window, "render_series", []):
            labels = [team["name"] for team in series["team_details"]]
            result_payload = result_payloads.get(("series", series["series_key"]))
            series_lookup[series["series_key"]] = {
                "key": series["series_key"],
                "label": series.get("label") or window.name,
                "round_key": window.round_key,
                "conference": series.get("conference"),
                "teams": labels,
                "team_details": series["team_details"],
                "winner": team_name(result_payload.get("winner")) if result_payload and result_payload.get("winner") else None,
                "result_summary": format_result_summary(series, result_payload),
                "best_of": series.get("best_of", 7),
            }

    def pick(*keys: str) -> list[dict[str, Any]]:
        return [series_lookup[key] for key in keys if key in series_lookup]

    return {
        "west_play_in": pick("play_in-west-9v10", "play_in-west-7v8", "play_in-west-8seed"),
        "east_play_in": pick("play_in-east-7v8", "play_in-east-9v10", "play_in-east-8seed"),
        "west_round_1": pick("round_1-west-1v8", "round_1-west-4v5", "round_1-west-3v6", "round_1-west-2v7"),
        "east_round_1": pick("round_1-east-1v8", "round_1-east-4v5", "round_1-east-3v6", "round_1-east-2v7"),
        "west_round_2": pick("round_2-west-top", "round_2-west-bottom"),
        "east_round_2": pick("round_2-east-top", "round_2-east-bottom"),
        "conference_finals": pick("conference_finals-west", "conference_finals-east"),
        "finals": pick("finals-nba"),
    }


def _series_pick_rows(windows: list[BettingWindow], memberships: list[Membership], users: dict[str, User], submissions: list[PickSubmission]) -> list[dict[str, Any]]:
    submissions_by_key = {(item.window_id, item.member_id): item for item in submissions}
    rows: list[dict[str, Any]] = []
    for window in windows:
        if not window.is_revealed:
            continue
        if window.bet_type == "early":
            picks = []
            for membership in memberships:
                submission = submissions_by_key.get((window.id, membership.id))
                payload = submission.payload if submission else {}
                picks.append(
                    {
                        "member": membership,
                        "user": users[membership.user_id],
                        "pick": {
                            "conference_finalists": payload.get("conference_finalists", {}),
                            "nba_finalists": payload.get("nba_finalists", {}),
                            "champion": payload.get("champion"),
                            "finals_mvp": payload.get("finals_mvp"),
                        },
                    }
                )
            rows.append({"window": window, "type": "early", "picks": picks})
            continue
        for series in getattr(window, "render_series", []):
            picks = []
            for membership in memberships:
                submission = submissions_by_key.get((window.id, membership.id))
                payload = submission.payload if submission else {}
                series_pick = payload.get("series", {}).get(series["series_key"], {}) if payload else {}
                pick_summary = {
                    "winner": team_name(series_pick.get("winner")) if series_pick.get("winner") else "No pick",
                    "exact_result": series_pick.get("exact_result", "-"),
                }
                picks.append({"member": membership, "user": users[membership.user_id], "pick": pick_summary})
            rows.append({"window": window, "series": series, "picks": picks})
    return rows


def current_pick_state(window: BettingWindow, submission: PickSubmission | None) -> dict[str, Any]:
    state: dict[str, Any] = {"bet_type": window.bet_type}
    if not submission:
        return state
    payload = submission.payload
    if window.bet_type == "early":
        state["conference_finalists"] = payload.get("conference_finalists", {})
        state["nba_finalists"] = payload.get("nba_finalists", {})
        state["champion"] = payload.get("champion")
        state["finals_mvp"] = payload.get("finals_mvp")
        return state

    series_state: dict[str, Any] = {}
    for series_key, series_pick in payload.get("series", {}).items():
        exact_result = series_pick.get("exact_result") or "4-1"
        try:
            games_count = 4 + int(str(exact_result).split("-")[1])
        except (IndexError, ValueError):
            games_count = 5
        series_state[series_key] = {
            "winner": series_pick.get("winner"),
            "games_count": games_count,
        }
    state["series"] = series_state
    return state


def summarize_result(result: ResultSnapshot, windows: list[BettingWindow], users: dict[str, User], memberships: list[Membership]) -> dict[str, Any]:
    membership_map = {membership.id: membership for membership in memberships}
    member_names = {
        membership.id: users[membership.user_id].nickname
        for membership in memberships
        if membership.user_id in users
    }
    summary = {
        "title": f"{result.scope_type.title()} result",
        "subtitle": result.scope_key,
        "override": result.is_override,
        "items": [],
    }
    if result.scope_type == "series":
        series_meta = None
        for window in windows:
            for series in window.config.get("series", []):
                if series.get("series_key") == result.scope_key:
                    series_meta = series
                    break
            if series_meta:
                break
        teams = series_meta.get("teams", []) if series_meta else []
        summary["title"] = "Series result"
        summary["subtitle"] = f"{team_name(teams[0])} vs {team_name(teams[1])}" if len(teams) == 2 else result.scope_key
        summary["items"] = [
            f"Winner: {team_name(result.payload.get('winner'))}",
            f"{'Game result' if (series_meta or {}).get('best_of') == 1 else 'Series length'}: {result.payload.get('exact_result', 'TBD')}",
        ]
    elif result.scope_type == "early":
        summary["title"] = "Season results"
        summary["subtitle"] = "Early picks resolution"
        summary["items"] = [
            f"East finalist: {team_name(result.payload.get('nba_finalists', {}).get('East'))}",
            f"West finalist: {team_name(result.payload.get('nba_finalists', {}).get('West'))}",
            f"Champion: {team_name(result.payload.get('champion'))}",
            f"Finals MVP: {result.payload.get('finals_mvp', 'TBD')}",
        ]
    elif result.scope_type == "system":
        summary["title"] = "Provider health"
        summary["subtitle"] = result.payload.get("status", "unknown").title()
        summary["items"] = [result.payload.get("message", "No details available.")]
    return summary


def format_result_summary(series_meta: dict[str, Any] | None, payload: dict[str, Any] | None) -> str:
    if not payload:
        return "Result not posted yet."
    if payload.get("display_score"):
        return str(payload["display_score"])
    winner = team_name(payload.get("winner"))
    if (series_meta or {}).get("best_of") == 1:
        return winner
    exact_result = payload.get("exact_result")
    if exact_result:
        return f"{winner} won {exact_result}"
    return winner


def _build_breakdown_lookup(leaderboard: list[Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    series_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    early_lookup: dict[str, dict[str, Any]] = {}
    for entry in leaderboard:
        for item in entry.breakdown:
            if item.get("type") == "series":
                series_lookup[(entry.member_id, item.get("series_key", ""))] = item
            elif item.get("type") == "early":
                early_lookup[entry.member_id] = item
    return series_lookup, early_lookup


def _build_pick_tables(
    windows: list[BettingWindow],
    memberships: list[Membership],
    users: dict[str, User],
    submissions: list[PickSubmission],
    results: list[ResultSnapshot],
    leaderboard: list[Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    submissions_by_key = {(item.window_id, item.member_id): item for item in submissions}
    result_payloads = latest_result_payloads(results)
    series_breakdown_lookup, early_breakdown_lookup = _build_breakdown_lookup(leaderboard)
    closed_rows: list[dict[str, Any]] = []
    matchup_lookup: dict[str, dict[str, Any]] = {}

    for window in windows:
        if window.bet_type == "early":
            if not window.is_revealed:
                continue
            early_rows = []
            for membership in memberships:
                submission = submissions_by_key.get((window.id, membership.id))
                payload = submission.payload if submission else {}
                breakdown = early_breakdown_lookup.get(membership.id, {})
                early_rows.append(
                    {
                        "member": membership,
                        "user": users[membership.user_id],
                        "conference_finalists_east": team_name(payload.get("conference_finalists", {}).get("East")),
                        "conference_finalists_west": team_name(payload.get("conference_finalists", {}).get("West")),
                        "nba_finalists_east": team_name(payload.get("nba_finalists", {}).get("East")),
                        "nba_finalists_west": team_name(payload.get("nba_finalists", {}).get("West")),
                        "champion": team_name(payload.get("champion")),
                        "finals_mvp": payload.get("finals_mvp") or "No pick",
                        "points": breakdown.get("points", 0),
                    }
                )
            closed_rows.append(
                {
                    "window": window,
                    "type": "early",
                    "result_summary": {
                        "conference_finalists_east": team_name(result_payloads.get(("early", "season"), {}).get("conference_finalists", {}).get("East")),
                        "conference_finalists_west": team_name(result_payloads.get(("early", "season"), {}).get("conference_finalists", {}).get("West")),
                        "nba_finalists_east": team_name(result_payloads.get(("early", "season"), {}).get("nba_finalists", {}).get("East")),
                        "nba_finalists_west": team_name(result_payloads.get(("early", "season"), {}).get("nba_finalists", {}).get("West")),
                        "champion": team_name(result_payloads.get(("early", "season"), {}).get("champion")),
                        "finals_mvp": result_payloads.get(("early", "season"), {}).get("finals_mvp") or "TBD",
                    },
                    "rows": early_rows,
                }
            )
            continue

        for series in getattr(window, "render_series", []):
            result_payload = result_payloads.get(("series", series["series_key"]))
            rows = []
            for membership in memberships:
                submission = submissions_by_key.get((window.id, membership.id))
                payload = submission.payload if submission else {}
                pick = payload.get("series", {}).get(series["series_key"], {}) if payload else {}
                breakdown = series_breakdown_lookup.get((membership.id, series["series_key"]), {})
                rows.append(
                    {
                        "member": membership,
                        "user": users[membership.user_id],
                        "winner_pick": team_name(pick.get("winner")) if pick.get("winner") else "No pick",
                        "exact_result_pick": pick.get("exact_result", "-"),
                        "points": breakdown.get("points", 0),
                        "details": breakdown.get("details", []),
                    }
                )

            row = {
                "window": window,
                "series": series,
                "type": window.bet_type,
                "result_summary": format_result_summary(series, result_payload),
                "result_payload": result_payload,
                "rows": rows,
            }
            matchup_lookup[series["series_key"]] = row
            if window.is_revealed:
                closed_rows.append(row)

    return closed_rows, matchup_lookup


async def parse_submission_payload(request: Request, window: BettingWindow) -> dict[str, Any]:
    form = await request.form()
    payload_json = str(form.get("payload_json") or "").strip()
    if payload_json:
        return json.loads(payload_json)
    if window.bet_type == "early":
        payload = {
            "conference_finalists": {
                "East": str(form.get("conference_finalists_east") or ""),
                "West": str(form.get("conference_finalists_west") or ""),
            },
            "nba_finalists": {
                "East": str(form.get("nba_finalists_east") or ""),
                "West": str(form.get("nba_finalists_west") or ""),
            },
            "champion": str(form.get("champion") or ""),
            "finals_mvp": str(form.get("finals_mvp") or ""),
        }
        missing_fields = [
            label
            for label, value in [
                ("East conference finalist", payload["conference_finalists"]["East"]),
                ("West conference finalist", payload["conference_finalists"]["West"]),
                ("East NBA finalist", payload["nba_finalists"]["East"]),
                ("West NBA finalist", payload["nba_finalists"]["West"]),
                ("Champion", payload["champion"]),
                ("Finals MVP", payload["finals_mvp"]),
            ]
            if not value
        ]
        if missing_fields:
            raise HTTPException(status_code=400, detail=f"Complete every early-pick field before saving. Missing: {', '.join(missing_fields)}.")
        return payload

    payload: dict[str, Any] = {"series": {}}
    for series in window.config.get("series", []):
        series_key = series["series_key"]
        winner = str(form.get(f"winner_{series_key}") or "")
        missing_fields = []
        if not winner:
            missing_fields.append("winner")
        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Complete every field before saving this prediction. Missing for {series_key}: {', '.join(missing_fields)}.",
            )
        if window.bet_type == "play_in":
            payload["series"][series_key] = {
                "winner": winner,
                "exact_result": "1-0",
            }
            continue
        games_count_raw = str(form.get(f"games_count_{series_key}") or "5")
        try:
            games_count = max(4, min(7, int(games_count_raw)))
        except ValueError:
            games_count = 5
        payload["series"][series_key] = {
            "winner": winner,
            "exact_result": f"4-{games_count - 4}",
        }
    return payload


async def parse_bulk_submission_payloads(request: Request, windows: list[BettingWindow]) -> tuple[list[tuple[BettingWindow, dict[str, Any]]], list[str]]:
    form = await request.form()
    submissions_to_save: list[tuple[BettingWindow, dict[str, Any]]] = []
    skipped_labels: list[str] = []

    for window in windows:
        if window.is_locked:
            continue
        if window.bet_type == "early":
            payload = {
                "conference_finalists": {
                    "East": str(form.get("conference_finalists_east") or ""),
                    "West": str(form.get("conference_finalists_west") or ""),
                },
                "nba_finalists": {
                    "East": str(form.get("nba_finalists_east") or ""),
                    "West": str(form.get("nba_finalists_west") or ""),
                },
                "champion": str(form.get("champion") or ""),
                "finals_mvp": str(form.get("finals_mvp") or ""),
            }
            marked = any(
                [
                    payload["conference_finalists"]["East"],
                    payload["conference_finalists"]["West"],
                    payload["nba_finalists"]["East"],
                    payload["nba_finalists"]["West"],
                    payload["champion"],
                    payload["finals_mvp"],
                ]
            )
            if not marked:
                continue
            missing = any(
                not value
                for value in [
                    payload["conference_finalists"]["East"],
                    payload["conference_finalists"]["West"],
                    payload["nba_finalists"]["East"],
                    payload["nba_finalists"]["West"],
                    payload["champion"],
                    payload["finals_mvp"],
                ]
            )
            if missing:
                skipped_labels.append(window.name)
            else:
                submissions_to_save.append((window, payload))
            continue

        payload: dict[str, Any] = {"series": {}}
        window_has_saved_series = False
        for series in getattr(window, "render_series", []):
            if not series["resolved"]:
                continue
            series_key = series["series_key"]
            winner = str(form.get(f"winner_{series_key}") or "").strip()
            games_count_raw = str(form.get(f"games_count_{series_key}") or "").strip()
            marked = bool(winner or games_count_raw)
            if not marked:
                continue
            if not winner:
                skipped_labels.append(_series_display_name(series))
                continue
            if window.bet_type == "play_in":
                payload["series"][series_key] = {"winner": winner, "exact_result": "1-0"}
                window_has_saved_series = True
                continue
            if not games_count_raw:
                skipped_labels.append(_series_display_name(series))
                continue
            try:
                games_count = max(4, min(7, int(games_count_raw)))
            except ValueError:
                skipped_labels.append(_series_display_name(series))
                continue
            payload["series"][series_key] = {"winner": winner, "exact_result": f"4-{games_count - 4}"}
            window_has_saved_series = True
        if window_has_saved_series:
            submissions_to_save.append((window, payload))

    return submissions_to_save, skipped_labels


async def parse_result_payload(request: Request) -> tuple[str, str, dict[str, Any], str, str]:
    form = await request.form()
    source = str(form.get("source") or "manual")
    override_reason = str(form.get("override_reason") or "")
    display_score = str(form.get("display_score") or "").strip()
    payload_json = str(form.get("payload_json") or "").strip()
    if payload_json:
        return (
            str(form.get("scope_type") or "series"),
            str(form.get("scope_key") or ""),
            json.loads(payload_json),
            source,
            override_reason,
        )

    scope_type = str(form.get("scope_type") or "series")
    if scope_type == "early":
        payload = {
            "conference_finalists": {
                "East": str(form.get("result_conference_finalists_east") or ""),
                "West": str(form.get("result_conference_finalists_west") or ""),
            },
            "nba_finalists": {
                "East": str(form.get("result_nba_finalists_east") or ""),
                "West": str(form.get("result_nba_finalists_west") or ""),
            },
            "champion": str(form.get("result_champion") or ""),
            "finals_mvp": str(form.get("result_finals_mvp") or ""),
        }
        missing_fields = [
            label
            for label, value in [
                ("East conference finalist", payload["conference_finalists"]["East"]),
                ("West conference finalist", payload["conference_finalists"]["West"]),
                ("East NBA finalist", payload["nba_finalists"]["East"]),
                ("West NBA finalist", payload["nba_finalists"]["West"]),
                ("Champion", payload["champion"]),
                ("Finals MVP", payload["finals_mvp"]),
            ]
            if not value
        ]
        if missing_fields:
            raise HTTPException(status_code=400, detail=f"Fill every early-result field before saving. Missing: {', '.join(missing_fields)}.")
        return ("early", "season", payload, source, override_reason)

    bet_type = str(form.get("bet_type") or "series")
    result_winner = str(form.get("result_winner") or "")
    missing_fields = []
    if not str(form.get("scope_key") or ""):
        missing_fields.append("series")
    if not result_winner:
        missing_fields.append("winner")
    if missing_fields:
        raise HTTPException(status_code=400, detail=f"Fill every series-result field before saving. Missing: {', '.join(missing_fields)}.")
    if bet_type == "play_in":
        payload = {"winner": result_winner, "exact_result": "1-0"}
        if display_score:
            payload["display_score"] = display_score
        return ("series", str(form.get("scope_key") or ""), payload, source, override_reason)
    games_count_raw = str(form.get("result_games_count") or "5")
    try:
        games_count = max(4, min(7, int(games_count_raw)))
    except ValueError:
        games_count = 5
    payload = {
        "winner": result_winner,
        "exact_result": f"4-{games_count - 4}",
    }
    if display_score:
        payload["display_score"] = display_score
    return ("series", str(form.get("scope_key") or ""), payload, source, override_reason)


async def parse_bulk_result_payloads(request: Request, windows: list[BettingWindow]) -> tuple[list[tuple[str, dict[str, Any], str, str]], list[str]]:
    form = await request.form()
    payloads: list[tuple[str, dict[str, Any], str, str]] = []
    skipped_labels: list[str] = []
    for window in windows:
        if window.bet_type not in {"series", "play_in"}:
            continue
        for series in getattr(window, "render_series", []):
            if not series["resolved"]:
                continue
            series_key = series["series_key"]
            winner = str(form.get(f"result_winner_{series_key}") or "").strip()
            games_count_raw = str(form.get(f"result_games_count_{series_key}") or "").strip()
            display_score = str(form.get(f"display_score_{series_key}") or "").strip()
            source = str(form.get(f"source_{series_key}") or "manual").strip() or "manual"
            override_reason = str(form.get(f"override_reason_{series_key}") or "").strip()
            is_marked = any([winner, games_count_raw, display_score, override_reason, source != "manual"])
            if not is_marked:
                continue
            if not winner:
                skipped_labels.append(_series_display_name(series))
                continue
            payload: dict[str, Any]
            if window.bet_type == "play_in":
                payload = {"winner": winner, "exact_result": "1-0"}
            else:
                if not games_count_raw:
                    skipped_labels.append(_series_display_name(series))
                    continue
                try:
                    games_count = max(4, min(7, int(games_count_raw)))
                except ValueError:
                    skipped_labels.append(_series_display_name(series))
                    continue
                payload = {"winner": winner, "exact_result": f"4-{games_count - 4}"}
            if display_score:
                payload["display_score"] = display_score
            payloads.append((series_key, payload, source, override_reason))
    return payloads, skipped_labels


def _delete_membership(session: Session, membership: Membership) -> None:
    session.query(EventLog).filter(EventLog.actor_member_id == membership.id).update({"actor_member_id": None})
    session.query(ResultSnapshot).filter(ResultSnapshot.created_by_member_id == membership.id).update({"created_by_member_id": None})
    for submission in session.scalars(select(PickSubmission).where(PickSubmission.member_id == membership.id)).all():
        session.delete(submission)
    for entry in session.scalars(select(PaymentLedgerEntry).where(PaymentLedgerEntry.member_id == membership.id)).all():
        session.delete(entry)
    user_id = membership.user_id
    session.delete(membership)
    session.flush()
    remaining_membership = session.scalar(select(Membership).where(Membership.user_id == user_id))
    if not remaining_membership:
        user = session.get(User, user_id)
        if user:
            session.delete(user)


def load_pool_context(session: Session, pool_id: str) -> dict[str, Any]:
    if auto_lock_due_windows(session):
        session.commit()
    pool = session.get(Pool, pool_id)
    memberships = session.scalars(select(Membership).where(Membership.pool_id == pool_id)).all()
    users = {user.id: user for user in session.scalars(select(User).where(User.id.in_([m.user_id for m in memberships]))).all()}
    windows = session.scalars(select(BettingWindow).where(BettingWindow.pool_id == pool_id).order_by(BettingWindow.opens_at)).all()
    submissions = session.scalars(
        select(PickSubmission).where(PickSubmission.window_id.in_([window.id for window in windows] or [""]))
    ).all()
    results = session.scalars(select(ResultSnapshot).where(ResultSnapshot.pool_id == pool_id).order_by(ResultSnapshot.created_at)).all()
    result_payloads = latest_result_payloads(results)
    def window_display_sort_key(window: BettingWindow) -> tuple[int, int, int, datetime, datetime]:
        if window.bet_type == "early":
            return (0, 0, 0, window.opens_at, window.created_at)
        conference = None
        series_list = window.config.get("series", [])
        if series_list:
            conference = series_list[0].get("conference")
        has_result = any(result_payloads.get(("series", series["series_key"])) for series in series_list)
        state_group = 2 if has_result else (0 if not window.is_locked else 1)
        return (1, state_group, _series_priority(window.round_key, conference), window.opens_at, window.created_at)
    windows = sorted(windows, key=window_display_sort_key)
    invite = session.scalar(select(InviteLink).where(InviteLink.pool_id == pool_id, InviteLink.active.is_(True)))
    leaderboard = score_pool(
        members=[
            MemberState(
                member_id=membership.id,
                display_name=users[membership.user_id].nickname,
                payout_eligible=membership.payout_eligible,
                is_monkey=users[membership.user_id].is_monkey,
            )
            for membership in memberships
        ],
        windows=[
            WindowEnvelope(
                window_id=window.id,
                name=window.name,
                round_key=window.round_key,
                bet_type=window.bet_type,
                config=window.config,
                is_locked=window.is_locked,
            )
            for window in windows
        ],
        submissions=[
            SubmissionEnvelope(window_id=item.window_id, member_id=item.member_id, submitted_at=item.submitted_at, payload=item.payload)
            for item in submissions
        ],
        results=[
            ResultEnvelope(
                scope_type=item.scope_type,
                scope_key=item.scope_key,
                created_at=item.created_at,
                payload=item.payload,
                is_override=item.is_override,
            )
            for item in results
        ],
    )
    submissions_by_window_member = {(item.window_id, item.member_id): item for item in submissions}
    for window in windows:
        render_series = []
        for series in window.config.get("series", []):
            resolved_teams, labels = _series_display_meta(series, result_payloads)
            slots = series.get("slots") or [{"type": "team", "team": team} for team in series.get("teams", [])]
            teams = resolved_teams if len(resolved_teams) == 2 else [str(team).upper() for team in series.get("teams", [])]
            if len(teams) < 2:
                teams = teams + ["TBD"] * (2 - len(teams))
            team_details = []
            for index in range(2):
                team = teams[index] if index < len(teams) else "TBD"
                label = labels[index] if index < len(labels) else team_name(team)
                slot = slots[index] if index < len(slots) else {"type": "team", "team": team}
                seed_text = _slot_seed_text(slot) or _series_key_seed_text(str(series.get("series_key") or ""), index)
                team_details.append(
                    {
                        "abbr": team if team != "TBD" else "TBD",
                        "name": label,
                        "logo": team_logo(team if team != "TBD" else None),
                        "seed_text": seed_text,
                    }
                )
            render_series.append(
                {
                    **series,
                    "teams": teams,
                    "resolved": all(team != "TBD" for team in teams),
                    "team_details": team_details,
                }
            )
        window.render_series = render_series
    window_submission_states = {
        window.id: {
            member_id: current_pick_state(window, submissions_by_window_member.get((window.id, member_id)))
            for member_id in [membership.id for membership in memberships]
        }
        for window in windows
    }
    result_cards = [summarize_result(result, windows, users, memberships) for result in results]
    early_window = next((window for window in windows if window.bet_type == "early"), None)
    early_result_state = _latest_early_payload(session, pool_id)
    closed_pick_tables, matchup_lookup = _build_pick_tables(windows, memberships, users, submissions, results, leaderboard)
    closed_pick_tables = sorted(closed_pick_tables, key=_matchup_row_sort_key)
    leader_row = leaderboard[0] if leaderboard else None
    leader_message = _latest_leader_message(session, pool_id)
    return {
        "pool": pool,
        "memberships": memberships,
        "users": users,
        "windows": windows,
        "window_submission_states": window_submission_states,
        "results": results,
        "result_cards": result_cards,
        "early_window": early_window,
        "early_result_state": early_result_state,
        "leaderboard": leaderboard,
        "leaderboard_rows": leaderboard_as_dict(leaderboard),
        "invite": invite,
        "submissions_by_window_member": submissions_by_window_member,
        "team_select_groups": TEAM_SELECT_GROUPS,
        "team_player_lookup": TEAM_PLAYER_LOOKUP,
        "all_player_options": ALL_PLAYER_OPTIONS,
        "default_window_opens_at": local_input_value(offset_days=0, hour=12),
        "default_window_locks_at": local_input_value(offset_days=2, hour=19),
        "window_schedule_inputs": {window.id: {"opens_at": localize_datetime_input(window.opens_at), "locks_at": localize_datetime_input(window.locks_at)} for window in windows},
        "play_in_explanation": PLAY_IN_EXPLANATION,
        "closed_pick_tables": closed_pick_tables,
        "matchup_lookup": matchup_lookup,
        "leader_row": leader_row,
        "leader_message": leader_message,
        "bracket_sections": _build_bracket_sections(windows, results),
        "bracket_board": _build_bracket_board(windows, results),
        "tie_break_rules": [
            "Most exact series results predicted correctly",
            "Correct Finals MVP pick",
            "Earliest submission timestamp",
        ],
        "scoring_rules": {
            "early_picks": [
                "East conference finalist: 2 points",
                "West conference finalist: 2 points",
                "East NBA finalist: 3 points",
                "West NBA finalist: 3 points",
                "NBA champion: 5 points",
                "Finals MVP: 1 point",
            ],
            "series_rounds": [
                "Play-In: winner 1 point",
                "Round 1: winner 1 point, exact result 3 points",
                "Round 2: winner 2 points, exact result 5 points",
                "Conference Finals: winner 3 points, exact result 8 points",
                "NBA Finals: winner 4 points, exact result 10 points",
            ],
            "exact_bonus": [
                "Exactly 1 player gets the exact result: +2 bonus",
                "Exactly 2 players get the exact result: +1 each",
                "3 or more exact winners: no bonus",
            ],
            "tie_break": [
                "Most exact series results predicted correctly",
                "Correct Finals MVP pick",
                "Earliest submission timestamp",
            ],
        },
        "ceiling_explanation": "Ceiling = current points plus the maximum points still available from unresolved boards. Players who missed locked windows or already trail on scored boards can have different ceilings.",
    }


def create_default_early_window(pool_id: str) -> BettingWindow:
    east_teams = [team.code for team in TEAM_SELECT_GROUPS[0][1]]
    west_teams = [team.code for team in TEAM_SELECT_GROUPS[1][1]]
    return BettingWindow(
        pool_id=pool_id,
        name="Early Picks",
        round_key="early",
        bet_type="early",
        opens_at=utcnow(),
        locks_at=utcnow() + timedelta(days=7),
        monkey_seed=random.randint(1, 999999),
        config={
            "conference_finalist_options": {"East": east_teams, "West": west_teams},
            "nba_finalist_options": {"East": east_teams, "West": west_teams},
            "champion_options": east_teams + west_teams,
            "finals_mvp_options": ALL_PLAYER_OPTIONS,
        },
    )


def _create_series_window(
    pool_id: str,
    round_key: str,
    bet_type: str,
    name: str,
    opens_at: datetime,
    locks_at: datetime,
    series_key: str,
    teams: list[str] | None = None,
    conference: str | None = None,
    label: str | None = None,
    slots: list[dict[str, Any]] | None = None,
) -> BettingWindow:
    return BettingWindow(
        pool_id=pool_id,
        name=name,
        round_key=round_key,
        bet_type=bet_type,
        opens_at=opens_at,
        locks_at=locks_at,
        monkey_seed=random.randint(1, 999999),
        config={
            "series": [
                {
                    "series_key": series_key,
                    "round": round_key,
                    "conference": conference,
                    "label": label or name,
                    "slots": slots or [{"type": "team", "team": team} for team in teams or []],
                    "teams": teams or ["TBD", "TBD"],
                    "exact_results": ["1-0"] if bet_type == "play_in" else ["4-0", "4-1", "4-2", "4-3"],
                    "best_of": 1 if bet_type == "play_in" else 7,
                }
            ]
        },
    )


def _validate_seed_list(seed_codes: list[str], conference: str) -> None:
    if len(set(seed_codes)) != len(seed_codes):
        raise HTTPException(status_code=400, detail=f"{conference} seeds must be unique.")
    for code in seed_codes:
        team = TEAM_BY_CODE.get(code)
        if not team or team.conference != conference:
            raise HTTPException(status_code=400, detail=f"{code} is not a valid {conference} team.")


def _generate_bracket_windows(pool_id: str, east_seeds: list[str], west_seeds: list[str], opens_at: datetime, locks_at: datetime) -> list[BettingWindow]:
    windows: list[BettingWindow] = []
    conference_seeds = {"East": east_seeds, "West": west_seeds}
    for conference, seeds in conference_seeds.items():
        slug = conference.lower()
        play_in_open = opens_at
        round_one_open = opens_at + timedelta(days=4)
        round_two_open = opens_at + timedelta(days=18)
        conference_finals_open = opens_at + timedelta(days=32)
        windows.extend(
            [
                _create_series_window(
                    pool_id,
                    "play_in",
                    "play_in",
                    f"{conference} Play-In: {team_name(seeds[6])} vs {team_name(seeds[7])}",
                    play_in_open,
                    locks_at,
                    f"play_in-{slug}-7v8",
                    teams=[seeds[6], seeds[7]],
                    conference=conference,
                    label=f"{conference} 7 vs 8",
                    slots=[
                        {"type": "seed", "conference": conference, "seed": 7, "team": seeds[6]},
                        {"type": "seed", "conference": conference, "seed": 8, "team": seeds[7]},
                    ],
                ),
                _create_series_window(
                    pool_id,
                    "play_in",
                    "play_in",
                    f"{conference} Play-In: {team_name(seeds[8])} vs {team_name(seeds[9])}",
                    play_in_open,
                    locks_at,
                    f"play_in-{slug}-9v10",
                    teams=[seeds[8], seeds[9]],
                    conference=conference,
                    label=f"{conference} 9 vs 10",
                    slots=[
                        {"type": "seed", "conference": conference, "seed": 9, "team": seeds[8]},
                        {"type": "seed", "conference": conference, "seed": 10, "team": seeds[9]},
                    ],
                ),
                _create_series_window(
                    pool_id,
                    "play_in",
                    "play_in",
                    f"{conference} Play-In: No. 8 seed decider",
                    play_in_open + timedelta(days=2),
                    locks_at + timedelta(days=2),
                    f"play_in-{slug}-8seed",
                    teams=["TBD", "TBD"],
                    conference=conference,
                    label=f"{conference} No. 8 seed decider",
                    slots=[
                        {"type": "loser_of", "series_key": f"play_in-{slug}-7v8", "teams": [seeds[6], seeds[7]]},
                        {"type": "winner_of", "series_key": f"play_in-{slug}-9v10"},
                    ],
                ),
            ]
        )
        windows.extend(
            [
                _create_series_window(pool_id, "round_1", "series", f"{conference} Round 1: {team_name(seeds[0])} vs {conference} #8", round_one_open, round_one_open + timedelta(days=1), f"round_1-{slug}-1v8", teams=[seeds[0], "TBD"], conference=conference, label=f"{conference} 1 vs 8", slots=[{"type": "seed", "conference": conference, "seed": 1, "team": seeds[0]}, {"type": "play_in_seed", "conference": conference, "seed": 8, "series_key": f"play_in-{slug}-8seed"}]),
                _create_series_window(pool_id, "round_1", "series", f"{conference} Round 1: {team_name(seeds[1])} vs {conference} #7", round_one_open, round_one_open + timedelta(days=1), f"round_1-{slug}-2v7", teams=[seeds[1], "TBD"], conference=conference, label=f"{conference} 2 vs 7", slots=[{"type": "seed", "conference": conference, "seed": 2, "team": seeds[1]}, {"type": "play_in_seed", "conference": conference, "seed": 7, "series_key": f"play_in-{slug}-7v8"}]),
                _create_series_window(pool_id, "round_1", "series", generated_window_name("round_1", seeds[2], seeds[5]), round_one_open, round_one_open + timedelta(days=1), f"round_1-{slug}-3v6", teams=[seeds[2], seeds[5]], conference=conference, label=f"{conference} 3 vs 6", slots=[{"type": "seed", "conference": conference, "seed": 3, "team": seeds[2]}, {"type": "seed", "conference": conference, "seed": 6, "team": seeds[5]}]),
                _create_series_window(pool_id, "round_1", "series", generated_window_name("round_1", seeds[3], seeds[4]), round_one_open, round_one_open + timedelta(days=1), f"round_1-{slug}-4v5", teams=[seeds[3], seeds[4]], conference=conference, label=f"{conference} 4 vs 5", slots=[{"type": "seed", "conference": conference, "seed": 4, "team": seeds[3]}, {"type": "seed", "conference": conference, "seed": 5, "team": seeds[4]}]),
            ]
        )
        windows.extend(
            [
                _create_series_window(pool_id, "round_2", "series", f"{conference} Semifinal: Winner 1/8 vs Winner 4/5", round_two_open, round_two_open + timedelta(days=1), f"round_2-{slug}-top", teams=["TBD", "TBD"], conference=conference, label=f"{conference} Semifinal 1", slots=[{"type": "winner_of", "series_key": f"round_1-{slug}-1v8"}, {"type": "winner_of", "series_key": f"round_1-{slug}-4v5"}]),
                _create_series_window(pool_id, "round_2", "series", f"{conference} Semifinal: Winner 2/7 vs Winner 3/6", round_two_open, round_two_open + timedelta(days=1), f"round_2-{slug}-bottom", teams=["TBD", "TBD"], conference=conference, label=f"{conference} Semifinal 2", slots=[{"type": "winner_of", "series_key": f"round_1-{slug}-2v7"}, {"type": "winner_of", "series_key": f"round_1-{slug}-3v6"}]),
                _create_series_window(
                    pool_id,
                    "conference_finals",
                    "series",
                    f"{conference} Conference Finals",
                    conference_finals_open,
                    conference_finals_open + timedelta(days=1),
                    f"conference_finals-{slug}",
                    teams=["TBD", "TBD"],
                    conference=conference,
                    label=f"{conference} Conference Finals",
                    slots=[
                        {"type": "winner_of", "series_key": f"round_2-{slug}-top"},
                        {"type": "winner_of", "series_key": f"round_2-{slug}-bottom"},
                    ],
                ),
            ]
        )
    finals_open = opens_at + timedelta(days=46)
    windows.append(
        _create_series_window(
            pool_id,
            "finals",
            "series",
            "NBA Finals",
            finals_open,
            finals_open + timedelta(days=1),
            "finals-nba",
            teams=["TBD", "TBD"],
            conference=None,
            label="NBA Finals",
            slots=[
                {"type": "winner_of", "series_key": "conference_finals-east"},
                {"type": "winner_of", "series_key": "conference_finals-west"},
            ],
        )
    )
    return windows


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    pools = session.scalars(select(Pool).order_by(Pool.created_at.desc())).all()
    return templates.TemplateResponse(request, "index.html", {"pools": pools})


@app.post("/pools")
def create_pool(
    request: Request,
    name: str = Form(...),
    season_label: str = Form("2025-26 / 2026 Playoffs"),
    commissioner_nickname: str = Form(...),
    commissioner_email: str = Form(""),
    avatar: str = Form("🏀"),
    session: Session = Depends(get_session),
) -> Response:
    pool = Pool(name=name, season_label=season_label)
    session.add(pool)
    session.flush()

    commissioner = User(email=commissioner_email or None, nickname=commissioner_nickname, avatar=avatar, is_monkey=False)
    monkey = User(email=None, nickname="The Monkey", avatar="🐒", is_monkey=True)
    session.add_all([commissioner, monkey])
    session.flush()

    commissioner_membership = Membership(pool_id=pool.id, user_id=commissioner.id, role="commissioner", payout_eligible=True, payment_status="paid")
    monkey_membership = Membership(pool_id=pool.id, user_id=monkey.id, role="player", payout_eligible=True, payment_status="n/a")
    session.add_all([commissioner_membership, monkey_membership])
    session.flush()

    invite = InviteLink(pool_id=pool.id, token=secrets.token_urlsafe(16), active=True)
    session.add(invite)
    early_window = create_default_early_window(pool.id)
    session.add(early_window)
    session.flush()
    _ensure_monkey_submission(session, early_window)
    session.add(PaymentLedgerEntry(pool_id=pool.id, member_id=commissioner_membership.id, status="paid", amount=0, note="Commissioner created pool"))
    session.add(EventLog(pool_id=pool.id, actor_member_id=commissioner_membership.id, event_type="pool_created", payload={"name": name}))
    session.commit()

    response = RedirectResponse(url=redirect_with_tab(pool.id), status_code=303)
    response.set_cookie(settings.session_cookie_name, encode_session(commissioner_membership.id), httponly=True, samesite="lax")
    return response


@app.get("/invite/{token}", response_class=HTMLResponse)
def invite_page(token: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    invite = session.scalar(select(InviteLink).where(InviteLink.token == token, InviteLink.active.is_(True)))
    if not invite:
        raise HTTPException(status_code=404, detail="Invite link not found.")
    pool = session.get(Pool, invite.pool_id)
    return templates.TemplateResponse(request, "invite.html", {"invite": invite, "pool": pool})


@app.post("/invite/{token}")
def join_pool(
    token: str,
    nickname: str = Form(...),
    email: str = Form(""),
    avatar: str = Form("🔥"),
    session: Session = Depends(get_session),
) -> Response:
    invite = session.scalar(select(InviteLink).where(InviteLink.token == token, InviteLink.active.is_(True)))
    if not invite:
        raise HTTPException(status_code=404, detail="Invite link not found.")
    user = User(email=email or None, nickname=nickname, avatar=avatar)
    session.add(user)
    session.flush()
    membership = Membership(pool_id=invite.pool_id, user_id=user.id, role="player", payout_eligible=True)
    session.add(membership)
    session.add(EventLog(pool_id=invite.pool_id, actor_member_id=membership.id, event_type="player_joined", payload={"nickname": nickname}))
    session.commit()
    response = RedirectResponse(url=f"/pools/{invite.pool_id}", status_code=303)
    response.set_cookie(settings.session_cookie_name, encode_session(membership.id), httponly=True, samesite="lax")
    return response


@app.get("/pools/{pool_id}", response_class=HTMLResponse)
def pool_detail(pool_id: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    context = load_pool_context(session, pool_id)
    membership = current_membership(request, session)
    context["current_membership"] = membership if membership and membership.pool_id == pool_id else None
    context["leader_can_post"] = bool(context["current_membership"] and context["leader_row"] and context["current_membership"].id == context["leader_row"].member_id)
    active_tab = request.query_params.get("tab", "overview")
    context["active_tab"] = active_tab if active_tab in VALID_POOL_TABS else "overview"
    context["resume_status"] = request.query_params.get("resume_status")
    context["resume_message"] = request.query_params.get("resume_message")
    context["flash_status"] = request.query_params.get("flash_status")
    context["flash_message"] = request.query_params.get("flash_message")
    return templates.TemplateResponse(request, "pool.html", context)


@app.get("/pools/{pool_id}/players/{member_id}", response_class=HTMLResponse)
def player_detail(pool_id: str, member_id: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    context = load_pool_context(session, pool_id)
    membership = current_membership(request, session)
    context["current_membership"] = membership if membership and membership.pool_id == pool_id else None
    target_membership = next((item for item in context["memberships"] if item.id == member_id), None)
    if not target_membership:
        raise HTTPException(status_code=404, detail="Player not found.")
    target_user = context["users"][target_membership.user_id]
    leaderboard_row = next((row for row in context["leaderboard"] if row.member_id == member_id), None)
    visible_picks = []
    missing_picks = []
    for window in context["windows"]:
        submission = context["submissions_by_window_member"].get((window.id, member_id))
        if window.bet_type == "early":
            if not submission and not window.is_locked:
                missing_picks.append({"window": window, "label": window.name, "type": "early"})
            if not window.is_revealed:
                continue
            if submission:
                visible_picks.append({"window": window, "type": "early", "payload": submission.payload})
            continue
        unresolved_series = [series for series in getattr(window, "render_series", []) if not series["resolved"]]
        if not submission and not window.is_locked:
            for series in getattr(window, "render_series", []):
                if series["resolved"]:
                    missing_picks.append({"window": window, "label": f"{series['team_details'][0]['name']} vs {series['team_details'][1]['name']}", "type": window.bet_type})
        elif submission and not window.is_locked:
            series_payload = submission.payload.get("series", {})
            for series in getattr(window, "render_series", []):
                if series["resolved"] and not series_payload.get(series["series_key"]):
                    missing_picks.append({"window": window, "label": f"{series['team_details'][0]['name']} vs {series['team_details'][1]['name']}", "type": window.bet_type})
        if not window.is_revealed:
            continue
        for series in getattr(window, "render_series", []):
            pick = submission.payload.get("series", {}).get(series["series_key"], {}) if submission else {}
            visible_picks.append({"window": window, "type": window.bet_type, "series": series, "payload": pick})
    return templates.TemplateResponse(
        request,
        "player.html",
        {
            **context,
            "selected_membership": target_membership,
            "selected_user": target_user,
            "selected_leaderboard_row": leaderboard_row,
            "visible_picks": visible_picks,
            "missing_picks": missing_picks,
        },
    )


@app.get("/pools/{pool_id}/matchups/{series_key}", response_class=HTMLResponse)
def matchup_detail(pool_id: str, series_key: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    context = load_pool_context(session, pool_id)
    membership = current_membership(request, session)
    context["current_membership"] = membership if membership and membership.pool_id == pool_id else None
    matchup = context["matchup_lookup"].get(series_key)
    if not matchup:
        raise HTTPException(status_code=404, detail="Matchup not found.")
    if not matchup["window"].is_revealed:
        raise HTTPException(status_code=403, detail="This board is still hidden until the window is revealed.")
    return templates.TemplateResponse(
        request,
        "matchup.html",
        {
            **context,
            "matchup": matchup,
        },
    )


@app.post("/pools/{pool_id}/leader-message")
async def save_leader_message(pool_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    membership = require_membership(request, session, pool_id)
    context = load_pool_context(session, pool_id)
    leader_row = context["leader_row"]
    if not leader_row or leader_row.member_id != membership.id:
        raise HTTPException(status_code=403, detail="Only the current first-place player can post the highlighted message.")
    form = await request.form()
    message = str(form.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Write a message before saving.")
    if len(message) > 280:
        raise HTTPException(status_code=400, detail="Highlighted messages must be 280 characters or fewer.")
    user = session.get(User, membership.user_id)
    session.add(
        EventLog(
            pool_id=pool_id,
            actor_member_id=membership.id,
            event_type="leader_message_updated",
            payload={
                "message": message,
                "member_id": membership.id,
                "display_name": user.nickname if user else "Leader",
            },
        )
    )
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, "overview"), status_code=303)


@app.post("/pools/{pool_id}/resume")
def resume_pool_access(
    pool_id: str,
    nickname: str = Form(...),
    email: str = Form(""),
    session: Session = Depends(get_session),
) -> Response:
    pool = session.get(Pool, pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found.")

    normalized_nickname = nickname.strip().lower()
    normalized_email = email.strip().lower()
    memberships = session.scalars(select(Membership).where(Membership.pool_id == pool_id)).all()
    candidates: list[tuple[Membership, User]] = []
    for membership in memberships:
        user = session.get(User, membership.user_id)
        if not user or user.nickname.strip().lower() != normalized_nickname:
            continue
        if user.email:
            if normalized_email and user.email.lower() == normalized_email:
                candidates.append((membership, user))
            elif not normalized_email:
                continue
        else:
            candidates.append((membership, user))

    if not candidates:
        message = "We could not match that member. Use the same nickname, and add the same email if one was used before."
        return RedirectResponse(url=f"{redirect_with_tab(pool_id)}&resume_status=error&resume_message={quote_plus(message)}", status_code=303)

    if len(candidates) > 1:
        message = "Multiple members match that nickname. Add the original email to resume the correct account."
        return RedirectResponse(url=f"{redirect_with_tab(pool_id)}&resume_status=error&resume_message={quote_plus(message)}", status_code=303)

    membership, user = candidates[0]
    message = f"Welcome back, {user.nickname}. Your access has been restored."
    response = RedirectResponse(url=f"{redirect_with_tab(pool_id)}&resume_status=success&resume_message={quote_plus(message)}", status_code=303)
    response.set_cookie(settings.session_cookie_name, encode_session(membership.id), httponly=True, samesite="lax")
    return response


@app.post("/pools/{pool_id}/signout")
def sign_out(pool_id: str) -> Response:
    response = RedirectResponse(url=redirect_with_tab(pool_id), status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


@app.post("/pools/{pool_id}/windows")
def create_window(
    pool_id: str,
    request: Request,
    name: str = Form(""),
    round_key: str = Form(...),
    bet_type: str = Form(...),
    opens_at: str = Form(...),
    locks_at: str = Form(...),
    series_key: str = Form(""),
    team_one: str = Form(""),
    team_two: str = Form(""),
    next_tab: str = Form("commissioner"),
    session: Session = Depends(get_session),
) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    config: dict[str, Any]
    if bet_type == "early":
        round_key = "early"
        name = name.strip() or "Early Picks"
        config = create_default_early_window(pool_id).config
    else:
        team_one = team_one.upper()
        team_two = team_two.upper()
        if team_one not in TEAM_BY_CODE or team_two not in TEAM_BY_CODE:
            raise HTTPException(status_code=400, detail="Choose both teams from the NBA list.")
        if team_one == team_two:
            raise HTTPException(status_code=400, detail="A series needs two different teams.")
        name = name.strip() or generated_window_name(round_key, team_one, team_two)
        series_key = series_key or f"{round_key}-{team_one}-{team_two}"
        config = {
            "series": [
                {
                    "series_key": series_key,
                    "round": round_key,
                    "conference": TEAM_BY_CODE[team_one].conference if TEAM_BY_CODE[team_one].conference == TEAM_BY_CODE[team_two].conference else None,
                    "teams": [team_one, team_two],
                    "exact_results": ["1-0"] if round_key == "play_in" or bet_type == "play_in" else ["4-0", "4-1", "4-2", "4-3"],
                    "best_of": 1 if round_key == "play_in" or bet_type == "play_in" else 7,
                }
            ]
        }
        if round_key == "play_in":
            bet_type = "play_in"
    window = BettingWindow(
        pool_id=pool_id,
        name=name,
        round_key=round_key,
        bet_type=bet_type,
        opens_at=parse_iso_datetime(opens_at),
        locks_at=parse_iso_datetime(locks_at),
        config=config,
        monkey_seed=random.randint(1, 999999),
    )
    session.add(window)
    session.flush()
    _ensure_monkey_submission(session, window)
    session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="window_created", payload={"window_name": name}))
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, next_tab), status_code=303)


@app.post("/pools/{pool_id}/windows/{window_id}/submit")
async def submit_picks(
    pool_id: str,
    window_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    membership = require_membership(request, session, pool_id)
    if auto_lock_due_windows(session):
        session.commit()
    window = session.get(BettingWindow, window_id)
    if not window or window.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Window not found.")
    if window.is_locked:
        return RedirectResponse(
            url=redirect_with_message(pool_id, "overview", "error", "The bet is closed, you can bag to Gil"),
            status_code=303,
        )
    try:
        payload = await parse_submission_payload(request, window)
    except HTTPException as exc:
        return RedirectResponse(url=redirect_with_message(pool_id, "overview", "error", str(exc.detail)), status_code=303)
    existing = session.scalar(select(PickSubmission).where(PickSubmission.window_id == window_id, PickSubmission.member_id == membership.id))
    if existing:
        existing.payload = payload
        existing.submitted_at = utcnow()
    else:
        session.add(PickSubmission(window_id=window_id, member_id=membership.id, payload=payload))
    session.add(EventLog(pool_id=pool_id, actor_member_id=membership.id, event_type="picks_submitted", payload={"window_id": window_id}))
    session.commit()
    return RedirectResponse(url=redirect_with_message(pool_id, "overview", "success", "Your picks were saved."), status_code=303)


@app.post("/pools/{pool_id}/submit-all")
async def submit_all_picks(
    pool_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    membership = require_membership(request, session, pool_id)
    if auto_lock_due_windows(session):
        session.commit()
    windows = load_pool_context(session, pool_id)["windows"]
    try:
        submissions_to_save, skipped_labels = await parse_bulk_submission_payloads(request, windows)
    except HTTPException as exc:
        return RedirectResponse(url=redirect_with_message(pool_id, "overview", "error", str(exc.detail)), status_code=303)
    if not submissions_to_save:
        if skipped_labels:
            return RedirectResponse(
                url=redirect_with_message(pool_id, "overview", "error", f"No complete picks were saved. Finish {skipped_labels[0]} first."),
                status_code=303,
            )
        return RedirectResponse(url=redirect_with_message(pool_id, "overview", "error", "Mark at least one pick before saving."), status_code=303)

    saved_count = 0
    for window, payload in submissions_to_save:
        existing = session.scalar(select(PickSubmission).where(PickSubmission.window_id == window.id, PickSubmission.member_id == membership.id))
        if existing:
            existing.payload = payload
            existing.submitted_at = utcnow()
        else:
            session.add(PickSubmission(window_id=window.id, member_id=membership.id, payload=payload))
        session.add(EventLog(pool_id=pool_id, actor_member_id=membership.id, event_type="picks_submitted", payload={"window_id": window.id, "bulk": True}))
        saved_count += 1
    session.commit()
    message = f"Saved {saved_count} marked pick board(s)."
    if skipped_labels:
        message += f" Skipped {len(skipped_labels)} incomplete board(s)."
    return RedirectResponse(
        url=redirect_with_message(pool_id, "overview", "success", message),
        status_code=303,
    )


@app.post("/pools/{pool_id}/windows/{window_id}/lock")
def lock_window(pool_id: str, window_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    window = session.get(BettingWindow, window_id)
    window.is_locked = True
    window.is_revealed = True
    window.revealed_at = utcnow()
    session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="window_locked", payload={"window_id": window_id}))
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, "commissioner"), status_code=303)


@app.post("/pools/{pool_id}/windows/{window_id}/schedule")
def update_window_schedule(
    pool_id: str,
    window_id: str,
    request: Request,
    opens_at: str = Form(...),
    locks_at: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    window = session.get(BettingWindow, window_id)
    if not window or window.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Window not found.")

    parsed_opens_at = parse_iso_datetime(opens_at)
    parsed_locks_at = parse_iso_datetime(locks_at)
    if parsed_locks_at <= parsed_opens_at:
        return RedirectResponse(
            url=redirect_with_message(pool_id, "commissioner", "error", "Lock time must be after the open time."),
            status_code=303,
        )

    window.opens_at = parsed_opens_at
    window.locks_at = parsed_locks_at
    if parsed_locks_at <= utcnow():
        window.is_locked = True
        window.is_revealed = True
        window.revealed_at = utcnow()
    else:
        if window.is_locked:
            window.is_locked = False
            window.is_revealed = False
            window.revealed_at = None
    session.add(
        EventLog(
            pool_id=pool_id,
            actor_member_id=commissioner.id,
            event_type="window_schedule_updated",
            payload={"window_id": window_id, "opens_at": parsed_opens_at.isoformat(), "locks_at": parsed_locks_at.isoformat()},
        )
    )
    session.commit()
    return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "success", f"Updated schedule for {window.name}."), status_code=303)


@app.post("/pools/{pool_id}/windows/{window_id}/unlock")
def unlock_window(pool_id: str, window_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    window = session.get(BettingWindow, window_id)
    window.is_locked = False
    window.is_revealed = False
    window.revealed_at = None
    session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="window_reopened", payload={"window_id": window_id}))
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, "commissioner"), status_code=303)


@app.post("/pools/{pool_id}/windows/{window_id}/delete")
def delete_window(pool_id: str, window_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    window = session.get(BettingWindow, window_id)
    if not window or window.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Window not found.")

    for submission in session.scalars(select(PickSubmission).where(PickSubmission.window_id == window.id)).all():
        session.delete(submission)

    result_keys = [series["series_key"] for series in window.config.get("series", [])]
    if window.bet_type == "early":
        result_keys = ["season"]
    if result_keys:
        result_scope = "early" if window.bet_type == "early" else "series"
        for result in session.scalars(
            select(ResultSnapshot).where(ResultSnapshot.pool_id == pool_id, ResultSnapshot.scope_type == result_scope, ResultSnapshot.scope_key.in_(result_keys))
        ).all():
            session.delete(result)

    session.delete(window)
    session.add(
        EventLog(
            pool_id=pool_id,
            actor_member_id=commissioner.id,
            event_type="window_deleted",
            payload={"window_id": window_id, "window_name": window.name},
        )
    )
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, "commissioner"), status_code=303)


@app.post("/pools/{pool_id}/members/{member_id}/rename")
def rename_member(
    pool_id: str,
    member_id: str,
    request: Request,
    nickname: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    membership = session.get(Membership, member_id)
    if not membership or membership.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Player not found.")
    user = session.get(User, membership.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found.")
    new_name = nickname.strip()
    if not new_name:
        return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "error", "Player name cannot be empty."), status_code=303)
    user.nickname = new_name
    session.add(
        EventLog(
            pool_id=pool_id,
            actor_member_id=commissioner.id,
            event_type="member_renamed",
            payload={"member_id": member_id, "nickname": new_name},
        )
    )
    session.commit()
    return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "success", f"Updated {new_name}."), status_code=303)


@app.post("/pools/{pool_id}/members/{member_id}/delete")
def delete_member(pool_id: str, member_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    membership = session.get(Membership, member_id)
    if not membership or membership.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Player not found.")
    user = session.get(User, membership.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found.")
    if user.is_monkey:
        return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "error", "The Monkey cannot be removed."), status_code=303)
    if membership.role == "commissioner":
        return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "error", "Delete the entire pool instead of deleting the commissioner."), status_code=303)
    nickname = user.nickname
    _delete_membership(session, membership)
    session.add(
        EventLog(
            pool_id=pool_id,
            actor_member_id=commissioner.id,
            event_type="member_deleted",
            payload={"nickname": nickname},
        )
    )
    session.commit()
    return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "success", f"Removed {nickname} from the tournament."), status_code=303)


@app.post("/pools/{pool_id}/delete")
def delete_pool(pool_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    pool = session.get(Pool, pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found.")
    memberships = session.scalars(select(Membership).where(Membership.pool_id == pool_id)).all()
    session.query(EventLog).filter(EventLog.pool_id == pool_id).delete()
    session.query(ResultSnapshot).filter(ResultSnapshot.pool_id == pool_id).delete()
    session.query(PickSubmission).filter(PickSubmission.window_id.in_(select(BettingWindow.id).where(BettingWindow.pool_id == pool_id))).delete(
        synchronize_session=False
    )
    session.query(PaymentLedgerEntry).filter(PaymentLedgerEntry.pool_id == pool_id).delete()
    session.query(InviteLink).filter(InviteLink.pool_id == pool_id).delete()
    session.query(BettingWindow).filter(BettingWindow.pool_id == pool_id).delete()
    for membership in memberships:
        session.delete(membership)
    session.flush()
    user_ids = [membership.user_id for membership in memberships]
    for user_id in user_ids:
        if not session.scalar(select(Membership).where(Membership.user_id == user_id)):
            user = session.get(User, user_id)
            if user:
                session.delete(user)
    session.delete(pool)
    session.commit()
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


@app.post("/pools/{pool_id}/results")
async def post_result(
    pool_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    form = await request.form()
    if form.get("scope_key"):
        try:
            scope_type, scope_key, payload, source, override_reason = await parse_result_payload(request)
        except HTTPException as exc:
            return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "error", str(exc.detail)), status_code=303)
        session.add(
            ResultSnapshot(
                pool_id=pool_id,
                scope_type=scope_type,
                scope_key=scope_key,
                payload=payload,
                source=source,
                is_override=bool(override_reason),
                override_reason=override_reason or None,
                created_by_member_id=commissioner.id,
            )
        )
        session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="result_posted", payload={"scope_type": scope_type, "scope_key": scope_key}))
        session.flush()
        _materialize_resolved_windows(session, pool_id)
        session.commit()
        return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "success", "Saved 1 marked result."), status_code=303)
    context = load_pool_context(session, pool_id)
    try:
        result_payloads, skipped_labels = await parse_bulk_result_payloads(request, context["windows"])
    except HTTPException as exc:
        return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "error", str(exc.detail)), status_code=303)
    if not result_payloads:
        if skipped_labels:
            return RedirectResponse(
                url=redirect_with_message(pool_id, "commissioner", "error", f"No complete results were saved. Finish {skipped_labels[0]} first."),
                status_code=303,
            )
        return RedirectResponse(url=redirect_with_message(pool_id, "commissioner", "error", "Mark at least one result before saving."), status_code=303)
    for scope_key, payload, source, override_reason in result_payloads:
        session.add(
            ResultSnapshot(
                pool_id=pool_id,
                scope_type="series",
                scope_key=scope_key,
                payload=payload,
                source=source,
                is_override=bool(override_reason),
                override_reason=override_reason or None,
                created_by_member_id=commissioner.id,
            )
        )
        session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="result_posted", payload={"scope_type": "series", "scope_key": scope_key}))
    session.flush()
    _materialize_resolved_windows(session, pool_id)
    session.commit()
    message = f"Saved {len(result_payloads)} marked result(s)."
    if skipped_labels:
        message += f" Skipped {len(skipped_labels)} incomplete board(s)."
    return RedirectResponse(
        url=redirect_with_message(pool_id, "commissioner", "success", message),
        status_code=303,
    )


@app.post("/pools/{pool_id}/results/early-field")
def save_early_result_field(
    pool_id: str,
    request: Request,
    field_name: str = Form(...),
    field_value: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    payload = _latest_early_payload(session, pool_id)
    field_map = {
        "conference_finalists_east": ("conference_finalists", "East"),
        "conference_finalists_west": ("conference_finalists", "West"),
        "nba_finalists_east": ("nba_finalists", "East"),
        "nba_finalists_west": ("nba_finalists", "West"),
    }
    if field_name in field_map:
        parent, child = field_map[field_name]
        payload[parent][child] = field_value
    elif field_name == "champion":
        payload["champion"] = field_value
    elif field_name == "finals_mvp":
        payload["finals_mvp"] = field_value
    else:
        raise HTTPException(status_code=400, detail="Unknown early-result field.")
    session.add(
        ResultSnapshot(
            pool_id=pool_id,
            scope_type="early",
            scope_key="season",
            payload=payload,
            source="manual",
            is_override=False,
            override_reason=None,
            created_by_member_id=commissioner.id,
        )
    )
    session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="early_result_updated", payload={"field_name": field_name}))
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, "commissioner"), status_code=303)


@app.post("/pools/{pool_id}/generate-bracket")
async def generate_bracket(
    pool_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    commissioner = require_commissioner(request, session, pool_id)
    form = await request.form()
    east_seeds = [str(form.get(f"east_seed_{index}") or "").upper() for index in range(1, 11)]
    west_seeds = [str(form.get(f"west_seed_{index}") or "").upper() for index in range(1, 11)]
    _validate_seed_list(east_seeds, "East")
    _validate_seed_list(west_seeds, "West")
    opens_at = parse_iso_datetime(str(form.get("opens_at") or local_input_value(offset_days=0, hour=12)))
    locks_at = parse_iso_datetime(str(form.get("locks_at") or local_input_value(offset_days=2, hour=19)))
    for window in _generate_bracket_windows(pool_id, east_seeds, west_seeds, opens_at, locks_at):
        session.add(window)
        session.flush()
        _ensure_monkey_submission(session, window)
    session.add(EventLog(pool_id=pool_id, actor_member_id=commissioner.id, event_type="bracket_generated", payload={"east": east_seeds, "west": west_seeds}))
    session.commit()
    return RedirectResponse(url=redirect_with_tab(pool_id, "bracket"), status_code=303)


@app.get("/pools/{pool_id}/export")
def export_pool(pool_id: str, request: Request, session: Session = Depends(get_session)) -> Response:
    require_commissioner(request, session, pool_id)
    filename, payload = export_bundle(session, pool_id)
    return Response(payload, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/recover")
def recover_pool(snapshot: UploadFile = File(...), session: Session = Depends(get_session)) -> Response:
    pool, commissioner_membership_id = restore_from_snapshot_json(session, snapshot.file.read())
    response = RedirectResponse(url=f"/pools/{pool.id}", status_code=303)
    response.set_cookie(settings.session_cookie_name, encode_session(commissioner_membership_id), httponly=True, samesite="lax")
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.db import SessionLocal
from app.models import BettingWindow, EventLog, Membership, PickSubmission, ResultSnapshot, SideBet, SideBetSubmission, User
from app.services.provider import provider_healthcheck


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _generate_monkey_payload(window: BettingWindow) -> dict:
    rng = random.Random(window.monkey_seed or int(window.created_at.timestamp()))
    if window.bet_type == "early":
        config = window.config
        east_finalist = rng.choice(config.get("nba_finalist_options", {}).get("East", ["TBD"]))
        west_finalist = rng.choice(config.get("nba_finalist_options", {}).get("West", ["TBD"]))
        return {
            "conference_finalists": {
                "East": rng.choice(config.get("conference_finalist_options", {}).get("East", ["TBD"])),
                "West": rng.choice(config.get("conference_finalist_options", {}).get("West", ["TBD"])),
            },
            "nba_finalists": {
                "East": east_finalist,
                "West": west_finalist,
            },
            "champion": rng.choice([east_finalist, west_finalist]),
            "finals_mvp": rng.choice(config.get("finals_mvp_options", ["TBD"])),
        }
    picks = {}
    for series in window.config.get("series", []):
        teams = series.get("teams", ["Home", "Away"])
        exacts = series.get("exact_results", ["4-0", "4-1", "4-2", "4-3"])
        if any(team == "TBD" for team in teams):
            continue
        picks[series["series_key"]] = {
            "winner": rng.choice(teams),
            "exact_result": rng.choice(exacts),
        }
    return {"series": picks}


def auto_lock_due_windows(session, now: datetime | None = None) -> int:
    current_time = _normalize_aware(now or utcnow())
    locked_count = 0
    windows = session.scalars(select(BettingWindow).where(BettingWindow.is_locked.is_(False))).all()
    for window in windows:
        if _normalize_aware(window.locks_at) <= current_time:
            window.is_locked = True
            window.is_revealed = True
            window.revealed_at = current_time
            session.add(EventLog(pool_id=window.pool_id, actor_member_id=None, event_type="window_locked", payload={"window_id": window.id}))
            locked_count += 1
    side_bets = session.scalars(select(SideBet).where(SideBet.is_locked.is_(False))).all()
    for side_bet in side_bets:
        if _normalize_aware(side_bet.locks_at) <= current_time:
            side_bet.is_locked = True
            session.add(
                EventLog(
                    pool_id=side_bet.pool_id,
                    actor_member_id=None,
                    event_type="side_bet_locked",
                    payload={"side_bet_id": side_bet.id},
                )
            )
            locked_count += 1
    return locked_count


def process_windows() -> None:
    session = SessionLocal()
    try:
        now = utcnow()
        windows = session.scalars(select(BettingWindow)).all()
        side_bets = session.scalars(select(SideBet)).all()
        for window in windows:
            monkey_member = session.scalar(
                select(Membership)
                .join(User, Membership.user_id == User.id)
                .where(Membership.pool_id == window.pool_id, User.is_monkey.is_(True))
            )
            if monkey_member:
                existing_monkey_pick = session.scalar(
                    select(PickSubmission).where(PickSubmission.window_id == window.id, PickSubmission.member_id == monkey_member.id)
                )
                payload = _generate_monkey_payload(window)
                if window.opens_at <= now and not existing_monkey_pick and (window.bet_type == "early" or payload.get("series")):
                    session.add(
                        PickSubmission(
                            window_id=window.id,
                            member_id=monkey_member.id,
                            payload=payload,
                            submitted_at=now,
                        )
                    )
                    session.add(
                        EventLog(pool_id=window.pool_id, actor_member_id=monkey_member.id, event_type="monkey_submitted", payload={"window_id": window.id})
                    )
        for side_bet in side_bets:
            monkey_member = session.scalar(
                select(Membership)
                .join(User, Membership.user_id == User.id)
                .where(Membership.pool_id == side_bet.pool_id, User.is_monkey.is_(True))
            )
            if not monkey_member:
                continue
            existing_monkey_answer = session.scalar(
                select(SideBetSubmission).where(SideBetSubmission.side_bet_id == side_bet.id, SideBetSubmission.member_id == monkey_member.id)
            )
            if side_bet.opens_at <= now and not side_bet.is_locked and not existing_monkey_answer:
                session.add(
                    SideBetSubmission(
                        side_bet_id=side_bet.id,
                        member_id=monkey_member.id,
                        answer=random.choice(["yes", "no", "over", "under", "maybe", "team alpha"]),
                        submitted_at=now,
                    )
                )
                session.add(
                    EventLog(pool_id=side_bet.pool_id, actor_member_id=monkey_member.id, event_type="side_bet_submitted", payload={"side_bet_id": side_bet.id})
                )
        auto_lock_due_windows(session, now)

        health = provider_healthcheck()
        if windows:
            session.add(
                ResultSnapshot(
                    pool_id=windows[0].pool_id,
                    scope_type="system",
                    scope_key="provider_health",
                    payload=health,
                    source="scheduler",
                    is_override=False,
                    override_reason=None,
                )
            )
        session.commit()
    finally:
        session.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(process_windows, "interval", minutes=5, id="pool-automation", replace_existing=True)
    scheduler.start()
    return scheduler

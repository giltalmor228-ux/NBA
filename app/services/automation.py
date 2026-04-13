from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.db import SessionLocal
from app.models import BettingWindow, EventLog, Membership, PickSubmission, ResultSnapshot, User
from app.services.provider import provider_healthcheck


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def process_windows() -> None:
    session = SessionLocal()
    try:
        now = utcnow()
        windows = session.scalars(select(BettingWindow)).all()
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

            if not window.is_locked and window.locks_at <= now:
                window.is_locked = True
                window.is_revealed = True
                window.revealed_at = now
                session.add(EventLog(pool_id=window.pool_id, actor_member_id=None, event_type="window_locked", payload={"window_id": window.id}))

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

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    season_label: Mapped[str] = mapped_column(String(32), default="2025-26 / 2026 Playoffs")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str] = mapped_column(String(80))
    avatar: Mapped[str] = mapped_column(String(16), default="🏀")
    loser_photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_monkey: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32), default="player")
    side_bet_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    payout_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    payment_status: Mapped[str] = mapped_column(String(32), default="pending")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InviteLink(Base):
    __tablename__ = "invite_links"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    token: Mapped[str] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BettingWindow(Base):
    __tablename__ = "betting_windows"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    name: Mapped[str] = mapped_column(String(120))
    round_key: Mapped[str] = mapped_column(String(32))
    bet_type: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locks_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    monkey_seed: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PickSubmission(Base):
    __tablename__ = "pick_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    window_id: Mapped[str] = mapped_column(ForeignKey("betting_windows.id"))
    member_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResultSnapshot(Base):
    __tablename__ = "result_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    scope_type: Mapped[str] = mapped_column(String(32))
    scope_key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_member_id: Mapped[str | None] = mapped_column(ForeignKey("memberships.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SideBet(Base):
    __tablename__ = "side_bets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    question: Mapped[str] = mapped_column(String(255))
    answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    points_value: Mapped[int] = mapped_column(default=1)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locks_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SideBetSubmission(Base):
    __tablename__ = "side_bet_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    side_bet_id: Mapped[str] = mapped_column(ForeignKey("side_bets.id", ondelete="CASCADE"))
    member_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    answer: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_member_id: Mapped[str | None] = mapped_column(ForeignKey("memberships.id"), nullable=True)


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    actor_member_id: Mapped[str | None] = mapped_column(ForeignKey("memberships.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentLedgerEntry(Base):
    __tablename__ = "payment_ledger_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id"))
    member_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

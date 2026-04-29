from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


ROUND_POINTS = {
    "play_in": {"winner": 1, "exact_total": 0},
    "round_1": {"winner": 1, "exact_total": 3},
    "round_2": {"winner": 2, "exact_total": 5},
    "conference_finals": {"winner": 3, "exact_total": 8},
    "finals": {"winner": 4, "exact_total": 10},
}

EARLY_PICK_MAX = 16


@dataclass
class MemberState:
    member_id: str
    display_name: str
    payout_eligible: bool = True
    is_monkey: bool = False


@dataclass
class SubmissionEnvelope:
    window_id: str
    member_id: str
    submitted_at: datetime
    payload: dict[str, Any]


@dataclass
class ResultEnvelope:
    scope_type: str
    scope_key: str
    created_at: datetime
    payload: dict[str, Any]
    is_override: bool = False


@dataclass
class WindowEnvelope:
    window_id: str
    name: str
    round_key: str
    bet_type: str
    config: dict[str, Any]
    is_locked: bool


@dataclass
class LeaderboardEntry:
    member_id: str
    display_name: str
    payout_eligible: bool
    is_monkey: bool
    total_points: int = 0
    exact_hits: int = 0
    finals_mvp_correct: bool = False
    earliest_submission_at: datetime | None = None
    max_remaining_points: int = 0
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    rank: int = 0
    payout_rank: int | None = None

    @property
    def projected_ceiling(self) -> int:
        return self.total_points + self.max_remaining_points


def _normalize_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def latest_results(results: list[ResultEnvelope]) -> dict[tuple[str, str], ResultEnvelope]:
    ordered = sorted(results, key=lambda item: (item.scope_type, item.scope_key, item.created_at, item.is_override))
    result_map: dict[tuple[str, str], ResultEnvelope] = {}
    for item in ordered:
        result_map[(item.scope_type, item.scope_key)] = item
    return result_map


def early_pick_score(picks: dict[str, Any], result: dict[str, Any]) -> tuple[int, bool, list[dict[str, Any]]]:
    score = 0
    details = []
    for conference in ("East", "West"):
        predicted_cf = picks.get("conference_finalists", {}).get(conference)
        actual_cf = result.get("conference_finalists", {}).get(conference)
        hit = predicted_cf == actual_cf
        if hit:
            score += 2
        details.append({"label": f"{conference} conference finalist", "hit": hit, "points": 2 if hit else 0})

        predicted_finalist = picks.get("nba_finalists", {}).get(conference)
        actual_finalist = result.get("nba_finalists", {}).get(conference)
        hit = predicted_finalist == actual_finalist
        if hit:
            score += 3
        details.append({"label": f"{conference} NBA finalist", "hit": hit, "points": 3 if hit else 0})

    champion_hit = picks.get("champion") == result.get("champion")
    if champion_hit:
        score += 5
    details.append({"label": "NBA champion", "hit": champion_hit, "points": 5 if champion_hit else 0})

    fmvp_hit = picks.get("finals_mvp") == result.get("finals_mvp")
    if fmvp_hit:
        score += 1
    details.append({"label": "Finals MVP", "hit": fmvp_hit, "points": 1 if fmvp_hit else 0})
    return score, fmvp_hit, details


def _series_pick_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    series = payload.get("series", {})
    if isinstance(series, list):
        return {item["series_key"]: item for item in series}
    return series


def _exact_bonus(hit_count: int) -> int:
    if hit_count == 1:
        return 2
    if hit_count == 2:
        return 1
    return 0


def _series_max_remaining_points(round_points: dict[str, int]) -> int:
    if round_points["exact_total"] > 0:
        return round_points["exact_total"] + 2
    return round_points["winner"]


def score_pool(
    members: list[MemberState],
    windows: list[WindowEnvelope],
    submissions: list[SubmissionEnvelope],
    results: list[ResultEnvelope],
) -> list[LeaderboardEntry]:
    entries = {
        member.member_id: LeaderboardEntry(
            member_id=member.member_id,
            display_name=member.display_name,
            payout_eligible=member.payout_eligible,
            is_monkey=member.is_monkey,
        )
        for member in members
    }
    submissions_by_window: dict[str, dict[str, SubmissionEnvelope]] = {}
    for submission in submissions:
        submissions_by_window.setdefault(submission.window_id, {})[submission.member_id] = submission
        entry = entries.get(submission.member_id)
        submission_time = _normalize_timestamp(submission.submitted_at)
        if entry and submission_time and (
            entry.earliest_submission_at is None or submission_time < entry.earliest_submission_at
        ):
            entry.earliest_submission_at = submission_time
    result_map = latest_results(results)

    for window in windows:
        member_submissions = submissions_by_window.get(window.window_id, {})
        if window.bet_type == "early":
            result = result_map.get(("early", "season"))
            for member_id, entry in entries.items():
                submission = member_submissions.get(member_id)
                if not submission:
                    if not window.is_locked:
                        entry.max_remaining_points += EARLY_PICK_MAX
                    continue
                if not result:
                    entry.max_remaining_points += EARLY_PICK_MAX
                    continue
                points, fmvp_hit, details = early_pick_score(submission.payload, result.payload)
                entry.total_points += points
                entry.finals_mvp_correct = entry.finals_mvp_correct or fmvp_hit
                entry.breakdown.append({"window": window.name, "type": "early", "points": points, "details": details})
            continue

        series_config = window.config.get("series", [])
        for series_meta in series_config:
            series_key = series_meta["series_key"]
            result = result_map.get(("series", series_key))
            round_points = ROUND_POINTS[series_meta["round"]]
            exact_hit_members = set()
            if result and round_points["exact_total"] > 0:
                for member_id, submission in member_submissions.items():
                    pick = _series_pick_map(submission.payload).get(series_key)
                    if pick and pick.get("exact_result") == result.payload.get("exact_result"):
                        exact_hit_members.add(member_id)
            bonus_points = _exact_bonus(len(exact_hit_members))

            for member_id, entry in entries.items():
                submission = member_submissions.get(member_id)
                pick = _series_pick_map(submission.payload).get(series_key) if submission else None
                if not pick:
                    if not window.is_locked:
                        entry.max_remaining_points += _series_max_remaining_points(round_points)
                    continue
                if not result:
                    entry.max_remaining_points += _series_max_remaining_points(round_points)
                    continue

                winner_points = round_points["winner"] if pick.get("winner") == result.payload.get("winner") else 0
                exact_match = round_points["exact_total"] > 0 and pick.get("exact_result") == result.payload.get("exact_result")
                exact_points = max(round_points["exact_total"] - round_points["winner"], 0) if exact_match else 0
                if exact_match:
                    entry.exact_hits += 1
                bonus = bonus_points if exact_match else 0
                total = winner_points + exact_points + bonus
                entry.total_points += total
                entry.breakdown.append(
                    {
                        "window": window.name,
                        "type": "series",
                        "series_key": series_key,
                        "points": total,
                        "details": [
                            {"label": "Winner pick", "points": winner_points},
                            {"label": "Exact result upgrade", "points": exact_points},
                            {"label": "Exact bonus", "points": bonus},
                        ],
                    }
                )

    ordered = sorted(
        entries.values(),
        key=lambda item: (
            -item.total_points,
            -item.exact_hits,
            -int(item.finals_mvp_correct),
            item.earliest_submission_at or datetime.max.replace(tzinfo=timezone.utc),
            item.display_name.lower(),
        ),
    )
    payout_rank = 0
    for index, entry in enumerate(ordered, start=1):
        entry.rank = index
        if entry.payout_eligible:
            payout_rank += 1
            entry.payout_rank = payout_rank
    return ordered


def leaderboard_as_dict(entries: list[LeaderboardEntry]) -> list[dict[str, Any]]:
    return [asdict(entry) | {"projected_ceiling": entry.projected_ceiling} for entry in entries]

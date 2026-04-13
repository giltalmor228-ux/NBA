from datetime import datetime, timezone

from app.domain.scoring import MemberState, ResultEnvelope, SubmissionEnvelope, WindowEnvelope, score_pool


def dt() -> datetime:
    return datetime(2026, 4, 20, tzinfo=timezone.utc)


def test_scoring_exact_bonus_and_monkey_payout_skip() -> None:
    members = [
        MemberState(member_id="a", display_name="Avi", payout_eligible=True),
        MemberState(member_id="b", display_name="Ben", payout_eligible=True),
        MemberState(member_id="m", display_name="The Monkey", payout_eligible=True, is_monkey=True),
    ]
    windows = [
        WindowEnvelope(
            window_id="w1",
            name="Round 1",
            round_key="round_1",
            bet_type="series",
            is_locked=True,
            config={
                "series": [
                    {
                        "series_key": "R1-BOS-ORL",
                        "round": "round_1",
                        "teams": ["BOS", "ORL"],
                        "top_scorer_options": ["Tatum", "Banchero"],
                    }
                ]
            },
        )
    ]
    submissions = [
        SubmissionEnvelope(
            window_id="w1",
            member_id="a",
            submitted_at=dt(),
            payload={"series": {"R1-BOS-ORL": {"winner": "BOS", "exact_result": "4-1"}}},
        ),
        SubmissionEnvelope(
            window_id="w1",
            member_id="b",
            submitted_at=datetime(2026, 4, 20),
            payload={"series": {"R1-BOS-ORL": {"winner": "BOS", "exact_result": "4-1"}}},
        ),
        SubmissionEnvelope(
            window_id="w1",
            member_id="m",
            submitted_at=dt(),
            payload={"series": {"R1-BOS-ORL": {"winner": "BOS", "exact_result": "4-0"}}},
        ),
    ]
    results = [
        ResultEnvelope(
            scope_type="series",
            scope_key="R1-BOS-ORL",
            created_at=dt(),
            payload={"winner": "BOS", "exact_result": "4-1"},
        )
    ]

    leaderboard = score_pool(members, windows, submissions, results)

    assert leaderboard[0].member_id == "a"
    assert leaderboard[0].total_points == 5
    assert leaderboard[0].payout_rank == 1
    assert leaderboard[1].member_id == "b"
    assert leaderboard[1].total_points == 5
    assert leaderboard[1].payout_rank == 2
    assert leaderboard[2].member_id == "m"
    assert leaderboard[2].payout_rank == 3


def test_unresolved_windows_add_projected_ceiling() -> None:
    members = [MemberState(member_id="a", display_name="Avi", payout_eligible=True)]
    windows = [
        WindowEnvelope(
            window_id="early",
            name="Early Picks",
            round_key="early",
            bet_type="early",
            config={},
            is_locked=False,
        )
    ]
    submissions = []
    results = []
    leaderboard = score_pool(members, windows, submissions, results)
    assert leaderboard[0].max_remaining_points == 16

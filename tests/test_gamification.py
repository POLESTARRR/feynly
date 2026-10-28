from datetime import date

from src.gamification import (
    ALL_BADGES,
    attempt_xp,
    current_streak,
    earned_badge_keys,
    earned_badges,
    level_for_xp,
    locked_badges,
    longest_streak,
    total_xp,
)

TODAY = date(2026, 8, 18)


def attempt(concept="inflation", score=7.0, day="2026-08-18"):
    return (concept, score, f"{day}T10:00:00+00:00")


# ------------------------------------------------------------------- XP


def test_attempt_xp_rewards_score():
    assert attempt_xp(10) > attempt_xp(5) > attempt_xp(0)


def test_zero_score_still_earns_something():
    # Showing up and being wrong still beats not studying.
    assert attempt_xp(0) > 0


def test_total_xp_sums_attempts():
    attempts = [attempt(score=10), attempt(score=0)]
    assert total_xp(attempts) == attempt_xp(10) + attempt_xp(0)


def test_total_xp_empty():
    assert total_xp([]) == 0


# ---------------------------------------------------------------- levels


def test_level_one_at_zero_xp():
    info = level_for_xp(0)
    assert info.level == 1
    assert info.xp_into_level == 0


def test_level_increases_with_xp():
    assert level_for_xp(5000).level > level_for_xp(100).level


def test_levels_are_monotonic():
    levels = [level_for_xp(xp).level for xp in range(0, 3000, 50)]
    assert levels == sorted(levels)


def test_level_progress_fraction_within_bounds():
    for xp in (0, 50, 99, 100, 101, 500, 12345):
        assert 0.0 <= level_for_xp(xp).progress_fraction <= 1.0


def test_xp_into_level_never_exceeds_requirement():
    for xp in range(0, 2000, 37):
        info = level_for_xp(xp)
        assert info.xp_into_level < info.xp_for_next


# --------------------------------------------------------------- streaks


def test_no_streak_without_attempts():
    assert current_streak([], TODAY) == 0
    assert longest_streak([]) == 0


def test_streak_counts_consecutive_days():
    attempts = [attempt(day="2026-08-16"), attempt(day="2026-08-17"), attempt(day="2026-08-18")]
    assert current_streak(attempts, TODAY) == 3


def test_streak_survives_when_today_not_yet_studied():
    # Studied through yesterday; today isn't over, so the streak still stands.
    attempts = [attempt(day="2026-08-16"), attempt(day="2026-08-17")]
    assert current_streak(attempts, TODAY) == 2


def test_streak_breaks_after_a_missed_day():
    attempts = [attempt(day="2026-08-10"), attempt(day="2026-08-11")]
    assert current_streak(attempts, TODAY) == 0


def test_multiple_attempts_same_day_count_once():
    attempts = [attempt(day="2026-08-18"), attempt(day="2026-08-18")]
    assert current_streak(attempts, TODAY) == 1


def test_longest_streak_finds_best_run():
    attempts = [
        attempt(day="2026-08-01"), attempt(day="2026-08-02"), attempt(day="2026-08-03"),
        attempt(day="2026-08-10"),  # gap breaks it
        attempt(day="2026-08-18"),
    ]
    assert longest_streak(attempts) == 3


def test_malformed_timestamp_does_not_break_streaks():
    attempts = [attempt(day="2026-08-18"), ("x", 5.0, "not-a-date")]
    assert current_streak(attempts, TODAY) == 1


# ---------------------------------------------------------------- badges


def test_no_badges_without_attempts():
    assert earned_badge_keys([]) == set()


def test_first_steps_on_first_attempt():
    assert "first_steps" in earned_badge_keys([attempt()])


def test_perfectionist_requires_a_ten():
    assert "perfectionist" not in earned_badge_keys([attempt(score=9)])
    assert "perfectionist" in earned_badge_keys([attempt(score=10)])


def test_comeback_requires_recovery_from_a_low_score():
    recovered = [attempt(score=3), attempt(score=8)]
    assert "comeback" in earned_badge_keys(recovered)


def test_comeback_not_awarded_for_small_gain():
    assert "comeback" not in earned_badge_keys([attempt(score=3), attempt(score=5)])


def test_comeback_not_awarded_when_starting_high():
    assert "comeback" not in earned_badge_keys([attempt(score=6), attempt(score=10)])


def test_deep_diver_needs_five_attempts_at_one_concept():
    assert "deep_diver" not in earned_badge_keys([attempt() for _ in range(4)])
    assert "deep_diver" in earned_badge_keys([attempt() for _ in range(5)])


def test_deep_diver_not_earned_by_spreading_across_concepts():
    spread = [attempt(concept=f"c{i}") for i in range(5)]
    assert "deep_diver" not in earned_badge_keys(spread)


def test_explorer_and_scholar_thresholds():
    ten = [attempt(concept=f"c{i}") for i in range(10)]
    assert "explorer" in earned_badge_keys(ten)
    assert "scholar" not in earned_badge_keys(ten)

    twenty_five = [attempt(concept=f"c{i}") for i in range(25)]
    assert "scholar" in earned_badge_keys(twenty_five)


def test_century_at_one_hundred_attempts():
    assert "century" in earned_badge_keys([attempt() for _ in range(100)])
    assert "century" not in earned_badge_keys([attempt() for _ in range(99)])


def test_streak_badges():
    days = [attempt(day=f"2026-08-{d:02d}") for d in range(1, 4)]
    assert "consistent" in earned_badge_keys(days)
    assert "dedicated" not in earned_badge_keys(days)

    week = [attempt(day=f"2026-08-{d:02d}") for d in range(1, 8)]
    assert "dedicated" in earned_badge_keys(week)


def test_polymath_needs_three_subjects():
    attempts = [attempt(concept="a"), attempt(concept="b"), attempt(concept="c")]
    two = {"a": "chem", "b": "chem", "c": "physics"}
    assert "polymath" not in earned_badge_keys(attempts, two)

    three = {"a": "chem", "b": "bio", "c": "physics"}
    assert "polymath" in earned_badge_keys(attempts, three)


def test_subject_master_requires_all_concepts_in_the_subject():
    mapping = {"a": "chem", "b": "chem"}
    # Only one of chemistry's two concepts studied, not mastery.
    assert "subject_master" not in earned_badge_keys([attempt(concept="a", score=10)], mapping)

    both = [attempt(concept="a", score=9), attempt(concept="b", score=9)]
    assert "subject_master" in earned_badge_keys(both, mapping)


def test_subject_master_requires_high_average():
    mapping = {"a": "chem", "b": "chem"}
    mediocre = [attempt(concept="a", score=9), attempt(concept="b", score=5)]
    assert "subject_master" not in earned_badge_keys(mediocre, mapping)


def test_subject_master_ignores_uncategorized():
    mapping = {"a": None, "b": None}
    attempts = [attempt(concept="a", score=10), attempt(concept="b", score=10)]
    assert "subject_master" not in earned_badge_keys(attempts, mapping)


# ------------------------------------------------------------ partitions


def test_earned_and_locked_partition_all_badges():
    attempts = [attempt(score=10)]
    earned = earned_badges(attempts)
    locked = locked_badges(attempts)
    assert len(earned) + len(locked) == len(ALL_BADGES)
    assert not ({b.key for b in earned} & {b.key for b in locked})


def test_badges_are_recomputed_not_accumulated():
    """Derived state must reflect current history exactly, with no stickiness."""
    assert "perfectionist" not in earned_badge_keys([attempt(score=5)])


def test_all_badges_have_unique_keys():
    keys = [b.key for b in ALL_BADGES]
    assert len(keys) == len(set(keys))

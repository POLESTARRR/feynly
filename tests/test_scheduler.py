import random
from datetime import date

from src.scheduler import (
    DEFAULT_EASE,
    MIN_EASE,
    ReviewState,
    due_concepts,
    next_ease,
    pick_next,
    review_state,
    score_to_quality,
)

TODAY = date(2026, 8, 18)


# ------------------------------------------------------------------ mapping


def test_score_to_quality_maps_ten_point_to_five_point():
    assert score_to_quality(10) == 5.0
    assert score_to_quality(6) == 3.0
    assert score_to_quality(0) == 0.0


def test_score_to_quality_clamps():
    assert score_to_quality(20) == 5.0
    assert score_to_quality(-5) == 0.0


# --------------------------------------------------------------------- ease


def test_ease_increases_on_perfect_recall():
    assert next_ease(2.5, 5.0) > 2.5


def test_ease_decreases_on_poor_recall():
    assert next_ease(2.5, 2.0) < 2.5


def test_ease_never_falls_below_floor():
    ease = 2.5
    for _ in range(20):
        ease = next_ease(ease, 0.0)
    assert ease == MIN_EASE


# ------------------------------------------------------------------- SM-2


def test_first_successful_review_schedules_one_day_out():
    state = review_state(ReviewState(), score=8, today=TODAY)
    assert state.repetitions == 1
    assert state.interval_days == 1
    assert state.due == "2026-08-19"


def test_second_successful_review_schedules_six_days_out():
    first = review_state(ReviewState(), score=8, today=TODAY)
    second = review_state(first, score=8, today=TODAY)
    assert second.repetitions == 2
    assert second.interval_days == 6
    assert second.due == "2026-08-24"


def test_third_review_multiplies_interval_by_ease():
    state = ReviewState(ease=2.5, interval_days=6, repetitions=2, due="2026-08-18")
    third = review_state(state, score=10, today=TODAY)
    assert third.repetitions == 3
    assert third.interval_days == round(6 * third.ease)
    assert third.interval_days > 6


def test_lapse_resets_repetitions_and_interval():
    state = ReviewState(ease=2.5, interval_days=30, repetitions=5, due="2026-08-18")
    lapsed = review_state(state, score=2, today=TODAY)
    assert lapsed.repetitions == 0
    assert lapsed.interval_days == 1
    assert lapsed.due == "2026-08-19"


def test_lapse_lowers_ease_so_repeat_failures_grow_slower():
    state = ReviewState(ease=2.5, interval_days=30, repetitions=5)
    lapsed = review_state(state, score=2, today=TODAY)
    assert lapsed.ease < 2.5


def test_borderline_score_of_six_counts_as_pass():
    # 6/10 -> quality 3.0, exactly the pass threshold
    state = review_state(ReviewState(), score=6, today=TODAY)
    assert state.repetitions == 1


def test_score_of_five_counts_as_lapse():
    state = review_state(ReviewState(repetitions=3, interval_days=10), score=5, today=TODAY)
    assert state.repetitions == 0


# --------------------------------------------------------------- due dates


def test_never_studied_is_due():
    assert ReviewState().is_due(TODAY)


def test_future_due_date_is_not_due():
    assert not ReviewState(due="2026-08-25").is_due(TODAY)


def test_due_today_is_due():
    assert ReviewState(due="2026-08-18").is_due(TODAY)


def test_past_due_is_due():
    assert ReviewState(due="2026-08-01").is_due(TODAY)


def test_days_until_due():
    assert ReviewState(due="2026-08-25").days_until_due(TODAY) == 7
    assert ReviewState(due="2026-08-11").days_until_due(TODAY) == -7
    assert ReviewState(due="2026-08-18").days_until_due(TODAY) == 0


def test_due_concepts_sorted_most_overdue_first():
    states = {
        "a": ReviewState(due="2026-08-17"),   # 1 day overdue
        "b": ReviewState(due="2026-08-01"),   # 17 days overdue
        "c": ReviewState(due="2026-09-01"),   # not due
    }
    rows = due_concepts(states, TODAY)
    assert [c for c, _ in rows] == ["b", "a"]
    assert rows[0][1] == 17


def test_due_concepts_empty_when_nothing_due():
    states = {"a": ReviewState(due="2026-09-01")}
    assert due_concepts(states, TODAY) == []


# ------------------------------------------------------------ round-tripping


def test_review_state_dict_round_trip():
    state = ReviewState(ease=2.36, interval_days=6, repetitions=2, due="2026-08-24")
    assert ReviewState.from_dict(state.to_dict()) == state


def test_review_state_from_none_is_default():
    assert ReviewState.from_dict(None) == ReviewState()
    assert ReviewState.from_dict({}).ease == DEFAULT_EASE


# ------------------------------------------------------------- pick_next


def test_pick_next_returns_none_with_no_concepts():
    assert pick_next([], {}, {}) is None


def test_pick_next_prefers_due_review_over_everything():
    concepts = ["due_one", "weak_one", "fresh"]
    averages = {"due_one": 9.0, "weak_one": 2.0}
    states = {
        "due_one": ReviewState(due="2026-08-01", repetitions=3),
        "weak_one": ReviewState(due="2026-09-30", repetitions=3),
    }
    assert pick_next(concepts, averages, states, TODAY) == ("due_one", "due")


def test_pick_next_picks_most_overdue_first():
    concepts = ["a", "b"]
    averages = {"a": 5.0, "b": 5.0}
    states = {
        "a": ReviewState(due="2026-08-17"),
        "b": ReviewState(due="2026-08-01"),
    }
    assert pick_next(concepts, averages, states, TODAY)[0] == "b"


def test_pick_next_weak_bucket_on_low_roll():
    concepts = ["weak_one", "strong_one", "fresh"]
    averages = {"weak_one": 3.0, "strong_one": 9.0}
    states = {
        "weak_one": ReviewState(due="2026-09-30"),
        "strong_one": ReviewState(due="2026-09-30"),
    }
    rng = random.Random()
    rng.random = lambda: 0.1  # inside the weak share
    assert pick_next(concepts, averages, states, TODAY, rng) == ("weak_one", "weak")


def test_pick_next_strong_bucket_on_mid_roll():
    concepts = ["weak_one", "strong_one", "fresh"]
    averages = {"weak_one": 3.0, "strong_one": 9.0}
    states = {
        "weak_one": ReviewState(due="2026-09-30"),
        "strong_one": ReviewState(due="2026-09-30"),
    }
    rng = random.Random()
    rng.random = lambda: 0.7  # inside the strong share
    assert pick_next(concepts, averages, states, TODAY, rng) == ("strong_one", "strong")


def test_pick_next_new_bucket_on_high_roll():
    concepts = ["weak_one", "strong_one", "fresh"]
    averages = {"weak_one": 3.0, "strong_one": 9.0}
    states = {
        "weak_one": ReviewState(due="2026-09-30"),
        "strong_one": ReviewState(due="2026-09-30"),
    }
    rng = random.Random()
    rng.random = lambda: 0.95  # in the exploration share
    assert pick_next(concepts, averages, states, TODAY, rng) == ("fresh", "new")


def test_pick_next_falls_back_when_preferred_bucket_empty():
    # No unseen concepts at all; a high roll must still return something.
    concepts = ["weak_one"]
    averages = {"weak_one": 3.0}
    states = {"weak_one": ReviewState(due="2026-09-30")}
    rng = random.Random()
    rng.random = lambda: 0.95
    assert pick_next(concepts, averages, states, TODAY, rng) == ("weak_one", "weak")


def test_pick_next_unstudied_concept_is_due_immediately():
    # A brand-new concept has no review state, so it counts as due.
    assert pick_next(["fresh"], {}, {}, TODAY) == ("fresh", "new")


def test_pick_next_picks_weakest_within_weak_bucket():
    concepts = ["bad", "worse"]
    averages = {"bad": 5.0, "worse": 1.0}
    states = {c: ReviewState(due="2026-09-30") for c in concepts}
    rng = random.Random()
    rng.random = lambda: 0.1
    assert pick_next(concepts, averages, states, TODAY, rng)[0] == "worse"

import json
from datetime import date

from src.progress import ProgressStore

TODAY = date(2026, 8, 18)


def test_record_and_history(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "inflation", 7)
    store.record("chat1", "inflation", 9)

    history = store.history("chat1", "inflation")
    assert [e["score"] for e in history] == [7, 9]
    assert all("ts" in e for e in history)


def test_average(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "inflation", 4)
    store.record("chat1", "inflation", 8)
    assert store.average("chat1", "inflation") == 6
    assert store.average("chat1", "unseen") is None


def test_averages_map(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "a", 4)
    store.record("chat1", "b", 8)
    assert store.averages("chat1") == {"a": 4.0, "b": 8.0}


def test_latest_score(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "inflation", 3)
    store.record("chat1", "inflation", 9)
    assert store.latest_score("chat1", "inflation") == 9
    assert store.latest_score("chat1", "unseen") is None


def test_weakest_sorted_ascending_by_average(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "strong", 9)
    store.record("chat1", "weak", 2)
    store.record("chat1", "medium", 5)
    assert [r[0] for r in store.weakest("chat1")] == ["weak", "medium", "strong"]


def test_weakest_respects_limit(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    for i, concept in enumerate(["a", "b", "c", "d"]):
        store.record("chat1", concept, i)
    assert len(store.weakest("chat1", limit=2)) == 2


def test_weakest_empty_when_no_history(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    assert store.weakest("chat1") == []


def test_chats_are_isolated(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "inflation", 10)
    store.record("chat2", "inflation", 2)
    assert store.average("chat1", "inflation") == 10
    assert store.average("chat2", "inflation") == 2


def test_persists_across_instances(tmp_path):
    path = tmp_path / "progress.json"
    ProgressStore(path).record("chat1", "inflation", 5)
    assert ProgressStore(path).average("chat1", "inflation") == 5


def test_studied_concepts(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "b", 5)
    store.record("chat1", "a", 5)
    assert store.studied_concepts("chat1") == ["a", "b"]


def test_total_attempts(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "a", 5)
    store.record("chat1", "a", 6)
    store.record("chat1", "b", 7)
    assert store.total_attempts("chat1") == 3


def test_all_attempts_sorted_oldest_first(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "a", 5)
    store.record("chat1", "b", 7)
    rows = store.all_attempts("chat1")
    assert [r[0] for r in rows] == ["a", "b"]
    assert [r[1] for r in rows] == [5, 7]


# ------------------------------------------------- spaced repetition wiring


def test_record_returns_and_stores_review_state(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    state = store.record("chat1", "inflation", 8, today=TODAY)
    assert state.repetitions == 1
    assert state.due == "2026-08-19"
    assert store.review_state("chat1", "inflation").due == "2026-08-19"


def test_review_state_defaults_for_unstudied(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    assert store.review_state("chat1", "never").due is None


def test_review_state_survives_reload(tmp_path):
    path = tmp_path / "progress.json"
    ProgressStore(path).record("chat1", "inflation", 8, today=TODAY)
    assert ProgressStore(path).review_state("chat1", "inflation").due == "2026-08-19"


def test_due_lists_overdue_concepts(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    store.record("chat1", "old", 8, today=date(2026, 8, 1))
    store.record("chat1", "recent", 8, today=TODAY)
    due = store.due("chat1", today=TODAY)
    assert [c for c, _ in due] == ["old"]


def test_repeated_success_pushes_due_date_further_out(tmp_path):
    store = ProgressStore(tmp_path / "progress.json")
    first = store.record("chat1", "inflation", 9, today=TODAY)
    second = store.record("chat1", "inflation", 9, today=TODAY)
    assert second.interval_days > first.interval_days


# ------------------------------------------------------------- v1 migration


def test_migrates_v1_bare_list_format(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({
        "local": {"photosynthesis": [{"score": 5.0, "ts": "2026-08-18T01:00:00+00:00"}]}
    }))

    store = ProgressStore(path)
    assert store.average("local", "photosynthesis") == 5.0
    assert store.total_attempts("local") == 1
    # migrated entries get default review state, so they read as due now
    assert store.review_state("local", "photosynthesis").due is None


def test_migrated_data_can_be_updated(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({
        "local": {"photosynthesis": [{"score": 5.0, "ts": "2026-08-18T01:00:00+00:00"}]}
    }))

    store = ProgressStore(path)
    store.record("local", "photosynthesis", 9, today=TODAY)
    assert store.total_attempts("local") == 2
    assert store.review_state("local", "photosynthesis").due == "2026-08-19"

    # and the migration persists in v2 shape
    reloaded = ProgressStore(path)
    assert reloaded.total_attempts("local") == 2

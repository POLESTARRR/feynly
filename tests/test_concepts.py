import json

from src.concepts import UNCATEGORIZED, ConceptStore, ParsedConcept, parse_markdown_notes


# ------------------------------------------------------------------ parsing


def test_parse_markdown_notes_splits_on_h2():
    text = "# Title\nintro ignored\n\n## First Concept\nline one\nline two\n\n## Second\nother notes\n"
    parsed = parse_markdown_notes(text)
    assert set(parsed.keys()) == {"First Concept", "Second"}
    assert "line one" in parsed["First Concept"].notes
    assert parsed["Second"].notes == "other notes"


def test_h1_sets_subject_for_following_concepts():
    text = "# Chemistry\n\n## Covalent Bonding\nshared electrons\n\n# Physics\n\n## Inertia\nresists change\n"
    parsed = parse_markdown_notes(text)
    assert parsed["Covalent Bonding"].subject == "Chemistry"
    assert parsed["Inertia"].subject == "Physics"


def test_default_subject_applies_before_any_h1():
    text = "## Loose Concept\nsome notes\n"
    parsed = parse_markdown_notes(text, default_subject="biology")
    assert parsed["Loose Concept"].subject == "biology"


def test_h1_overrides_default_subject():
    text = "# Chemistry\n\n## Bonding\nnotes\n"
    parsed = parse_markdown_notes(text, default_subject="biology")
    assert parsed["Bonding"].subject == "Chemistry"


def test_subject_is_none_without_h1_or_default():
    parsed = parse_markdown_notes("## Solo\nnotes\n")
    assert parsed["Solo"].subject is None


def test_parse_ignores_content_before_first_concept_heading():
    parsed = parse_markdown_notes("no heading yet\n\n## Only\nbody\n")
    assert set(parsed) == {"Only"}
    assert parsed["Only"].notes == "body"


def test_parse_drops_empty_sections():
    parsed = parse_markdown_notes("## Empty\n\n## Real\nsomething\n")
    assert set(parsed) == {"Real"}


def test_headings_inside_code_fences_are_not_structure():
    text = "## Markdown Syntax\nUse this:\n```\n# Not a subject\n## Not a concept\n```\ndone\n"
    parsed = parse_markdown_notes(text)
    assert set(parsed) == {"Markdown Syntax"}
    assert "# Not a subject" in parsed["Markdown Syntax"].notes


def test_parse_handles_empty_input():
    assert parse_markdown_notes("") == {}


# -------------------------------------------------------------------- store


def test_add_and_get_is_case_insensitive(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Inflation", "some notes")
    assert store.get("inflation") == "some notes"
    assert store.get("  INFLATION  ") == "some notes"
    assert store.exists("Inflation")


def test_get_missing_returns_none(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    assert store.get("nope") is None
    assert not store.exists("nope")


def test_save_and_reload_round_trips(tmp_path):
    path = tmp_path / "concepts.json"
    store = ConceptStore(path)
    store.add("Inflation", "notes about inflation", subject="Economics")
    store.save()

    reloaded = ConceptStore(path)
    assert reloaded.get("inflation") == "notes about inflation"
    assert reloaded.subject_of("inflation") == "economics"
    assert len(reloaded) == 1


def test_merge_accepts_parsed_concepts(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.merge({"Bonding": ParsedConcept(notes="shared electrons", subject="Chemistry")})
    assert store.get("bonding") == "shared electrons"
    assert store.subject_of("bonding") == "chemistry"


def test_merge_accepts_bare_strings(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.merge({"A": "a-notes"})
    assert store.get("a") == "a-notes"
    assert store.subject_of("a") is None


def test_merge_keeps_existing_and_adds_new(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("A", "a-notes")
    store.merge({"B": "b-notes"})
    assert store.get("A") == "a-notes"
    assert store.get("B") == "b-notes"
    assert len(store) == 2


def test_replace_all_wipes_existing(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("A", "a-notes")
    store.replace_all({"B": "b-notes"})
    assert store.get("A") is None
    assert len(store) == 1


def test_names_sorted(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Zeta", "z")
    store.add("Alpha", "a")
    assert store.names() == ["alpha", "zeta"]


# ----------------------------------------------------------------- subjects


def test_names_filtered_by_subject(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Bonding", "n", subject="Chemistry")
    store.add("Inertia", "n", subject="Physics")
    assert store.names(subject="chemistry") == ["bonding"]
    assert store.names(subject="Chemistry") == ["bonding"]


def test_names_filtered_by_uncategorized(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Bonding", "n", subject="Chemistry")
    store.add("Loose", "n")
    assert store.names(subject=UNCATEGORIZED) == ["loose"]


def test_subjects_listed_with_uncategorized_last(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Loose", "n")
    store.add("Bonding", "n", subject="Chemistry")
    store.add("Inertia", "n", subject="Physics")
    assert store.subjects() == ["chemistry", "physics", UNCATEGORIZED]


def test_subjects_empty_store(tmp_path):
    assert ConceptStore(tmp_path / "concepts.json").subjects() == []


def test_subject_exists(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Bonding", "n", subject="Chemistry")
    assert store.subject_exists("chemistry")
    assert store.subject_exists("CHEMISTRY")
    assert not store.subject_exists("history")


def test_counts_by_subject(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("Bonding", "n", subject="Chemistry")
    store.add("Acids", "n", subject="Chemistry")
    store.add("Loose", "n")
    assert store.counts_by_subject() == {"chemistry": 2, UNCATEGORIZED: 1}


def test_subject_of_missing_concept(tmp_path):
    assert ConceptStore(tmp_path / "concepts.json").subject_of("nope") is None


# --------------------------------------------------------------- matching


def test_find_close_matches_prefix_and_substring(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("inflation", "n")
    store.add("deflation", "n")
    store.add("tcp vs udp", "n")
    assert "inflation" in store.find_close_matches("inflat")
    assert "tcp vs udp" in store.find_close_matches("udp")


def test_find_close_matches_empty_query(tmp_path):
    store = ConceptStore(tmp_path / "concepts.json")
    store.add("inflation", "n")
    assert store.find_close_matches("") == []


# ------------------------------------------------------------- persistence


def test_load_missing_file_starts_empty(tmp_path):
    store = ConceptStore(tmp_path / "does_not_exist.json")
    assert len(store) == 0
    assert store.warning is None


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "concepts.json"
    store = ConceptStore(path)
    store.add("A", "a")
    store.save()
    assert json.loads(path.read_text()) == {"a": {"notes": "a", "subject": None}}


def test_migrates_v1_bare_string_format(tmp_path):
    path = tmp_path / "concepts.json"
    path.write_text(json.dumps({"inflation": "old-style notes"}))

    store = ConceptStore(path)
    assert store.get("inflation") == "old-style notes"
    assert store.subject_of("inflation") is None


def test_migrated_store_saves_in_v2_shape(tmp_path):
    path = tmp_path / "concepts.json"
    path.write_text(json.dumps({"inflation": "old-style notes"}))

    store = ConceptStore(path)
    store.save()
    assert json.loads(path.read_text())["inflation"] == {"notes": "old-style notes", "subject": None}


def test_corrupt_file_is_quarantined_not_fatal(tmp_path):
    path = tmp_path / "concepts.json"
    path.write_text("{ this is not json")

    store = ConceptStore(path)
    assert len(store) == 0
    assert store.warning is not None
    assert any(p.name.startswith("concepts.json.corrupt-") for p in tmp_path.iterdir())

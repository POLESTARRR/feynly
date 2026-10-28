#!/usr/bin/env python3
"""Notes loader.

Usage:
    python src/load_notes.py notes.md                     # merge into the store
    python src/load_notes.py notes.md --replace           # wipe the store first
    python src/load_notes.py chem.md --subject chemistry  # tag everything in the file
    python src/load_notes.py a.md b.md c.md               # load several files at once

Structure of a notes file:
    ## Concept Name      starts a concept; the text under it is the source
    # Subject Name       groups every concept beneath it under that subject

A `--subject` flag applies to concepts that appear before any `#` heading.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.concepts import ConceptStore, parse_markdown_notes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load markdown notes into the concept store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("notes_files", type=Path, nargs="+", help="One or more markdown files")
    parser.add_argument("--replace", action="store_true", help="Overwrite the store instead of merging")
    parser.add_argument("--subject", default=None, help="Subject for concepts with no '# Subject' heading")
    parser.add_argument("--store", type=Path, default=None, help="Path to concepts.json")
    args = parser.parse_args()

    missing = [f for f in args.notes_files if not f.exists()]
    if missing:
        for f in missing:
            print(f"Notes file not found: {f}", file=sys.stderr)
        return 1

    parsed_all = {}
    per_file = []
    for notes_file in args.notes_files:
        text = notes_file.read_text(encoding="utf-8")
        parsed = parse_markdown_notes(text, default_subject=args.subject)
        if not parsed:
            print(f"No '## Concept' sections found in {notes_file}, skipped.", file=sys.stderr)
            continue
        per_file.append((notes_file, parsed))
        parsed_all.update(parsed)

    if not parsed_all:
        print("Nothing loaded.", file=sys.stderr)
        return 1

    store = ConceptStore(args.store) if args.store else ConceptStore()
    if store.warning:
        print(f"Warning: {store.warning}", file=sys.stderr)

    if args.replace:
        store.replace_all(parsed_all)
        verb = "Replaced store with"
    else:
        store.merge(parsed_all)
        verb = "Merged"
    store.save()

    for notes_file, parsed in per_file:
        subjects = sorted({c.subject or "uncategorized" for c in parsed.values()})
        print(f"{notes_file.name}: {len(parsed)} concept(s) [{', '.join(subjects)}]")

    print(f"\n{verb} {len(parsed_all)} concept(s).")
    print(f"Store now has {len(store)} concept(s) across {len(store.subjects())} subject(s).")
    for subject, count in sorted(store.counts_by_subject().items()):
        print(f"  {subject}: {count}")
    print(f"Saved to {store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

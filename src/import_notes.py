#!/usr/bin/env python3
"""Turn photos of notes into markdown you can study from.

Point it at a photo of a whiteboard, a textbook page, a cheat sheet, or
handwritten notes, and it transcribes them into the `## Concept` markdown the
concept store expects, using `claude -p`'s vision on your subscription, so it
costs nothing extra.

    python src/import_notes.py photo.jpg
    python src/import_notes.py page1.jpg page2.jpg --subject chemistry
    python src/import_notes.py whiteboard.png --load        # skip the review step

By default it writes a markdown file and STOPS, so you can read it before
loading. That step matters: these notes become the authority every future
explanation is graded against, so a transcription mistake would quietly become
a grading mistake forever. Review beats convenience here.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.concepts import ConceptStore, parse_markdown_notes  # noqa: E402
from src.llm import ProviderError, get_provider  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = PROJECT_ROOT / "notes"
# claude -p only reads files it has permission for; staging inside the project
# avoids the sandbox refusing paths like /tmp.
STAGING_DIR = PROJECT_ROOT / "data" / ".import"

CLAUDE_BIN = "claude"
IMPORT_TIMEOUT_SECONDS = 180

SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".pdf"}

PROMPT = """Read the image at {path} and transcribe it into markdown study notes.

Rules:
- Use `## Concept Name` for each distinct concept, topic, or term.
- Write the material under each heading as clear prose or bullet points.
- {subject_rule}
- Transcribe faithfully. Do NOT add facts that are not in the image, and do not
  correct or embellish the content, these notes will be used as the authority
  for grading, so invented detail is worse than missing detail.
- If some text is genuinely unreadable, write `[unclear]` rather than guessing.
- Ignore page furniture: headers, footers, page numbers, watermarks, URLs.
- Output ONLY the markdown. No preamble, no explanation, no code fences."""

SUBJECT_RULE_WITH = "Begin the file with a single `# {subject}` heading as the subject."
SUBJECT_RULE_WITHOUT = (
    "If the image shows an overall subject or chapter title, put it as a single "
    "`# Subject` heading at the top; otherwise omit any `#` heading."
)


class ImportError_(RuntimeError):
    """Raised when an image cannot be transcribed."""


def _strip_fences(text: str) -> str:
    """Remove a wrapping ```markdown fence if the model added one anyway."""
    text = text.strip()
    fenced = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n?```$", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text


def transcribe_image(image: Path, subject: str | None = None) -> str:
    """Transcribe one image to markdown via `claude -p`. Raises ImportError_ on failure."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged = STAGING_DIR / image.name
    try:
        shutil.copy2(image, staged)
        relative = staged.relative_to(PROJECT_ROOT)
        subject_rule = (
            SUBJECT_RULE_WITH.format(subject=subject) if subject else SUBJECT_RULE_WITHOUT
        )
        prompt = PROMPT.format(path=f"./{relative}", subject_rule=subject_rule)

        try:
            raw = get_provider().complete_with_image(prompt, staged)
        except ProviderError as exc:
            raise ImportError_(str(exc)) from exc

        markdown = _strip_fences(raw)
        if not markdown:
            raise ImportError_(f"Got an empty transcription for {image.name}.")
        if "##" not in markdown:
            raise ImportError_(
                f"No '## Concept' headings found in the transcription of {image.name}, "
                "the image may not contain readable notes."
            )
        return markdown
    finally:
        staged.unlink(missing_ok=True)


def output_path(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return NOTES_DIR / f"imported_{stamp}.md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe photos of notes into study markdown using claude -p vision.",
    )
    parser.add_argument("images", type=Path, nargs="+", help="Image files (png, jpg, pdf, ...)")
    parser.add_argument("--subject", "-s", default=None, help="Subject to file these notes under")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Where to write the markdown")
    parser.add_argument(
        "--load", action="store_true",
        help="Load into the concept store immediately, skipping the review step",
    )
    args = parser.parse_args()

    missing = [i for i in args.images if not i.exists()]
    for image in missing:
        print(f"Not found: {image}", file=sys.stderr)
    if missing:
        return 1

    odd = [i for i in args.images if i.suffix.lower() not in SUPPORTED_SUFFIXES]
    for image in odd:
        print(f"Warning: {image.name} is not a recognised image type, trying anyway.", file=sys.stderr)

    sections: list[str] = []
    failures = 0
    for index, image in enumerate(args.images, start=1):
        print(f"[{index}/{len(args.images)}] Reading {image.name} ...", flush=True)
        try:
            # Only the first image carries the `# Subject` heading, so several
            # pages of one subject merge into one file instead of repeating it.
            markdown = transcribe_image(image, args.subject if index == 1 else None)
        except ImportError_ as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            failures += 1
            continue

        if index > 1:
            markdown = re.sub(r"^#\s+.*$", "", markdown, count=1, flags=re.MULTILINE).strip()
        sections.append(markdown)
        found = len(parse_markdown_notes(markdown))
        print(f"  got {found} concept(s)")

    if not sections:
        print("Nothing transcribed.", file=sys.stderr)
        return 1

    combined = "\n\n".join(sections) + "\n"
    parsed = parse_markdown_notes(combined, default_subject=args.subject)

    destination = output_path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(combined, encoding="utf-8")

    print(f"\nWrote {len(parsed)} concept(s) to {destination}")
    if failures:
        print(f"({failures} image(s) failed.)")

    if not args.load:
        print("\nRead it over and fix anything the transcription got wrong -")
        print("these notes become the answer key every explanation is graded against.")
        print(f"\nThen load it:\n  python src/load_notes.py {destination}")
        return 0

    store = ConceptStore()
    store.merge(parsed)
    store.save()
    print(f"Loaded into the concept store, now {len(store)} concept(s) total.")
    print("Check them with: python src/study.py list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

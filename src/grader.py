"""Grades a user's explanation of a concept against their source notes.

The judge is whichever backend `llm.py` is configured for: `claude -p` locally
on a Claude subscription, or Gemini's free tier when deployed. The notes and the
explanation are passed fresh on every call, so grading stays grounded in what the
user actually wrote for that concept rather than in anything the model recalls.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable

from src.llm import ProviderError, get_provider

GRADE_ATTEMPTS = 3           # total tries, including the first
RETRY_BACKOFF_SECONDS = 2    # multiplied by the attempt number

GRADING_PROMPT_TEMPLATE = """You are a strict but fair study grader using the Feynman technique. \
A student is trying to prove they understand a concept by explaining it in their own words. \
Grade their explanation ONLY against the source notes below, do not use outside knowledge, \
and do not reward correct-sounding claims that the notes don't actually support.

SOURCE NOTES for "{concept}":
---
{notes}
---

STUDENT'S EXPLANATION:
---
{explanation}
---

Evaluate the explanation and respond with ONLY a single JSON object (no markdown fences, \
no prose outside the JSON) with this exact shape:

{{
  "score": <integer 0-10>,
  "correct": ["point the student got right", ...],
  "vague": ["point the student gestured at but didn't clearly nail down", ...],
  "wrong_or_missing": ["point that is wrong, or an important point from the notes the student left out", ...],
  "notes_gaps": ["claim the student made that is plausible and relevant but that the notes simply don't cover", ...],
  "summary": "one or two sentence overall verdict, direct and specific"
}}

Scoring guide: 9-10 = explained fully and precisely in their own words. 6-8 = core idea right, \
missing nuance or minor gaps. 3-5 = partial/vague understanding, several gaps. 0-2 = mostly wrong \
or a restatement of jargon without real explanation. Empty lists are fine when there's nothing to \
report for that category.

Keep "wrong_or_missing" and "notes_gaps" strictly distinct. Something the notes contradict, or an \
important point the notes make that the student omitted, is wrong_or_missing and should cost them \
score. Something the student asserted that the notes are simply silent on is a notes_gap: it means \
their notes may be incomplete, NOT that the student was wrong, so it must not reduce the score. \
Output raw JSON only."""


class GradingError(RuntimeError):
    """A grading attempt failed.

    `transient` marks failures worth retrying (a timeout, a hiccup in the CLI, a
    malformed reply) as opposed to ones that will fail identically every time
    (the `claude` binary not being installed).
    """

    def __init__(self, message: str, transient: bool = True):
        super().__init__(message)
        self.transient = transient


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown code fences if the model added them despite instructions.
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back to grabbing the first {...} block in case of stray prose.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise GradingError(f"No JSON object found in grader output: {raw[:300]!r}")
    return json.loads(match.group(0))


def _validate(result: dict) -> dict:
    if "score" not in result:
        raise GradingError(f"Grader output missing 'score': {result!r}")
    try:
        score = float(result["score"])
    except (TypeError, ValueError) as exc:
        raise GradingError(f"Grader 'score' is not numeric: {result.get('score')!r}") from exc
    score = max(0.0, min(10.0, score))
    return {
        "score": score,
        "correct": list(result.get("correct") or []),
        "vague": list(result.get("vague") or []),
        "wrong_or_missing": list(result.get("wrong_or_missing") or []),
        "notes_gaps": list(result.get("notes_gaps") or []),
        "summary": str(result.get("summary") or "").strip(),
    }


def _grade_once(concept: str, notes: str, explanation: str, provider=None) -> dict:
    """One grading attempt against the configured backend."""
    prompt = GRADING_PROMPT_TEMPLATE.format(concept=concept, notes=notes, explanation=explanation)
    provider = provider or get_provider()
    try:
        raw = provider.complete(prompt)
    except ProviderError as exc:
        # Carry the backend's own transient/permanent judgement through, so a
        # missing binary or a bad API key is not retried three times over.
        raise GradingError(str(exc), transient=exc.transient) from exc

    return _validate(_extract_json(raw))


def grade_explanation(
    concept: str,
    notes: str,
    explanation: str,
    attempts: int = GRADE_ATTEMPTS,
    on_retry: Callable[[int, GradingError], None] | None = None,
    provider=None,
) -> dict:
    """Grade `explanation` against `notes`, retrying transient failures.

    The model occasionally returns prose instead of JSON, and the CLI can time
    out under load. Both are worth one more try before making the user retype a
    long explanation. `on_retry(attempt_number, error)` is called before each
    retry so a UI can say what's happening.

    Raises GradingError once retries are exhausted, so callers decide how to
    surface it rather than silently mis-scoring the user.
    """
    # Build the provider once so a retry does not re-read config or re-open a client.
    provider = provider or get_provider()
    last_error: GradingError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _grade_once(concept, notes, explanation, provider)
        except GradingError as exc:
            last_error = exc
            if not exc.transient or attempt >= attempts:
                raise
            if on_retry:
                on_retry(attempt, exc)
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise last_error  # unreachable; retained so the contract is explicit

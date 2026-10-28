"""One interface over two backends, so the same grading logic runs locally and deployed.

Locally, Feynly grades with `claude -p` on your Claude Code subscription: free,
private, and nothing leaves your machine except the prompt. That cannot work on a
public host, which has no Claude Code CLI and must not carry your subscription
token, so the deployed instance uses Gemini's free tier instead.

Grading, the tutor and photo import all talk to
`complete()` and `complete_with_image()` and never knows which backend answered.

Selection: `LLM_PROVIDER` env var ("claude" or "gemini"), defaulting to claude.
"""

from __future__ import annotations

import mimetypes
import os
import subprocess
from pathlib import Path
from typing import Protocol

DEFAULT_PROVIDER = "claude"
CLAUDE_BIN = "claude"
CLAUDE_TIMEOUT_SECONDS = 180

# Verified against a real free-tier key. Ordered by preference, and tried in turn
# when one is overloaded: free-tier models return 503 under load often enough that
# a single hard-coded model makes the app look broken when it is merely busy.
# Flash before flash-lite, because the vague-vs-wrong distinction is a judgement
# call and the lite tiers blur it.
GEMINI_MODELS = (
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
)
GEMINI_DEFAULT_MODEL = GEMINI_MODELS[0]


class ProviderError(RuntimeError):
    """A backend failed to produce a completion.

    `transient` marks failures worth retrying (timeouts, overload, a malformed
    reply) as opposed to permanent ones (missing binary, missing API key).
    """

    def __init__(self, message: str, transient: bool = True):
        super().__init__(message)
        self.transient = transient


class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str:
        """Return the model's text response to `prompt`."""

    def complete_with_image(self, prompt: str, image: Path) -> str:
        """Return the model's text response to `prompt` about `image`."""


# ------------------------------------------------------------------ claude


class ClaudeCodeProvider:
    """Headless Claude Code. Free on a Claude subscription; local only."""

    name = "claude"

    def __init__(self, binary: str = CLAUDE_BIN, timeout: int = CLAUDE_TIMEOUT_SECONDS):
        self.binary = binary
        self.timeout = timeout

    def _run(self, prompt: str, cwd: str | None = None) -> str:
        try:
            proc = subprocess.run(
                [self.binary, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise ProviderError(
                "`claude` CLI not found on PATH. Install Claude Code and run "
                "`claude setup-token`, or set LLM_PROVIDER=gemini.",
                transient=False,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"claude timed out after {self.timeout}s.") from exc

        if proc.returncode != 0:
            raise ProviderError(f"`claude -p` exited {proc.returncode}: {proc.stderr.strip()[:400]}")

        reply = proc.stdout.strip()
        if not reply:
            raise ProviderError("claude returned an empty reply.")
        return reply

    def complete(self, prompt: str) -> str:
        return self._run(prompt)

    def complete_with_image(self, prompt: str, image: Path) -> str:
        # claude -p reads images by path, and only paths it has permission for,
        # so callers stage the file inside the project before calling.
        return self._run(f"{prompt}\n\nThe image is at: {image}", cwd=str(image.parent.parent.parent))


# ------------------------------------------------------------------ gemini


class GeminiProvider:
    """Google Gemini. Used for the deployed instance, which needs a real free tier."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        # Read explicitly rather than letting the SDK scan the environment: it
        # silently prefers GOOGLE_API_KEY over GEMINI_API_KEY, which can pick up
        # an unrelated key that happens to be set on the machine.
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or ""
        pinned = model or os.environ.get("GEMINI_MODEL")
        # A pinned model means exactly that: no silent substitution behind the
        # user's back. Otherwise fall through the preference list on overload.
        self.models = (pinned,) if pinned else GEMINI_MODELS
        self._client = None

    @property
    def model(self) -> str:
        """The model actually tried first."""
        return self.models[0]

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Add it to .env, or use LLM_PROVIDER=claude.",
                transient=False,
            )
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError(
                "google-genai is not installed. Run: pip install google-genai",
                transient=False,
            ) from exc
        self._client = genai.Client(api_key=self.api_key)
        return self._client

    @staticmethod
    def _text_of(response) -> str:
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise ProviderError("Gemini returned an empty reply.")
        return text

    def _wrap(self, exc: Exception) -> ProviderError:
        message = str(exc)
        # 4xx other than 429 are permanent: a bad key or a retired model will
        # fail identically forever, so retrying just wastes the user's time.
        permanent = any(code in message for code in ("400", "401", "403", "404"))
        return ProviderError(f"Gemini call failed: {message[:400]}", transient=not permanent)

    def _generate(self, contents) -> str:
        """Try each candidate model, moving on when one is merely overloaded."""
        client = self._get_client()
        last: ProviderError | None = None

        for model in self.models:
            try:
                return self._text_of(
                    client.models.generate_content(model=model, contents=contents)
                )
            except ProviderError as exc:
                # An empty reply is this model's problem; a permanent error is
                # ours. Neither is worth trying the next model for.
                if not exc.transient:
                    raise
                last = exc
            except Exception as exc:  # noqa: BLE001 - SDK raises many concrete types
                wrapped = self._wrap(exc)
                if not wrapped.transient:
                    raise wrapped from exc
                last = wrapped

        raise last or ProviderError("No Gemini model produced a reply.")

    def complete(self, prompt: str) -> str:
        return self._generate(prompt)

    def complete_with_image(self, prompt: str, image: Path) -> str:
        # Surface a missing key before doing any local work.
        self._get_client()

        # Read the file before touching the SDK. A missing or unreadable image is
        # a permanent, local problem; doing it inside the API try-block would let
        # it be reported as a retryable Gemini failure.
        try:
            data = image.read_bytes()
        except OSError as exc:
            raise ProviderError(f"Could not read {image.name}: {exc}", transient=False) from exc

        try:
            from google.genai import types

            mime = mimetypes.guess_type(str(image))[0] or "image/png"
            part = types.Part.from_bytes(data=data, mime_type=mime)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc) from exc

        return self._generate([part, prompt])


# ----------------------------------------------------------------- factory


PROVIDERS = {"claude": ClaudeCodeProvider, "gemini": GeminiProvider}


def get_provider(name: str | None = None) -> LLMProvider:
    """Build the configured provider. `name` overrides the LLM_PROVIDER env var."""
    chosen = (name or os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if chosen not in PROVIDERS:
        raise ProviderError(
            f"Unknown LLM_PROVIDER {chosen!r}. Expected one of: {', '.join(sorted(PROVIDERS))}.",
            transient=False,
        )
    return PROVIDERS[chosen]()

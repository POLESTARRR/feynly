"""The provider abstraction that lets the same logic run on claude -p or Gemini."""

import subprocess
from pathlib import Path

import pytest

from src import llm
from src.llm import (
    ClaudeCodeProvider,
    GeminiProvider,
    ProviderError,
    get_provider,
)


def _proc(returncode=0, stdout="", stderr=""):
    class P:
        pass

    P.returncode = returncode
    P.stdout = stdout
    P.stderr = stderr
    return P()


# ----------------------------------------------------------------- factory


def test_defaults_to_claude(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert get_provider().name == "claude"


def test_env_var_selects_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert get_provider().name == "gemini"


def test_explicit_name_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert get_provider("claude").name == "claude"


def test_selection_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  GEMINI  ")
    assert get_provider().name == "gemini"


def test_unknown_provider_is_permanent_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    with pytest.raises(ProviderError) as exc:
        get_provider()
    assert exc.value.transient is False
    assert "gemini" in str(exc.value)  # tells you the valid options


# ------------------------------------------------------------------ claude


def test_claude_returns_stdout(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "  the answer  "))
    assert ClaudeCodeProvider().complete("prompt") == "the answer"


def test_claude_missing_binary_is_permanent(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(ProviderError) as exc:
        ClaudeCodeProvider().complete("prompt")
    assert exc.value.transient is False
    # Points at the escape hatch rather than dead-ending.
    assert "LLM_PROVIDER=gemini" in str(exc.value)


def test_claude_timeout_is_transient(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=180)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(ProviderError) as exc:
        ClaudeCodeProvider().complete("prompt")
    assert exc.value.transient is True


def test_claude_nonzero_exit_is_transient(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1, "", "boom"))
    with pytest.raises(ProviderError) as exc:
        ClaudeCodeProvider().complete("prompt")
    assert exc.value.transient is True


def test_claude_empty_reply_rejected(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, "   "))
    with pytest.raises(ProviderError, match="empty"):
        ClaudeCodeProvider().complete("prompt")


def test_claude_image_prompt_includes_path(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["prompt"] = cmd[2]
        return _proc(0, "## Concept\n\nnotes")

    monkeypatch.setattr(subprocess, "run", fake_run)
    image = tmp_path / "a" / "b" / "photo.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"x")

    ClaudeCodeProvider().complete_with_image("read this", image)
    assert str(image) in captured["prompt"]
    assert "read this" in captured["prompt"]


# ------------------------------------------------------------------ gemini


class FakeModels:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error
        self.calls = []

    def generate_content(self, model, contents):
        self.calls.append({"model": model, "contents": contents})
        if self.error:
            raise self.error

        class R:
            pass

        R.text = self.text
        return R()


class FakeClient:
    def __init__(self, models):
        self.models = models


def gemini_with(models, **kwargs):
    provider = GeminiProvider(api_key="test-key", **kwargs)
    provider._client = FakeClient(models)
    return provider


def test_gemini_returns_text():
    provider = gemini_with(FakeModels(text="  hello  "))
    assert provider.complete("prompt") == "hello"


def test_gemini_uses_configured_model():
    models = FakeModels(text="ok")
    gemini_with(models, model="gemini-3.5-flash").complete("prompt")
    assert models.calls[0]["model"] == "gemini-3.5-flash"


def test_gemini_model_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    assert GeminiProvider(api_key="k").model == "gemini-3.1-flash-lite"


def test_missing_api_key_is_permanent(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderError) as exc:
        GeminiProvider(api_key="").complete("prompt")
    assert exc.value.transient is False
    assert "LLM_PROVIDER=claude" in str(exc.value)


def test_api_key_is_not_read_from_google_api_key(monkeypatch):
    """The SDK silently prefers GOOGLE_API_KEY; a stray one must not be picked up."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "someone-elses-key")
    assert GeminiProvider().api_key == ""


def test_gemini_empty_reply_rejected():
    with pytest.raises(ProviderError, match="empty"):
        gemini_with(FakeModels(text="")).complete("prompt")


@pytest.mark.parametrize("code", ["400", "401", "403", "404"])
def test_client_errors_are_permanent(code):
    provider = gemini_with(FakeModels(error=RuntimeError(f"{code} NOT_FOUND")))
    with pytest.raises(ProviderError) as exc:
        provider.complete("prompt")
    assert exc.value.transient is False


@pytest.mark.parametrize("message", ["429 RESOURCE_EXHAUSTED", "503 UNAVAILABLE", "connection reset"])
def test_overload_and_network_errors_are_transient(message):
    provider = gemini_with(FakeModels(error=RuntimeError(message)))
    with pytest.raises(ProviderError) as exc:
        provider.complete("prompt")
    assert exc.value.transient is True


def test_gemini_image_sends_bytes_and_prompt(tmp_path):
    """Uses the real SDK types so the part shape stays honest."""
    models = FakeModels(text="## Concept\n\nnotes")
    provider = gemini_with(models)

    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG fake")

    assert provider.complete_with_image("transcribe this", image).startswith("## Concept")

    contents = models.calls[0]["contents"]
    assert contents[1] == "transcribe this"
    # The first element is the image part built by google.genai.types.
    assert getattr(contents[0], "inline_data", None) is not None
    assert contents[0].inline_data.mime_type == "image/png"
    assert contents[0].inline_data.data == b"\x89PNG fake"


def test_gemini_infers_mime_from_extension(tmp_path):
    models = FakeModels(text="ok")
    provider = gemini_with(models)
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff fake")

    provider.complete_with_image("prompt", image)
    assert models.calls[0]["contents"][0].inline_data.mime_type == "image/jpeg"


def test_unreadable_image_is_permanent(tmp_path):
    provider = gemini_with(FakeModels(text="x"))
    with pytest.raises(ProviderError) as exc:
        provider.complete_with_image("prompt", tmp_path / "missing.png")
    assert exc.value.transient is False


# --------------------------------------------------------------- contract


@pytest.mark.parametrize("provider_name", ["claude", "gemini"])
def test_both_providers_satisfy_the_interface(provider_name, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    provider = get_provider(provider_name)
    assert provider.name == provider_name
    assert callable(provider.complete)
    assert callable(provider.complete_with_image)


# ------------------------------------------------------- model fallback


class SequencedModels:
    """Raises the queued error for each call until one succeeds."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.tried = []

    def generate_content(self, model, contents):
        self.tried.append(model)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        class R:
            pass

        R.text = outcome
        return R()


def test_overloaded_model_falls_through_to_the_next():
    models = SequencedModels([RuntimeError("503 UNAVAILABLE"), "recovered"])
    provider = gemini_with(models)
    assert provider.complete("prompt") == "recovered"
    assert len(models.tried) == 2
    assert models.tried[0] != models.tried[1]


def test_fallback_tries_each_model_once_then_gives_up():
    from src.llm import GEMINI_MODELS

    models = SequencedModels([RuntimeError("503 UNAVAILABLE")] * len(GEMINI_MODELS))
    with pytest.raises(ProviderError, match="503"):
        gemini_with(models).complete("prompt")
    assert models.tried == list(GEMINI_MODELS)


def test_permanent_error_does_not_try_other_models():
    """A bad key fails identically everywhere; burning the list helps nobody."""
    models = SequencedModels([RuntimeError("403 PERMISSION_DENIED"), "unused"])
    with pytest.raises(ProviderError) as exc:
        gemini_with(models).complete("prompt")
    assert exc.value.transient is False
    assert len(models.tried) == 1


def test_pinned_model_is_never_substituted():
    """An explicit choice must be honoured, not silently swapped on overload."""
    models = SequencedModels([RuntimeError("503 UNAVAILABLE")])
    provider = gemini_with(models, model="gemini-3.5-flash")
    with pytest.raises(ProviderError):
        provider.complete("prompt")
    assert models.tried == ["gemini-3.5-flash"]


def test_pinned_via_env_is_also_respected(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    provider = GeminiProvider(api_key="k")
    assert provider.models == ("gemini-3.1-flash-lite",)


def test_default_tries_the_preference_list():
    from src.llm import GEMINI_MODELS

    assert GeminiProvider(api_key="k").models == GEMINI_MODELS
    assert GeminiProvider(api_key="k").model == GEMINI_MODELS[0]


def test_image_path_also_falls_back(tmp_path):
    models = SequencedModels([RuntimeError("503 UNAVAILABLE"), "## Concept\n\nnotes"])
    provider = gemini_with(models)
    image = tmp_path / "p.png"
    image.write_bytes(b"\x89PNG")

    assert provider.complete_with_image("read", image).startswith("## Concept")
    assert len(models.tried) == 2

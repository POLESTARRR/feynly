#!/usr/bin/env python3
"""One-shot deploy to Hugging Face Spaces.

Creates the Space if it does not exist, uploads the secrets it needs, pushes the
code, and reports the URL. Everything it needs comes from the environment or
`.env`, so no credential is ever passed on the command line where it would land
in shell history.

    export HF_TOKEN=hf_...        # a write token from huggingface.co/settings/tokens
    python scheduling/deploy_hf.py

Re-running is safe: an existing Space is updated rather than duplicated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SPACE_NAME = os.environ.get("HF_SPACE_NAME", "feynly")

# Uploaded as Space secrets. Everything here is required for the deployed app to
# work at all, so a missing one is reported before the Space is touched.
REQUIRED_SECRETS = (
    "GEMINI_API_KEY",
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "FLASK_SECRET_KEY",
)

# Plain variables: not sensitive, and visible in the Space settings.
VARIABLES = {"LLM_PROVIDER": "gemini"}

# Only what the container needs. Notes, progress and .env stay on your machine.
UPLOAD = ("src", "Dockerfile", "requirements-deploy.txt", "sample_notes.md", "README.md")

SPACE_README = """---
title: Feynly
emoji: 🧠
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Feynly

Explain a concept in your own words and get graded against your own notes.

Built on the Feynman technique: you do not understand something until you can
explain it simply. Feynly grades the explanation rather than testing recall, and
tells you what you got right, where you were vague, what you got wrong, and what
your notes never covered in the first place.

Source: https://github.com/POLESTARRR/feynly
"""


def fail(message: str) -> None:
    print(f"\n  {message}\n", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        fail("python-dotenv is missing. Run: pip install python-dotenv")
    load_dotenv(PROJECT_ROOT / ".env")

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        fail(
            "HF_TOKEN is not set.\n"
            "  Create a WRITE token at https://huggingface.co/settings/tokens\n"
            "  then run:  export HF_TOKEN=hf_your_token_here"
        )

    missing = [name for name in REQUIRED_SECRETS if not os.environ.get(name)]
    if missing:
        fail("Missing from .env: " + ", ".join(missing))

    try:
        from huggingface_hub import HfApi
    except ImportError:
        fail("huggingface_hub is missing. Run: pip install huggingface_hub")

    api = HfApi(token=token)

    try:
        user = api.whoami()["name"]
    except Exception as exc:  # noqa: BLE001
        fail(f"That token was rejected: {exc}")

    repo_id = f"{user}/{SPACE_NAME}"
    print(f"Deploying to {repo_id} as {user}")

    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="docker",
        exist_ok=True,
        private=False,
    )
    print("  space ready")

    # Secrets before the code, so the first container start already has them.
    for name in REQUIRED_SECRETS:
        api.add_space_secret(repo_id=repo_id, key=name, value=os.environ[name])
    print(f"  {len(REQUIRED_SECRETS)} secrets uploaded")

    for key, value in VARIABLES.items():
        api.add_space_variable(repo_id=repo_id, key=key, value=value)
    print(f"  {len(VARIABLES)} variable(s) set")

    readme = PROJECT_ROOT / ".hf_readme.md"
    readme.write_text(SPACE_README, encoding="utf-8")
    try:
        api.upload_file(
            path_or_fileobj=str(readme),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="space",
        )
    finally:
        readme.unlink(missing_ok=True)

    for item in UPLOAD:
        source = PROJECT_ROOT / item
        if not source.exists():
            continue
        if source.is_dir():
            api.upload_folder(
                folder_path=str(source),
                path_in_repo=item,
                repo_id=repo_id,
                repo_type="space",
                ignore_patterns=["__pycache__/*", "*.pyc"],
            )
        elif item != "README.md":  # the Space README is the one written above
            api.upload_file(
                path_or_fileobj=str(source),
                path_in_repo=item,
                repo_id=repo_id,
                repo_type="space",
            )
        print(f"  uploaded {item}")

    url = f"https://huggingface.co/spaces/{repo_id}"
    print(f"\nDone. Building now, which takes a few minutes.\n  {url}\n")
    print("When it is live, open it in a private window too. It should look like")
    print("a brand new account with none of your notes. If your notes show up")
    print("there, stop and say so: sessions are not isolated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

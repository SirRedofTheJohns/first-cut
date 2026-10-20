"""Build and deploy the Hugging Face Space (Gradio + ZeroGPU).

    uv run python scripts/deploy_space.py --build-only   # just assemble build/space/
    uv run python scripts/deploy_space.py                # assemble and upload

The Space gets the `firstcut` package as source (no wheel needed), the sample briefs and a
trimmed Figma response for the sample brand, so the demo never spends Figma API quota.
API keys go in as Space *secrets*, read from the local .env; they are never uploaded as files.
"""

import argparse
import os
import shutil
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "space"
SECRETS = ("GOOGLE_API_KEY", "GROQ_API_KEY")
VARIABLES = {
    "LLM_PROVIDER": "google_genai",
    # Flash-Lite: 500 requests/day and 15/min on the free tier (Flash models: 20/day).
    "LLM_MODEL": "gemini-3.5-flash-lite",
    "LLM_REQUESTS_PER_SECOND": "0.25",
    "LLM_FALLBACK_PROVIDER": "groq",
    "LLM_FALLBACK_MODEL": "openai/gpt-oss-120b",
    "FIRSTCUT_ENABLE_ZEROGPU": "1",
}


def build() -> Path:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    for name in ("app.py", "zerogpu.py", "requirements.txt", "README.md"):
        shutil.copy(ROOT / "app" / name, BUILD / name)
    shutil.copytree(
        ROOT / "src" / "firstcut",
        BUILD / "firstcut",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(ROOT / "briefs", BUILD / "briefs")
    shutil.copy(ROOT / "tests" / "fixtures" / "figma_masa_brand.json", BUILD / "brand_fixture.json")
    return BUILD


def deploy(repo_id: str) -> None:
    # Locally from .env; in CI from the environment (GitHub Actions secrets).
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    api = HfApi(token=env["HF_TOKEN"])
    api.create_repo(
        repo_id,
        repo_type="space",
        space_sdk="gradio",
        space_hardware="zero-a10g",  # ZeroGPU
        exist_ok=True,
    )
    for key in SECRETS:
        if env.get(key):  # already-set Space secrets are kept when a key isn't available
            api.add_space_secret(repo_id, key, env[key])
    for key, value in VARIABLES.items():
        api.add_space_variable(repo_id, key, value)
    api.upload_folder(
        folder_path=BUILD, repo_id=repo_id, repo_type="space", commit_message="Deploy First Cut"
    )
    print(f"https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="SirRedOfTheJohns/first-cut")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    print("built", build())
    if not args.build_only:
        deploy(args.repo)

from pathlib import Path

from firstcut.config import Settings
from firstcut.integrations.figma import FigmaClient
from firstcut.integrations.gdocs import GoogleDocsClient


def figma_client(settings: Settings) -> FigmaClient | None:
    if settings.figma_token is None or not settings.figma_token.get_secret_value():
        return None
    return FigmaClient(
        settings.figma_token.get_secret_value(),
        Path(settings.figma_cache_dir),
        settings.figma_cache_hours,
    )


def gdocs_client(settings: Settings) -> GoogleDocsClient | None:
    key = settings.google_application_credentials
    if not key or not Path(key).exists():
        return None  # a Google Doc brief then fails with a message naming the setting
    return GoogleDocsClient(Path(key))

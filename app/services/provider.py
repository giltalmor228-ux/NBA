from __future__ import annotations

from typing import Protocol

import httpx

from app.config import get_settings


class NbaDataProvider(Protocol):
    def fetch_games(self, season: str) -> dict:
        ...


class BallDontLieProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch_games(self, season: str) -> dict:
        headers = {"Authorization": self.settings.nba_provider_api_key} if self.settings.nba_provider_api_key else {}
        with httpx.Client(timeout=20.0, headers=headers) as client:
            response = client.get(f"{self.settings.nba_provider_base_url}/games", params={"seasons[]": season})
            response.raise_for_status()
            return response.json()


def provider_healthcheck() -> dict[str, str]:
    settings = get_settings()
    if not settings.nba_provider_api_key:
        return {"status": "degraded", "message": "NBA provider API key missing; live validation is disabled."}
    return {"status": "ok", "message": "Provider configured."}

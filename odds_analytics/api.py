from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings


@dataclass(slots=True)
class ApiResponse:
    status_code: int
    payload: Any
    headers: dict[str, str]


class OddsApiClient:
    def __init__(self, timeout: int | None = None) -> None:
        self.timeout = timeout or Settings.ODDS_API_TIMEOUT
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "OddsAnalytics/1.0"})

    def _get(self, path: str, api_key: str, **params) -> ApiResponse:
        response = self.session.get(
            f"{Settings.ODDS_API_BASE_URL}{path}",
            params={"apiKey": api_key, **params},
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return ApiResponse(response.status_code, payload, dict(response.headers))

    def get_sports(self, api_key: str) -> ApiResponse:
        return self._get("/sports/", api_key)

    def get_odds(self, api_key: str, league_key: str) -> ApiResponse:
        return self._get(
            f"/sports/{league_key}/odds/",
            api_key,
            regions="eu",
            markets="h2h,spreads,totals",
            oddsFormat="decimal",
        )

    def get_scores(self, api_key: str, league_key: str) -> ApiResponse:
        return self._get(
            f"/sports/{league_key}/scores/",
            api_key,
            daysFrom=3,
        )

    def check_balance(self, api_key: str) -> int:
        response = self.get_sports(api_key)
        if response.status_code == 200:
            try:
                return int(response.headers.get("x-requests-remaining", 0))
            except (TypeError, ValueError):
                return 0
        return -1

"""Client HTTP commun : cooldown par endpoint, retries, mode hors-ligne (fixtures)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests


class ProviderError(Exception):
    pass


class QuotaExhausted(ProviderError):
    pass


class HttpClient:
    def __init__(self, name: str, offline: bool = False, fixtures_dir: Path | None = None,
                 timeout: int = 40, log=print):
        self.name = name
        self.offline = offline
        self.fixtures_dir = fixtures_dir
        self.timeout = timeout
        self.log = log
        self._last_call: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "betlab/0.1 (simulation, personal project)"
        self.calls = 0

    # ------------------------------------------------------------------
    def _fixture(self, fixture_name: str):
        p = self.fixtures_dir / self.name / f"{fixture_name}.json"
        if not p.exists():
            raise ProviderError(f"[offline] fixture manquante: {p}")
        with open(p, encoding="utf-8") as f:
            payload = json.load(f)
        # une fixture peut être {"status":..,"headers":..,"json":..} ou directement le JSON
        if isinstance(payload, dict) and "json" in payload and "status" in payload:
            return payload["status"], payload["json"], payload.get("headers", {})
        return 200, payload, {}

    def get(self, url: str, params: dict | None = None, *, endpoint: str = "",
            cooldown: float = 0.0, fixture_name: str | None = None, retries: int = 2,
            headers: dict | None = None):
        """Retourne (status, json, headers). Lève ProviderError si échec définitif."""
        self.calls += 1
        if self.offline:
            return self._fixture(fixture_name or endpoint)

        key = endpoint or url
        last = self._last_call.get(key)
        if last is not None and cooldown > 0:
            wait = cooldown - (time.time() - last)
            if wait > 0:
                time.sleep(wait)

        err = None
        for attempt in range(retries + 1):
            try:
                self._last_call[key] = time.time()
                r = self.session.get(url, params=params, timeout=self.timeout, headers=headers)
            except requests.RequestException as e:
                err = ProviderError(f"{self.name} {endpoint}: {e}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 304:
                return 304, None, dict(r.headers)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1) + cooldown)
                continue
            try:
                body = r.json() if r.content else None
            except ValueError:
                body = None
            if r.status_code == 429:
                raise QuotaExhausted(f"{self.name} {endpoint}: 429 {body}")
            if r.status_code >= 400:
                raise ProviderError(f"{self.name} {endpoint}: HTTP {r.status_code} {str(body)[:200]}")
            return r.status_code, body, dict(r.headers)
        raise err or ProviderError(f"{self.name} {endpoint}: échec")

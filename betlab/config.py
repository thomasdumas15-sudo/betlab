"""Chargement de config.yaml + variables d'environnement (.env)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("BETLAB_ROOT", Path(__file__).resolve().parent.parent))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


class Config:
    def __init__(self, path: Path | None = None):
        _load_dotenv(ROOT / ".env")
        self.path = path or ROOT / "config.yaml"
        with open(self.path, encoding="utf-8") as f:
            self.raw: dict = yaml.safe_load(f)
        self.root = ROOT
        self.data_dir = ROOT / "data"
        self.docs_dir = ROOT / "docs"
        self.offline = os.environ.get("BETLAB_OFFLINE", "") == "1"
        self.fixtures_dir = Path(os.environ.get("BETLAB_FIXTURES", ROOT / "tests" / "fixtures"))

    # --- accès simples
    def __getitem__(self, k):
        return self.raw[k]

    def get(self, k, default=None):
        return self.raw.get(k, default)

    @property
    def tz(self) -> str:
        return self.raw.get("timezone", "Europe/Paris")

    @property
    def sports(self) -> dict:
        return self.raw["sports"]

    @property
    def strategies(self) -> dict:
        return {k: v for k, v in self.raw["strategies"].items() if v.get("enabled", True)}

    @property
    def bookmakers(self) -> dict:
        return self.raw["bookmakers"]

    def book_slug(self, canonical: str, provider: str) -> str | None:
        return self.bookmakers.get(canonical, {}).get(provider)

    def canonical_book(self, provider: str, slug: str) -> str | None:
        slug = (slug or "").lower()
        for canon, m in self.bookmakers.items():
            if (m.get(provider) or "").lower() == slug:
                return canon
        return None

    def key(self, name: str) -> str | None:
        v = os.environ.get(name, "").strip()
        return v or None

    @property
    def has_oddspapi(self) -> bool:
        return bool(self.key("ODDSPAPI_KEY")) or self.offline

    @property
    def has_theoddsapi(self) -> bool:
        return bool(self.key("THEODDSAPI_KEY")) or self.offline

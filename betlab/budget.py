"""Gestionnaire de budget : répartit un quota mensuel gratuit sur le mois.

Règle : allocation journalière = (restant - réserve) / jours restants.
Un appel de priorité 1 (NBA) peut dépasser l'allocation du jour tant que la
réserve n'est pas entamée ; les autres priorités s'arrêtent à l'allocation.
"""
from __future__ import annotations

from .util import days_left_in_month, month_key, now_utc


class Budget:
    def __init__(self, cfg, state: dict):
        self.cfg = cfg
        self.state = state.setdefault("budget", {})
        self.log: list[str] = []

    def _p(self, provider: str) -> dict:
        now = now_utc()
        p = self.state.setdefault(provider, {})
        if p.get("month") != month_key(now):
            p.update({"month": month_key(now), "used": 0, "today": now.date().isoformat(),
                      "used_today": 0, "reported_remaining": None, "denied": 0})
        if p.get("today") != now.date().isoformat():
            p["today"] = now.date().isoformat()
            p["used_today"] = 0
        return p

    def quota(self, provider: str) -> int:
        return int(self.cfg["providers"].get(provider, {}).get("monthly_quota", 0))

    def reserve(self, provider: str) -> int:
        return int(self.cfg["providers"].get(provider, {}).get("reserve", 0))

    def remaining(self, provider: str) -> int:
        p = self._p(provider)
        rep = p.get("reported_remaining")
        est = self.quota(provider) - int(p.get("used", 0))
        if rep is not None:
            return min(est, int(rep))
        return est

    def daily_allowance(self, provider: str) -> float:
        rem = self.remaining(provider) - self.reserve(provider)
        return max(0.0, rem / max(1, days_left_in_month(now_utc())))

    def can_spend(self, provider: str, n: int = 1, priority: int = 5) -> bool:
        p = self._p(provider)
        rem = self.remaining(provider)
        if rem - n < 0:
            return False
        allowance = self.daily_allowance(provider)
        if p["used_today"] + n <= max(allowance, 1.0):
            return True
        # priorité haute : on accepte de puiser un peu plus, sans toucher la réserve
        if priority <= 1 and rem - n >= self.reserve(provider):
            return True
        p["denied"] = int(p.get("denied", 0)) + 1
        return False

    def spend(self, provider: str, n: int = 1, what: str = "") -> None:
        p = self._p(provider)
        p["used"] = int(p.get("used", 0)) + n
        p["used_today"] = int(p.get("used_today", 0)) + n
        self.log.append(f"{provider}: -{n} ({what}) restant≈{self.remaining(provider)}")

    def report_remaining(self, provider: str, remaining: int | None, used: int | None = None) -> None:
        """Mise à jour depuis les headers/compte du fournisseur (valeur fiable)."""
        p = self._p(provider)
        if remaining is not None:
            p["reported_remaining"] = int(remaining)
        if used is not None:
            p["used"] = max(int(p.get("used", 0)), int(used))

    def summary(self) -> dict:
        out = {}
        for provider in self.cfg["providers"]:
            p = self._p(provider)
            out[provider] = {
                "quota": self.quota(provider),
                "used": int(p.get("used", 0)),
                "remaining": self.remaining(provider),
                "used_today": int(p.get("used_today", 0)),
                "daily_allowance": round(self.daily_allowance(provider), 1),
                "reserve": self.reserve(provider),
                "denied": int(p.get("denied", 0)),
            }
        return out

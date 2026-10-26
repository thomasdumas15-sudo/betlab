"""Utilitaires : temps, probabilités (de-vig), Kelly, normalisation des noms."""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


# ---------------------------------------------------------------- temps
_FAKE_NOW: datetime | None = None   # utilisé par la démo et les tests


def set_fake_now(dt: datetime | None) -> None:
    global _FAKE_NOW
    _FAKE_NOW = dt.astimezone(UTC) if dt else None


def now_utc() -> datetime:
    if _FAKE_NOW is not None:
        return _FAKE_NOW
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> datetime | None:
    """Parse ISO 8601 (avec Z, +00:00, fractions de seconde…) -> datetime UTC."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # tronquer les fractions > 6 chiffres
    m = re.match(r"^(.*\.\d{6})\d+([+-]\d{2}:\d{2})$", s)
    if m:
        s = m.group(1) + m.group(2)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_now(tz_name: str) -> datetime:
    return now_utc().astimezone(ZoneInfo(tz_name))


def in_window(local_dt: datetime, window: str) -> bool:
    """window = 'HH:MM-HH:MM' en heure locale."""
    a, b = window.split("-")
    h1, m1 = map(int, a.split(":"))
    h2, m2 = map(int, b.split(":"))
    t = local_dt.hour * 60 + local_dt.minute
    return h1 * 60 + m1 <= t <= h2 * 60 + m2


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def days_left_in_month(dt: datetime) -> int:
    nxt = (dt.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (nxt - dt.replace(hour=0, minute=0, second=0, microsecond=0)).days


# ---------------------------------------------------------------- probas
def implied(odds: float) -> float:
    return 1.0 / odds if odds and odds > 1.0 else 0.0


def devig(prices: dict[str, float], method: str = "proportional") -> dict[str, float]:
    """Retire la marge d'un marché (dict outcome -> cote décimale).

    proportional : p_i = (1/o_i) / sum(1/o_j)   (standard, robuste)
    power        : p_i = (1/o_i)^k avec k tel que sum = 1 (corrige le biais favori/outsider)
    """
    probs = {k: implied(v) for k, v in prices.items() if v and v > 1.0}
    if len(probs) < 2:
        return {}
    total = sum(probs.values())
    if total <= 0:
        return {}
    if method == "power":
        lo, hi = 0.5, 3.0
        for _ in range(60):
            k = (lo + hi) / 2
            s = sum(p ** k for p in probs.values())
            if s > 1:
                lo = k
            else:
                hi = k
        k = (lo + hi) / 2
        out = {o: p ** k for o, p in probs.items()}
        tot = sum(out.values())
        return {o: p / tot for o, p in out.items()}
    return {o: p / total for o, p in probs.items()}


def margin(prices: dict[str, float]) -> float | None:
    probs = [implied(v) for v in prices.values() if v and v > 1.0]
    if len(probs) < 2:
        return None
    return sum(probs) - 1.0


def kelly_fraction(p: float, odds: float) -> float:
    """Fraction de Kelly pleine. b = odds - 1."""
    b = odds - 1.0
    if b <= 0 or p <= 0:
        return 0.0
    f = (p * b - (1 - p)) / b
    return max(0.0, f)


def kelly_stake(bankroll: float, p: float, odds: float, fraction: float,
                max_pct: float, min_pct: float) -> float:
    f = kelly_fraction(p, odds) * fraction
    if f <= 0:
        return 0.0
    f = min(f, max_pct)
    f = max(f, min_pct)
    return round(bankroll * f, 2)


# ---------------------------------------------------------------- noms
_STOP = {
    "fc", "cf", "sc", "ac", "as", "bc", "bk", "kk", "club", "basket", "basketball",
    "de", "the", "le", "la", "les", "los", "del", "ss", "ssc", "us", "rc", "og", "fk",
    "sv", "vfb", "vfl", "tsg", "1", "04", "05", "1899", "1909", "hc", "cp", "ud",
}

_ALIASES = {
    # NBA
    "la clippers": "los angeles clippers",
    "la lakers": "los angeles lakers",
    "ny knicks": "new york knicks",
    "gs warriors": "golden state warriors",
    "okc thunder": "oklahoma city thunder",
    "sa spurs": "san antonio spurs",
    "no pelicans": "new orleans pelicans",
    # Foot FR / divers
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "paris saint-germain": "paris saint germain",
    "olympique marseille": "marseille",
    "olympique de marseille": "marseille",
    "olympique lyonnais": "lyon",
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham hotspur",
    "inter": "inter milan",
    "internazionale": "inter milan",
    "fc internazionale milano": "inter milan",
    "atletico de madrid": "atletico madrid",
    "athletic club": "athletic bilbao",
    "bayern munchen": "bayern munich",
    "fc bayern munchen": "bayern munich",
    "borussia monchengladbach": "monchengladbach",
    "borussia m'gladbach": "monchengladbach",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_name(name: str | None) -> str:
    if not name:
        return ""
    s = strip_accents(name).lower().strip()
    s = re.sub(r"[\.\-_/']", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _ALIASES.get(s, s)
    return s


def name_tokens(name: str | None) -> set[str]:
    return {t for t in norm_name(name).split() if t not in _STOP}


def name_similarity(a: str | None, b: str | None) -> float:
    """Jaccard sur les tokens + bonus si l'un contient l'autre."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    inter = len(ta & tb)
    union = len(ta | tb)
    j = inter / union if union else 0.0
    if ta <= tb or tb <= ta:
        j = max(j, 0.8)
    # tennis : "Nom Prénom" vs "Prénom Nom" -> même tokens, ok. Nom de famille seul -> inclusion.
    return j


def stable_hash(*parts: object) -> int:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:12], 16)


def pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.{digits}f} %".replace(".", ",")


def mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def stdev(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

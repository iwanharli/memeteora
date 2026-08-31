"""Hard gates. These remove pools; they never contribute to a score.

Anything that survives here is a real, tradeable pool. Everything that
distinguishes a good one from a bad one is left to scoring.
"""
from sources import split_legs

DEFAULTS = dict(min_tvl=50_000, min_volume=100_000, min_holders=500, min_age_hours=24)


def check(p, cfg, now_ms):
    if p.get("is_blacklisted"):
        return "blacklisted", None, None
    if (p.get("tvl") or 0) < cfg["min_tvl"]:
        return "tvl", None, None
    if (p["volume"].get("24h") or 0) < cfg["min_volume"]:
        return "volume", None, None

    base, quote = split_legs(p)
    if base is None:
        return "no-quote-leg", None, None
    if not base.get("freeze_authority_disabled", True):
        return "freeze-authority", None, None   # the mint can freeze your position
    if (base.get("holders") or 0) < cfg["min_holders"]:
        return "holders", None, None
    if (now_ms - (p.get("created_at") or 0)) / 3.6e6 < cfg["min_age_hours"]:
        return "too-new", None, None
    return None, base, quote

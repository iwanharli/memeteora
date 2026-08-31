"""Historical candles, used only to seed volatility before our own on-chain
price series is long enough.

No single vendor covers every Meteora pool. Measured on 73 gated pools:
DexPaprika 71% (rest are genuine 404s), GeckoTerminal ~12% at speed but it
indexes pools DexPaprika misses, so the union reaches ~81% and the remainder
are rate-limit, not absence. They are tried in that order, per pool.
"""
import json, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

UA = {"Accept": "application/json", "User-Agent": "memet/1.0"}
DEXPAPRIKA = "https://api.dexpaprika.com/networks/solana/pools/{}/ohlcv?start={}&interval=1h&limit={}"
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana/pools/{}/ohlcv/hour?limit={}"

# measured sustainable rates; below these both APIs start returning 429
DELAY = {"dexpaprika": 1.5, "geckoterminal": 2.5}


def _get(url, tries=2, backoff=3.0):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(backoff)
                continue
            raise
    return None


def from_dexpaprika(pool, hours=100):
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")
    d = _get(DEXPAPRIKA.format(pool, start, hours))
    if not isinstance(d, list):
        return []
    out = []
    for c in d:
        ts = datetime.fromisoformat(c["time_open"].replace("Z", "+00:00"))
        out.append((ts, c["open"], c["high"], c["low"], c["close"], c.get("volume")))
    return out


def from_geckoterminal(pool, hours=100):
    d = _get(GECKO.format(pool, hours))
    lst = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    out = []
    for ts, o, h, l, c, v in lst:
        out.append((datetime.fromtimestamp(ts, timezone.utc), o, h, l, c, v))
    return sorted(out)


def fetch(pool, hours=100):
    """-> (rows, source). Empty list if no vendor has this pool."""
    for name, fn in (("dexpaprika", from_dexpaprika), ("geckoterminal", from_geckoterminal)):
        try:
            rows = fn(pool, hours)
        except Exception:
            rows = []
        time.sleep(DELAY[name])
        if len(rows) >= 24:
            return rows, name
    return [], None

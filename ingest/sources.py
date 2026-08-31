"""Data sources: Meteora datapi (pool metrics) + DexScreener (price action)."""
import json, time, urllib.parse, urllib.request

METEORA = "https://dlmm.datapi.meteora.ag/pools"
DEXS = "https://api.dexscreener.com/latest/dex/pairs/solana/"
QUOTES = {"SOL", "USDC", "USDT"}
UA = {"User-Agent": "memet-screener/1.0"}


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def fetch_pools(pages=3, page_size=1000, sort="tvl:desc"):
    """TVL-sorted so we never page through the 120k+ dust pools."""
    out = []
    for page in range(1, pages + 1):
        q = urllib.parse.urlencode({"page": page, "page_size": page_size, "sort_by": sort})
        d = _get(f"{METEORA}?{q}")
        out.extend(d.get("data", []))
        if page >= d.get("pages", 1):
            break
        time.sleep(0.15)          # well under the documented 30 rps
    return out


def split_legs(p):
    """Return (base_token, quote_symbol). Base is the leg carrying the risk."""
    x, y = p["token_x"], p["token_y"]
    if y["symbol"] in QUOTES and x["symbol"] not in QUOTES:
        return x, y["symbol"]
    if x["symbol"] in QUOTES and y["symbol"] not in QUOTES:
        return y, x["symbol"]
    if x["symbol"] in QUOTES and y["symbol"] in QUOTES:
        return x, y["symbol"]      # SOL-USDC and friends
    return None, None              # exotic pair, no clean quote leg


def fetch_price_action(addresses, batch=30):
    """DexScreener takes up to 30 comma-separated pair addresses per call."""
    res = {}
    for i in range(0, len(addresses), batch):
        chunk = addresses[i:i + batch]
        try:
            d = _get(DEXS + ",".join(chunk))
        except Exception:
            continue
        for pr in (d.get("pairs") or []):
            ch = pr.get("priceChange") or {}
            tx = (pr.get("txns") or {}).get("h24") or {}
            res[pr["pairAddress"]] = dict(
                price_usd=_f(pr.get("priceUsd")),
                chg_5m=ch.get("m5"), chg_1h=ch.get("h1"),
                chg_6h=ch.get("h6"), chg_24h=ch.get("h24"),
                buys_24h=tx.get("buys"), sells_24h=tx.get("sells"),
                liquidity_usd=(pr.get("liquidity") or {}).get("usd"),
                fdv=pr.get("fdv"))
        time.sleep(0.3)
    return res


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

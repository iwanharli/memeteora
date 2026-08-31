"""Exact pool price straight from the LbPair account.

This is the only source with complete coverage: every tracked pool in a single
getMultipleAccounts call, no vendor indexing gaps and no rate limit worth
worrying about. Third-party OHLCV is only ever a backfill for history we
haven't collected yet.

Offsets validated against the API: the decoded bin_step matches pool_config
for every pool, and decoded prices match observed market prices.
"""
import base64, json, struct, time, urllib.request

RPC = "https://api.mainnet-beta.solana.com"
BATCH = 100                       # getMultipleAccounts hard limit

# LbPair layout, from the discriminator:
#   8  anchor discriminator
#   32 StaticParameters
#   32 VariableParameters
#   1  bump  |  2 bin_step_seed  |  1 pair_type  |  4 active_id  |  2 bin_step
_ACTIVE_ID = 8 + 32 + 32 + 4
_BIN_STEP = _ACTIVE_ID + 4


def _rpc(method, params, tries=3):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for i in range(tries):
        try:
            req = urllib.request.Request(
                RPC, data=body.encode(),
                headers={"Content-Type": "application/json", "User-Agent": "memet/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def decode_price(data_b64, dec_x, dec_y):
    """(active_id, bin_step, price in quote per base) or None if it isn't an LbPair."""
    d = base64.b64decode(data_b64)
    if len(d) < _BIN_STEP + 2:
        return None
    active_id = struct.unpack_from("<i", d, _ACTIVE_ID)[0]
    bin_step = struct.unpack_from("<H", d, _BIN_STEP)[0]
    if not 0 < bin_step <= 10_000:
        return None
    price = (1 + bin_step / 1e4) ** active_id * 10 ** (dec_x - dec_y)
    return active_id, bin_step, price


def fetch_prices(pools):
    """pools: [(address, dec_x, dec_y)] -> {address: (active_id, bin_step, price)}"""
    out = {}
    for i in range(0, len(pools), BATCH):
        chunk = pools[i:i + BATCH]
        res = _rpc("getMultipleAccounts",
                   [[p[0] for p in chunk], {"encoding": "base64"}])["result"]["value"]
        for (addr, dx, dy), v in zip(chunk, res):
            if not v:
                continue
            dec = decode_price(v["data"][0], dx, dy)
            if dec:
                out[addr] = dec
        time.sleep(0.1)
    return out

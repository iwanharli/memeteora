"""Two independent verdicts per pool.

opportunity : how good and how durable the fee flow is  (0-100, higher better)
risk        : how likely the pool hurts you              (0-100, higher worse)
adjusted    : opportunity discounted by risk             (the ranking column)

They are kept separate on purpose. A pool can be genuinely lucrative and
genuinely dangerous at the same time, and collapsing that into one number
hides exactly the thing you need to decide on.
"""
import math, statistics, time

WEIGHTS_VERSION = "v1"
WINDOWS = (("30m", 48), ("1h", 24), ("2h", 12), ("4h", 6), ("12h", 2), ("24h", 1))


def derive(p, base):  # noqa: D401
    """Raw metrics from one Meteora pool record."""
    r = p["fee_tvl_ratio"]
    daily = [(r.get(w) or 0) * mult for w, mult in WINDOWS]     # each window as a daily %
    mean = statistics.fmean(daily)
    tvl = p.get("tvl") or 0
    vol24 = p["volume"].get("24h") or 0
    fee24 = p["fees"].get("24h") or 0
    return dict(
        daily=daily,
        fee_day=daily[-1],
        floor=min(daily),                                   # worst window: the conservative bet
        cv=(statistics.pstdev(daily) / mean) if mean > 0 else 9.9,
        momentum=(daily[1] / daily[-1]) if daily[-1] > 0 else 0.0,
        turnover=(vol24 / tvl) if tvl else 0.0,
        realised_fee_pct=(fee24 / vol24 * 100) if vol24 else 0.0,
        tvl=tvl, vol24=vol24,
        mcap=base.get("market_cap") or 0,
        mcap_tvl=((base.get("market_cap") or 0) / tvl) if tvl else 0.0,
        holders=base.get("holders") or 0,
        verified=bool(base.get("is_verified")),
        freeze_disabled=bool(base.get("freeze_authority_disabled")),
        age_days=(time.time() * 1000 - (p.get("created_at") or 0)) / 8.64e7,
        bin_step=p["pool_config"].get("bin_step") or 0,
        base_fee=p["pool_config"].get("base_fee_pct") or 0,
        # mode 1 pays fees in the quote leg only - in a memecoin pool that is
        # the difference between realised income and more of the same exposure
        quote_only=(p["pool_config"].get("collect_fee_mode") == 1),
    )


# ------------------------------------------------------------------ opportunity
def opportunity(m):
    # earnings floor, log-scaled so 0.3%/day ~26, 1%/day ~40, 5%/day ~62, capped
    earn = min(25 * math.log10(1 + m["floor"] * 30), 45) if m["floor"] > 0 else 0.0
    # steadiness across the six windows: a single hot hour scores near zero here
    persist = 25 * math.exp(-1.2 * m["cv"])
    # heating up vs cooling off, capped so momentum can't run the ranking
    mom = 15 * min(m["momentum"], 2.0) / 2.0
    # depth: a pool you can actually size into
    depth = max(0.0, 10 * min(math.log10(max(m["tvl"], 1) / 10_000) / 2, 1.0))
    return max(0.0, min(100.0, earn + persist + mom + depth))


# ------------------------------------------------------------------ risk
def risk(m, pa=None, lvr=None):
    """pa   = DexScreener price action, or None.
    lvr  = dict from volatility.assess(), or None when we have no price history.

    Volatility risk is priced through LVR, not impermanent loss. IL only
    compares two endpoints and is blind to the path; LVR is the actual
    adverse-selection cost and accumulates trade by trade. On this pool set the
    two disagree in direction often enough that IL was actively misleading -
    STONK-SOL scored -15.8 on IL while its real edge was +1.7."""
    flags, total = [], 0.0

    def add(points, flag):
        nonlocal total
        total += points
        if flag:
            flags.append(flag)

    # --- exit risk: how much token value sits above how little liquidity
    if m["mcap_tvl"] > 100:   add(15, "mcap/tvl>100")
    elif m["mcap_tvl"] > 40:  add(9, "mcap/tvl>40")
    elif m["mcap_tvl"] > 15:  add(4, None)
    if m["holders"] < 300:    add(10, "holders<300")
    elif m["holders"] < 1000: add(6, "holders<1k")
    if not m["verified"]:     add(5, "unverified")
    if not m["freeze_disabled"]: add(15, "FREEZE-AUTHORITY")

    # --- volatility, priced as LVR
    if lvr and lvr.get("lvr_daily_pct") is not None:
        cost = lvr["lvr_daily_pct"]              # % of TVL lost per day
        edge = lvr.get("edge_lvr_pct")
        # the cost itself: 1%/day is already severe for a fee-earning position
        add(min(18.0, cost * 6.0), "high-LVR" if cost > 1.5 else None)
        # and whether the pool actually earns it back
        if edge is not None and edge <= 0:
            add(min(14.0, 4.0 + abs(edge) * 3.0), "fee<LVR")
        bet, turn = lvr.get("breakeven_turnover"), m["turnover"]
        if bet and turn and turn < bet * 0.75:
            add(5.0, "turnover-short")
    else:
        add(10.0, "no-volatility-data")          # unknown risk is still risk

    if pa:
        c24 = pa.get("chg_24h")
        if c24 is not None and c24 < -50: add(10, "collapsing")
        # fees paid in the base leg are exposure dressed up as income
        if not m["quote_only"] and c24 is not None and c24 < -20:
            add(6, "fees-in-falling-base")
        c1 = pa.get("chg_1h")
        if c1 is not None and abs(c1) > 15: add(4, "1h-whipsaw")
        b, s = pa.get("buys_24h") or 0, pa.get("sells_24h") or 0
        if b + s > 200 and (b / (b + s) > 0.85 or s / (b + s) > 0.85):
            add(4, "one-sided-flow")
    else:
        add(8, "no-price-data")

    # --- depth
    if m["tvl"] < 50_000:     add(10, "thin-tvl")
    elif m["tvl"] < 150_000:  add(5, None)

    # --- data integrity / manipulation smell
    if m["cv"] > 1.0:         add(8, "spiky-fees")
    elif m["cv"] > 0.6:       add(4, None)
    if m["turnover"] > 60:    add(10, "turnover>60x")
    elif m["turnover"] > 30:  add(6, "turnover>30x")
    if m["base_fee"] and m["realised_fee_pct"] < m["base_fee"] * 0.5:
        add(5, "fee-mismatch")

    # --- structural fit: how many bins a typical day walks through
    if lvr and lvr.get("sigma_daily") and m["bin_step"]:
        bins_crossed = (lvr["sigma_daily"] * 100) / (m["bin_step"] / 100.0)
        if bins_crossed > 200:   add(8, "binstep-too-small")
        elif bins_crossed > 100: add(4, None)

    # --- youth
    if m["age_days"] < 3:     add(6, "age<3d")
    elif m["age_days"] < 7:   add(3, None)

    # --- fee denomination: quote-only means the income is actually banked
    if m["quote_only"]:
        total = max(0.0, total - 6.0)
        flags.append("quote-only-fees")

    return min(100.0, total), flags


def il_estimate(pct_move, band_pct=20.0):
    """Impermanent loss for a concentrated range, as a positive % of position.

    Still recorded as `il_est_pct` so older rows remain interpretable, but it
    no longer feeds risk: comparing two endpoints ignores everything that
    happened in between, which is exactly where LPs are actually charged."""
    if pct_move is None:
        return None
    r = 1 + pct_move / 100.0
    if r <= 0:
        return 100.0
    full = abs(2 * math.sqrt(r) / (1 + r) - 1) * 100
    return full * max(1.0, 100.0 / band_pct)


def combine(opp, rsk):
    """Risk is a discount, not a subtraction: at risk=100 nothing survives."""
    return opp * (1 - rsk / 100.0)

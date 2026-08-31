"""Realised volatility and the LVR floor it implies.

LVR (loss-versus-rebalancing) is the actual adverse-selection cost of providing
liquidity — what arbitrageurs take because the pool quotes a stale price.
Unlike impermanent loss it accumulates along the whole path, not just between
start and end price.

    Milionis, Moallemi, Roughgarden & Zhang (2022), arXiv:2208.06046
    instantaneous LVR, normalised by pool value = sigma^2 / 8

So a pool is only worth providing to when

    fee_rate * turnover  >  sigma^2 / 8

Both sides scale with concentration, so narrowing a range does not improve this
ratio — it changes out-of-range risk and rebalancing cost, nothing else.
"""
import math

MIN_OBS = 12
DAY = 86400.0
# a gap this long is a collector outage, not a market observation
MAX_GAP_DAYS = 0.5


def realised_sigma(series):
    """series: [(ts, price)] oldest first -> daily sigma as a fraction, or None.

    Scaled by the actual time between observations rather than an assumed
    cadence. Sampling is irregular in practice - the poller starts and stops,
    machines sleep, vendors return sparse candles - and treating a 4-hour gap
    as one 5-minute step inflates sigma by an order of magnitude, while
    assuming a cadence the data does not have deflates it.

    Estimator: sigma_daily = sqrt(mean(r_i^2 / dt_i)) with dt in days. This is
    the standard realised-variance estimator for unevenly spaced observations.
    """
    var_terms = []
    for i in range(1, len(series)):
        t0, p0 = series[i - 1]
        t1, p1 = series[i]
        if not p0 or not p1 or p0 <= 0 or p1 <= 0:
            continue
        dt = (t1 - t0).total_seconds() / DAY
        if dt <= 0 or dt > MAX_GAP_DAYS:
            continue                      # outage, not a price move
        r = math.log(p1 / p0)
        var_terms.append(r * r / dt)
    if len(var_terms) < MIN_OBS:
        return None
    return math.sqrt(sum(var_terms) / len(var_terms))


def lvr_daily_pct(sigma_daily):
    """sigma^2/8, expressed as a % of pool value lost per day."""
    return None if sigma_daily is None else (sigma_daily ** 2) / 8 * 100


def breakeven_turnover(sigma_daily, fee_pct):
    """Daily volume / TVL needed just to cover LVR at this fee tier."""
    lvr = lvr_daily_pct(sigma_daily)
    if lvr is None or not fee_pct:
        return None
    return lvr / fee_pct


def assess(series, fee_day_pct, fee_pct):
    """-> dict of sigma, lvr, edge, breakeven. `edge` is what actually matters."""
    sigma = realised_sigma(series)
    lvr = lvr_daily_pct(sigma)
    return dict(
        sigma_daily=sigma,
        lvr_daily_pct=lvr,
        edge_lvr_pct=(fee_day_pct - lvr) if (lvr is not None and fee_day_pct is not None) else None,
        breakeven_turnover=breakeven_turnover(sigma, fee_pct),
        n_obs=len(series),
    )

"""Deciding what to do with an open position, by comparing what each choice is
worth rather than by running down a list of thresholds.

Three options, and they differ in only two ways: where the capital ends up, and
what it costs to move it.

  HOLD       free. Earns nothing while out of range, and if the price is below
             the range it keeps diverging from simply having held the tokens.
             Right when the price is close enough to come back on its own.

  REBALANCE  two transactions. Redeploys this position, in this pool, centred
             on the current price. Right when the pool is still among the best
             available - the range simply fell behind the price.

  CLOSE      one transaction, and the capital returns to the allocator, which
             will put it in whatever currently ranks highest. Right when this
             pool is no longer worth its slot.

How long the price takes to come back is not a guess: for a diffusion, the
expected first passage over a log-distance d at volatility sigma is (d/sigma)^2
days. A position two daily sigmas out will not be back inside today, and gas is
cheap enough that waiting is the expensive option.
"""
import math

HOLD, CLOSE, REBALANCE = "hold", "close", "rebalance"

MAX_GENERATIONS = 12          # a range that cannot keep up is the wrong range
# below this, drifting back is cheaper than paying to re-centre
WAIT_HOURS = 3.0


def bins_out(active_id, center_bin, n_bins):
    """How many bins beyond the edge of the range the price sits."""
    half = n_bins // 2
    if active_id > center_bin + half:
        return active_id - (center_bin + half)
    if active_id < center_bin - half:
        return (center_bin - half) - active_id
    return 0


def days_to_return(bins_away, bin_step, sigma_daily):
    """Expected first passage back to the range edge, in days."""
    if bins_away <= 0:
        return 0.0
    if not sigma_daily or sigma_daily <= 0:
        return float("inf")
    d = abs(bins_away * math.log(1 + bin_step / 1e4))     # log-price distance
    return (d / sigma_daily) ** 2


def decide(pos, live, market, urgency, reasons):
    """-> (verb, reason)

    pos    : capital, generation, bins_out, bin_step, out_side, value, base_share
    live   : edge_lvr_pct, sigma_daily, blocked, tvl, fee_pct
    market : funded (pools the allocator would fund now), cost (rebalance cost
             breakdown from paper.rebalance_cost), gas_close_usd

    Now that re-centring is priced properly - swap fee and slippage, not just
    gas - the three options can be compared on value again. The earlier attempt
    collapsed into "chase the highest edge" because the cost side was two orders
    of magnitude too small: re-centring a $500 position in a 2% pool costs $4.35,
    not the $0.02 of gas.
    """
    fatal = [r for r in reasons
             if r.startswith(("edge ", "pool-now-blocked", "sigma ", "drawdown "))]
    if fatal:
        return CLOSE, fatal[0]

    edge = live.get("edge_lvr_pct") or 0.0
    if edge <= 0:
        return CLOSE, f"edge {edge:+.2f}%/day: the pool no longer covers its own volatility"

    out = pos.get("bins_out") or 0
    if out == 0:
        return HOLD, ""

    # A position that has run above its range is sitting in the quote token.
    # It earns nothing, but it is not bleeding either, and for a stable-asset
    # book that is a finished trade rather than a broken one.
    if pos.get("out_side") == "above":
        return HOLD, (f"{out} bins above range: converted into the quote token, "
                      "which is an acceptable end state - not re-centred automatically")

    if pos.get("generation", 0) >= MAX_GENERATIONS:
        return CLOSE, (f"re-centred {pos['generation']}x already: this range cannot "
                       "keep up with this pool")

    sigma = live.get("sigma_daily") or 0.0
    t_ret_h = days_to_return(out, pos.get("bin_step") or 1, sigma) * 24.0
    cost = (market.get("cost") or {}).get("total", 0.0)
    cap = pos.get("capital") or 0.0

    # value each option over one day, in dollars
    earning = max(0.0, 1.0 - min(t_ret_h / 24.0, 1.0))
    v_hold = cap * edge / 100.0 * earning - cap * (sigma / 100.0) * (1.0 - earning)
    v_reb = cap * edge / 100.0 - cost

    funded = market.get("funded")
    if funded is not None and pos.get("pool") not in funded:
        return CLOSE, (f"the allocator would not fund this pool today "
                       f"(edge {edge:+.2f}%/day ranks below the cut)")

    if v_reb <= v_hold:
        return HOLD, (f"{out} bins out, ~{t_ret_h:.1f}h from drifting back; "
                      f"re-centring costs ${cost:.2f} and is not worth it yet")
    return REBALANCE, (f"{out} bins out, ~{t_ret_h:.0f}h from returning; re-centring "
                       f"costs ${cost:.2f} against {edge:+.2f}%/day recovered")

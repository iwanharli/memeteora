"""When to leave a position. A different question from which pool to enter.

Every rule names the mechanism by which staying costs money, and each was
derived from the paper portfolio rather than picked as a round number.

The finding that shaped this module: all eleven positions that left their range
left it DOWNWARD, holding 100% of a falling token. That is not symmetric with
leaving upward, and the rules reflect it.

  Out of range BELOW - the position bought the whole way down, so it now holds
  MORE of the falling asset than the hold benchmark does. Every further drop
  widens the gap. Measured: position #1 stood at +2.9% vs hold when it left
  range and at -12.1% seventeen hours later, while earning nothing.

  Out of range ABOVE - the position sold the whole way up and is now entirely
  in the quote token. It earns nothing, but it is not bleeding either; the
  cost is opportunity, not loss. Lower urgency.
"""

# hours out of range before the signal fires
BELOW_SOFT_H = 1.0
BELOW_HARD_H = 3.0
# Out ABOVE is not a fault condition. The position sold its base leg on the way
# up and now sits in the quote token - for a book that prefers ending in stable
# assets that is the intended outcome, not a break to be repaired. It raises no
# signal on its own; only the pool's own condition can.
ABOVE_RAISES_SIGNAL = False

SIGMA_SHOCK = 1.75      # realised vol this many times entry vol
DRAWDOWN_HARD = -8.0    # % vs hold


def side(active_id, center_bin, n_bins):
    """'above', 'below', or None when the price is still inside the range."""
    half = n_bins // 2
    if active_id > center_bin + half:
        return "above"
    if active_id < center_bin - half:
        return "below"
    return None


def evaluate(pos, live):
    """-> (urgency, reasons)

    pos  : entry facts - entry_sigma, entry_edge, out_side, hours_out
    live : current state - sigma_daily, edge_lvr_pct, blocked, block_reasons,
           pnl_pct
    """
    reasons, urgency = [], "none"

    def flag(level, text):
        nonlocal urgency
        reasons.append(text)
        if level == "hard" or urgency == "none":
            urgency = level if level == "hard" else ("soft" if urgency == "none" else urgency)

    out_side, hours_out = pos.get("out_side"), pos.get("hours_out") or 0.0

    # A flank deliberately placed away from the price starts out of range and is
    # supposed to wait there. Only a position that has actually held liquidity at
    # the market price can be said to have fallen out of it.
    if not pos.get("ever_in_range"):
        out_side = None

    if out_side == "below":
        if hours_out >= BELOW_HARD_H:
            flag("hard", f"below range {hours_out:.1f}h: holding more of a falling "
                         "token than never having deployed, and earning nothing")
        elif hours_out >= BELOW_SOFT_H:
            flag("soft", f"below range {hours_out:.1f}h: converted into the base token "
                         "on the way down")
    elif out_side == "above" and ABOVE_RAISES_SIGNAL:
        flag("soft", f"above range {hours_out:.1f}h: fully in quote")

    edge = live.get("edge_lvr_pct")
    if edge is not None and edge < 0:
        flag("hard", f"edge {edge:+.2f}: fees no longer cover the pool's own volatility")

    es, ls = pos.get("entry_sigma"), live.get("sigma_daily")
    if es and ls and ls > es * SIGMA_SHOCK:
        # LVR scales with sigma squared, so this is a fourfold cost increase
        flag("hard", f"sigma {ls / es:.1f}x entry: LVR is now ~{(ls / es) ** 2:.1f}x "
                     "what the position was opened against")

    if live.get("blocked"):
        why = (live.get("block_reasons") or ["red-flagged"])[0].split(":")[0]
        flag("hard", f"pool-now-blocked ({why}): the reason to be here is gone")

    dd = live.get("pnl_pct")
    if dd is not None and dd <= DRAWDOWN_HARD:
        flag("hard", f"drawdown {dd:.1f}% vs hold: the thesis is not working")

    return urgency, reasons

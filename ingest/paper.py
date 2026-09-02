"""Paper positions: run the strategy against real prices, with no capital.

The DLMM mechanic is deterministic, so given the real price path a position's
composition can be reconstructed exactly - no modelling assumptions at all on
the inventory side:

  * a bin below the active price holds only quote
  * a bin above it holds only base
  * as the active bin walks up, each bin it crosses converts base -> quote at
    that bin's price (you sold into the rally); walking down does the reverse

That is where impermanent loss and LVR actually come from, and simulating it
directly means we measure them rather than estimate them.

Fees are the one approximation, and it is stated rather than hidden: we take
the pool's realised fee/TVL rate and scale it by how concentrated our position
is relative to a position spread evenly over the same window. It assumes our
size does not move the pool. See `fee_accrual`.
"""
import json
from decimal import Decimal

# PositionV2 starts at a 70-bin layout and can be extended with
# increasePositionLength / createExtendedEmptyPosition up to 1400 bins. The old
# 69 figure is from the original release and is no longer the constraint - it
# was quietly driving every "the cap always binds, so go as wide as possible"
# conclusion in the sizing logic.
MAX_BINS = 1400
BASE_BINS = 69                # what a position gets without being extended


def bin_price(bin_id, bin_step_bps, dec_base, dec_quote):
    return (1 + bin_step_bps / 1e4) ** bin_id * 10 ** (dec_base - dec_quote)


def weights(shape, n_bins):
    """{offset_from_center: weight}, summing to 1."""
    half = n_bins // 2
    idx = range(-half, half + 1)
    if shape == "spot":
        w = {i: 1.0 for i in idx}
    elif shape == "curve":
        w = {i: float(half + 1 - abs(i)) for i in idx}
    elif shape == "bidask":
        w = {i: float(abs(i) + 1) for i in idx}
    else:
        raise ValueError(f"unknown shape {shape}")
    total = sum(w.values())
    return {i: v / total for i, v in w.items()}


def open_position(capital_usd, center_bin, shape, n_bins, bin_step, dec_b, dec_q,
                  quote_price_usd, market_price):
    """Deposit split the way DLMM actually does it: quote below, base above.

    Tokens are bought at the CURRENT market price, not at each bin's price - a
    bin above the active one receives base tokens acquired now, it does not
    magically get them at that bin's future price. Getting this wrong made an
    entry worth less than the capital deposited.

    Returns (bins, base_total, quote_total), amounts in token units.
    """
    w = weights(shape, n_bins)
    px_usd = market_price * quote_price_usd          # usd per base token
    bins, base_tot, quote_tot = {}, 0.0, 0.0
    for off, weight in w.items():
        bid = center_bin + off
        alloc = capital_usd * weight
        if off < 0:                                   # below price: quote only
            amt_q = alloc / quote_price_usd
            bins[bid] = [0.0, amt_q]
            quote_tot += amt_q
        elif off > 0:                                 # above price: base only
            amt_b = alloc / px_usd if px_usd > 0 else 0.0
            bins[bid] = [amt_b, 0.0]
            base_tot += amt_b
        else:                                         # active bin: half and half
            amt_q = alloc / 2 / quote_price_usd
            amt_b = (alloc / 2) / px_usd if px_usd > 0 else 0.0
            bins[bid] = [amt_b, amt_q]
            base_tot += amt_b
            quote_tot += amt_q
    return bins, base_tot, quote_tot


def walk(bins, prev_active, new_active, bin_step, dec_b, dec_q):
    """Convert the bins the price crossed. This IS the impermanent loss."""
    if prev_active is None or new_active == prev_active:
        return bins, 0
    crossed = 0
    step = 1 if new_active > prev_active else -1
    for bid in range(prev_active + step, new_active + step, step):
        held = bins.get(bid)
        if held is None:
            continue
        px = bin_price(bid, bin_step, dec_b, dec_q)
        if step > 0 and held[0] > 0:          # price rose: sell base into quote
            held[1] += held[0] * px
            held[0] = 0.0
            crossed += 1
        elif step < 0 and held[1] > 0:        # price fell: buy base with quote
            held[0] += held[1] / px if px > 0 else 0.0
            held[1] = 0.0
            crossed += 1
    return bins, crossed


def totals(bins):
    b = sum(v[0] for v in bins.values())
    q = sum(v[1] for v in bins.values())
    return b, q


def fee_accrual(capital_usd, pool_fee_day_pct, shape, n_bins, active_off, hours):
    """The one modelled quantity.

    pool_fee_day_pct is the return of an average dollar in the pool. Our own
    return scales with how much of our capital sits in the active bin relative
    to a position of the same width spread evenly - a flat position is the
    reference, so `spot` earns the pool rate and `curve` earns more while the
    price sits near its centre and less at the edges.
    """
    if active_off is None:
        return 0.0                                   # out of range: nothing
    w = weights(shape, n_bins)
    if active_off not in w:
        return 0.0
    concentration = w[active_off] * n_bins           # 1.0 for spot
    return capital_usd * (pool_fee_day_pct / 100.0) * (hours / 24.0) * concentration


# ---------------------------------------------------------------- claimed fees
# Both feeAmountPerTokenStored and liquiditySupply carry 64 fractional bits, so
# their product carries 128 and the divisor is 2^128. Getting this wrong is not
# subtle - it is off by a factor of 1.8e19 - but it only shows up against a
# real pool, not against a self-consistent test.


def claim_accrual(bins, chain, checkpoints, bin_step, dec_x, dec_y):
    """(fee_x, fee_y, bins_counted) in whole tokens, from the chain's own
    accumulators at our paper size.

    This mirrors what the DLMM program does when it settles a claim:

        claimable = (feeAmountPerTokenStored - checkpoint) * liquidity_share

    We hold no liquidity share on chain, so the delta is scaled by the share
    our paper liquidity would have held in that bin. The denominator includes
    our own deposit - adding liquidity dilutes the bin, and pretending it
    would not is the difference between a counterfactual and a fantasy.

    A bin with no checkpoint yet contributes nothing: the accumulator is
    cumulative since the pool opened, and crediting all of that to a position
    opened yesterday would invent fees that were earned by somebody else.
    """
    fx = fy = Decimal(0)
    counted = 0
    for bid, (base, quote) in bins.items():
        row = chain.get(bid)
        cp = checkpoints.get(bid)
        if not row or not cp:
            continue
        fee_x_now, fee_y_now, liq, amt_x, amt_y = row
        # the pool cannot un-earn a fee; a negative delta means the account was
        # re-initialised, and the next checkpoint resyncs it
        dfx = max(Decimal(0), fee_x_now - cp[0])
        dfy = max(Decimal(0), fee_y_now - cp[1])
        if (dfx == 0 and dfy == 0) or liq <= 0:
            continue

        # the module's own bin_price, in float: this only forms a ratio, and
        # the exactness that matters is in the integer accumulator delta below
        px = Decimal(str(bin_price(bid, bin_step, dec_x, dec_y)))
        ours = Decimal(str(base)) * px + Decimal(str(quote))
        theirs = (amt_x / Decimal(10) ** dec_x) * px + amt_y / Decimal(10) ** dec_y
        if ours <= 0:
            continue
        share = ours / (theirs + ours)

        # The program settles this as
        #     mulShr(share >> 64, delta, 64)
        # - the share is shifted down before the multiply and the product is
        # shifted again, so the divisor is 2^128, not 2^64. Integer floor
        # division at both steps, because that is what the on-chain math does
        # and rounding it differently drifts over thousands of marks.
        ours_q64 = int(liq * share)
        fx += Decimal((ours_q64 >> 64) * int(dfx) >> 64)
        fy += Decimal((ours_q64 >> 64) * int(dfy) >> 64)
        counted += 1
    return (float(fx / Decimal(10) ** dec_x),
            float(fy / Decimal(10) ** dec_y),
            counted)


def value_usd(bins, price_quote_per_base, quote_price_usd):
    b, q = totals(bins)
    return (b * price_quote_per_base + q) * quote_price_usd


def dumps(bins):
    return json.dumps({str(k): v for k, v in bins.items()})


def loads(raw):
    d = raw if isinstance(raw, dict) else json.loads(raw)
    return {int(k): list(v) for k, v in d.items()}


# ---------------------------------------------------------------- costs
# Measured against mainnet, not assumed: getMinimumBalanceForRentExemption
# for the account sizes the DLMM program uses.
POSITION_RENT_SOL = 0.057350       # PositionV2, 8112 bytes - refunded on close
BIN_ARRAY_RENT_SOL = 0.071437      # only if you are the first into that range
BASE_TX_SOL = 0.000005             # one signature
DEFAULT_PRIORITY_SOL = 0.0001      # unhurried LP transaction

TX_OPEN = 1                        # create position and deposit
TX_REBALANCE = 2                   # withdraw and close, then reopen
TX_CLAIM = 1


def tx_cost_sol(n_tx, priority_sol=DEFAULT_PRIORITY_SOL):
    return n_tx * (BASE_TX_SOL + priority_sol)


def costs_usd(tx_count, sol_price, n_positions=1, priority_sol=DEFAULT_PRIORITY_SOL):
    """(gas_usd, rent_usd). Rent is locked, not spent - reported separately so
    a refundable deposit is never mistaken for a loss."""
    gas = tx_cost_sol(tx_count, priority_sol) * sol_price
    rent = n_positions * POSITION_RENT_SOL * sol_price
    return gas, rent


def rebalance_cost(value_usd, base_share, target_share, pool_fee_pct, tvl_usd,
                   sol_price, n_tx=None):
    """What it actually costs to re-centre a position.

    Gas is the smallest term. Re-centring converts inventory back toward the
    target composition, and that swap pays the pool's own fee and moves the
    price against itself. The playbook states the threshold as
    swap fee + slippage + transaction cost + inventory risk + opportunity cost;
    modelling only gas made every rebalance look free, which is why an
    expected-value comparison built on it collapsed into "chase the highest
    edge".

    Slippage uses a linear price-impact approximation, swap/(2*TVL): fine for
    swaps that are small against the pool, deliberately pessimistic when they
    are not - which is exactly when the caution is warranted.
    """
    n_tx = TX_REBALANCE if n_tx is None else n_tx
    gas = tx_cost_sol(n_tx) * sol_price
    if value_usd <= 0 or base_share is None:
        return dict(gas=gas, swap_fee=0.0, slippage=0.0, total=gas, swapped=0.0)

    swapped = abs(base_share - target_share) * value_usd
    swap_fee = swapped * (pool_fee_pct or 0.0) / 100.0
    slippage = (swapped * swapped / (2 * tvl_usd)) if tvl_usd and tvl_usd > 0 else 0.0
    return dict(gas=gas, swap_fee=swap_fee, slippage=slippage,
                swapped=swapped, total=gas + swap_fee + slippage)

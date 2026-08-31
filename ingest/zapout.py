"""Which token a position should be withdrawn into.

Closing a DLMM position returns whatever the range happens to hold. For a
memecoin that is usually the memecoin - the position converted into it on the
way down, which is exactly the case where you least want to keep holding it.
Zap Out swaps the proceeds on the way out instead.

The output token matters more than it looks. Withdrawing CATE into SOL cuts
daily volatility from ~26% to ~4%, but SOL is not a stable asset and can still
fall 10% in a day. Measured on a $21 withdrawal:

    CATE -> SOL    0.455% price impact, 1 hop
    CATE -> USDC   0.466% price impact, 2 hops

Eleven hundredths of a percentage point - about $0.002 - to land in a stable
asset instead of a volatile one, in a single transaction rather than two. For a
book whose stated first priority is capital stability, that is not a trade-off.
"""

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"
STABLE = {USDC, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDC, USDT

# Above this daily volatility the base token is treated as speculative and its
# proceeds are swapped out rather than held. SOL and ETH sit far below it.
SPECULATIVE_SIGMA = 0.10


def output_mint(base_mint, quote_mint, sleeve, base_sigma, prefer=USDC):
    """-> (mint to receive, reason). None means take the tokens as they come."""
    if base_mint in STABLE:
        return None, "position already returns a stable asset"

    speculative = (sleeve == "satellite") or (base_sigma or 0) > SPECULATIVE_SIGMA
    if not speculative:
        return None, f"base token is not speculative (sigma {(base_sigma or 0) * 100:.1f}%/day)"

    if quote_mint in STABLE:
        # the quote leg is already stable; sweep the base leg into it
        return quote_mint, "swap the speculative leg into the pool's own stable quote"
    return prefer, ("swap out to USDC: the quote leg is SOL, which is calmer than "
                    "the base token but still not stable")


def cost(swap_usd, price_impact_pct, jupiter_fee_pct=0.0):
    """Zap Out is a swap, so it costs impact plus whatever the route charges.
    Returned separately from the close so it is never mistaken for free."""
    impact = swap_usd * (price_impact_pct or 0.0) / 100.0
    fee = swap_usd * jupiter_fee_pct / 100.0
    return dict(swap_usd=swap_usd, impact=impact, fee=fee, total=impact + fee)

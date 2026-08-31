"""Red flags: reasons to refuse a pool outright.

Different from the risk score on purpose. The score ranks pools you might
deploy into; a red flag says do not deploy at all. Scores are continuous and
tolerate being a little wrong. Red flags must be conservative and specific -
each one names the mechanism by which you lose money.

Two families:

  HARD        the token or pool can hurt you in ways no yield offsets.
              Mostly on-chain facts, not market conditions. These do not
              expire on their own.

  STRUCTURAL  the economics do not work right now. These come back when
              conditions change, so they are re-evaluated every ingest.
"""
from mintcheck import HOSTILE, hostile_extensions

# a pool must clear its breakeven by this much before we stop calling it broken
TURNOVER_MARGIN = 0.75
SIGMA_ABSURD = 1.5          # 150%/day: no fee tier covers this
MCAP_TVL_TRAP = 150.0       # $150 of token value per $1 of exit liquidity
# ...but only where this pool really is the exit. A verified, widely held token
# trades on many venues, so its mcap dwarfing one pool says nothing about
# whether you can get out. Applying it blindly blocked SOL-USDC at 13,246x -
# the best risk-adjusted pool in the whole set.
MANY_HOLDERS = 100_000


def evaluate(pool, base_token, score):
    """-> (blocked: bool, reasons: [str])

    pool        : dict-ish with bin_step, collect_fee_mode, is_blacklisted, created_at
    base_token  : token row incl. on-chain mint facts
    score       : latest metrics (fee_day, edge_lvr, turnover, breakeven, sigma...)
    """
    hard, structural = [], []

    # ---- HARD: on-chain token configuration
    if base_token.get("freeze_auth_active"):
        hard.append("freeze-authority: the mint can freeze your position in place")
    fee_bps = base_token.get("transfer_fee_bps")
    if fee_bps:
        hard.append(f"transfer-fee-{fee_bps}bps: {HOSTILE['TransferFeeConfig']}")
    for ext in hostile_extensions(base_token.get("extensions")):
        if ext == "TransferFeeConfig":
            continue                                  # already reported with its rate
        hard.append(f"{ext.lower()}: {HOSTILE[ext]}")
    # mint authority is normal for bridged assets and LSTs; it is only a flag
    # when nobody has verified the token
    if base_token.get("mint_auth_active") and not base_token.get("is_verified"):
        hard.append("mint-authority-unverified: supply can be inflated at will")

    # ---- HARD: pool level
    if pool.get("is_blacklisted"):
        hard.append("meteora-blacklist: flagged by the venue itself")

    # ---- STRUCTURAL: economics
    edge = score.get("edge_lvr_pct")
    fee = score.get("fee_day_pct")
    turn = score.get("turnover")
    brk = score.get("breakeven_turnover")
    sigma = score.get("sigma_daily")

    if edge is not None and edge < 0:
        structural.append(f"fee-below-lvr: earns {fee:.2f}%/day against "
                          f"{score.get('lvr_daily_pct', 0):.2f}%/day of adverse selection")
    if turn is not None and brk and turn < brk * TURNOVER_MARGIN:
        structural.append(f"turnover-{turn:.1f}x-vs-{brk:.1f}x-needed: "
                          "not enough volume to pay for the volatility")
    if sigma is not None and sigma > SIGMA_ABSURD:
        structural.append(f"sigma-{sigma * 100:.0f}pct-daily: no fee tier covers this")
    thin_venue = not (base_token.get("is_verified")
                      and (base_token.get("holders") or 0) >= MANY_HOLDERS)
    if thin_venue and score.get("mcap_tvl") and score["mcap_tvl"] > MCAP_TVL_TRAP:
        structural.append(f"mcap/tvl-{score['mcap_tvl']:.0f}x: this pool is the only "
                          "real exit and it is too narrow to leave through")

    reasons = hard + structural
    return bool(reasons), reasons


def is_hard(reason):
    """Hard flags are facts about the token; structural ones can lift again."""
    return not reason.split(":")[0].startswith(
        ("fee-below-lvr", "turnover-", "sigma-", "mcap/tvl-"))

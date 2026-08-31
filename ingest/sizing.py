"""How much capital goes where, out of a fixed budget.

Equal weights ignore everything the engine knows. The sizing here follows the
Kelly criterion, which for a bet with expected return mu and variance sigma^2
allocates a fraction

    f* = mu / sigma^2

and that is exactly the shape of an LP position: edge is the daily expected
return, sigma the daily volatility. A pool with half the volatility and the
same edge deserves four times the capital, not the same.

Three constraints bind afterwards, and they matter more than the weights:

  RESERVE      every position locks 0.0574 SOL of rent, refundable but idle,
               plus gas for future rebalances. That is not deployable capital
               and pretending otherwise overstates the book.

  FLOOR        rent is a fixed cost per position, so a small position is a bad
               position: $6 of rent on $9 of capital is 68% overhead. Below the
               floor a position is not sized down, it is dropped, and its
               capital goes to the ones that clear it.

  TOKEN CAP    no token may exceed a share of the book. A token usually has
               several pools, so this is checked on the token, not the pool.
"""

import os

POSITION_RENT_SOL = 0.057350
MAX_RENT_SHARE = float(os.environ.get("MEMET_MAX_RENT_SHARE", 0.08))
MAX_TOKEN_WEIGHT = 0.15
# A token cap alone is not enough: when a sleeve holds only two or three
# distinct tokens the cap relaxes to 1/n and a single position can take half
# the sleeve. This bounds any one position regardless of how few tokens are
# available - ETH-SOL took 50% of core before it existed.
MAX_POSITION_WEIGHT = 0.35
# A month of rebalancing at observed rates. Overridable because it, and the
# position floor, are sized for a real book - on a small test budget they would
# consume the whole thing before a single position could be opened.
GAS_BUFFER_USD = float(os.environ.get("MEMET_GAS_BUFFER", 20.0))

# Cash is held 70% USDC / 30% SOL. Position rent is NOT cash - it is a deposit
# locked in the position account that comes back on close - so it sits outside
# this split, even though it is denominated in SOL.
#
# The SOL leg is not a preference, it is an obligation: transaction fees can
# only be paid in SOL. So the cash pile has to be large enough that its 30% SOL
# share still covers the gas buffer, which sets a floor on how much of the
# budget stays uninvested.
CASH_SOL_SHARE = 0.30
CASH_USDC_SHARE = 0.70
# Kelly (f* = edge/sigma^2) maximises long-run growth and is, by construction,
# risk-averse: halving volatility quadruples the allocation. That is why it
# filled the book with blue chips earning 0.3%/day. The exponent on sigma is the
# knob - 2 is Kelly, 1 is Sharpe-like, 0 is chasing raw yield - so a profile is
# just a choice of exponent, edge floor and how much Kelly to take.
PROFILES = {
    # name:        (sigma exponent, fraction, min edge %/day, max risk score)
    "conservative": (2.0, 0.20, 0.50, 35.0),
    "semi":         (1.3, 0.35, 1.00, 45.0),
    "aggressive":   (1.0, 0.50, 2.00, 60.0),
    # kelly-weighted, no extra edge floor beyond repaying the rent
    "core":         (2.0, 0.20, 0.00, 30.0),
}
DEFAULT_PROFILE = "semi"

# A barbell: most of the book in pools that should not surprise you, a minority
# in ones that might pay for the rest. The two sleeves are sized and judged
# separately - averaging them produces a portfolio that is neither.
SLEEVES = {
    # name:      (share of budget, profile, description)
    "core":      (0.70, "core",      "verified, widely held, low volatility"),
    "satellite": (0.30, "aggressive", "memecoins - small stake, fast upside"),
}

# The posture sets how much of the book is allowed to be speculative at all.
# `stability` is the default because the operating playbook states it as the
# primary preference: capital stability and stable assets over the highest APR,
# and no memecoin as a core position. The others are one flag away.
POSTURES = {
    # name:        (core share, satellite profile, max satellite positions)
    "stability":   (0.85, "conservative", 2),
    "balanced":    (0.70, "aggressive",   4),
    "growth":      (0.55, "aggressive",   6),
}
DEFAULT_POSTURE = "stability"


def sleeves_for(posture=DEFAULT_POSTURE):
    core_share, sat_profile, _n = POSTURES.get(posture, POSTURES[DEFAULT_POSTURE])
    return {
        "core": (core_share, "core", "verified, widely held, low volatility"),
        "satellite": (1.0 - core_share, sat_profile,
                      "speculative - small stake, never core"),
    }

# `core` needs its own profile: the conservative one floors edge at 0.50%/day,
# which excludes almost every low-volatility pool. The rent floor (0.27%) is the
# real constraint there, so core takes it as-is.
# 10%/day still means ~190% annualised - but it is where the data separates
# SOL and ETH pairs (weighted sigma 2.9%) from everything else. Loosening it to
# 20% pulled ANSEM in at 13%/day, which is not a core holding by any reading.
CORE_MAX_SIGMA = 0.10
CORE_MIN_HOLDERS = 50_000

KELLY_FRACTION = 0.25          # full Kelly assumes the edge estimate is exact

# Kelly divides by sigma squared, so it hands enormous weight to any pool whose
# volatility looks small. Three guards, each for a failure seen in the data:
MIN_OBS = 60                   # GOLD-USDC showed sigma 0.95% off 23 price points
SIGMA_FLOOR = 0.05             # treat anything calmer as 5%/day when sizing
RENT_PAYBACK_DAYS = 30         # a position must earn back its own rent this fast


def rent_usd(sol_price):
    return POSITION_RENT_SOL * sol_price


def min_position(sol_price):
    """Below this, the fixed rent eats too much of the position to be worth it."""
    return rent_usd(sol_price) / MAX_RENT_SHARE


def plan(budget, candidates, sol_price, max_positions=12, profile=DEFAULT_PROFILE,
         reserve_cash=True):
    """candidates: [{pool, name, mint, edge, sigma, risk}] -> (allocations, meta)

    Returns allocations as [{...candidate, usd}] and a meta dict explaining
    where the budget went, so the split is auditable rather than a black box.
    """
    sig_exp, fraction, profile_min_edge, _max_risk = PROFILES.get(
        profile, PROFILES[DEFAULT_PROFILE])
    rent = rent_usd(sol_price)
    floor = min_position(sol_price)

    # rent is a fixed cost, so the edge has to be big enough to repay it in
    # reasonable time - at an 8% rent share, 0.04%/day needs 200 days
    # whichever binds harder: repaying the rent, or the profile's own appetite
    min_edge = max(MAX_RENT_SHARE * 100.0 / RENT_PAYBACK_DAYS, profile_min_edge)

    usable, rejected = [], {}
    for c in candidates:
        if not c.get("edge") or c["edge"] <= 0 or not c.get("sigma") or c["sigma"] <= 0:
            rejected[c.get("name", "?")] = "no edge or sigma"
        elif (c.get("n_obs") or 0) < MIN_OBS:
            rejected[c["name"]] = f"only {c.get('n_obs', 0)} price points"
        elif c["edge"] < min_edge:
            rejected[c["name"]] = (f"edge {c['edge']:.2f}%/day needs "
                                   f"{MAX_RENT_SHARE * 100 / c['edge']:.0f} days to repay rent")
        else:
            usable.append(c)
    if not usable:
        return [], dict(reason="nothing clears the edge and data-quality floors",
                        rejected=rejected)

    # sigma floored so a quiet pool cannot dominate through a noisy estimate
    for c in usable:
        sig = max(c["sigma"], SIGMA_FLOOR)
        c["kelly"] = (c["edge"] / 100.0) / (sig ** sig_exp) * fraction
    usable.sort(key=lambda c: -c["kelly"])

    # Position count and allocation have to be solved together. Choosing the
    # count first, capping, then dropping whatever falls below the floor leaves
    # the survivors renormalised back to near-equal weights - which throws away
    # the Kelly ranking the whole exercise exists to apply. So: try the largest
    # count the budget can carry, allocate, and shrink until nothing is dropped.
    rejected_floor = []
    max_n = min(max_positions, len(usable))
    # cash must be big enough that 30% of it still covers the gas buffer.
    # plan_book holds it once for the whole book, so sleeves opt out - reserving
    # it per sleeve would set the same money aside twice.
    cash = (GAS_BUFFER_USD / CASH_SOL_SHARE) if reserve_cash else 0.0
    for n in range(max_n, 0, -1):
        reserve = n * rent + cash
        deployable = budget - reserve
        if deployable < n * floor:
            continue

        chosen = usable[:n]
        by_mint = {}
        for c in chosen:
            by_mint.setdefault(c["mint"], []).append(c["pool"])
        # a cap can never bind tighter than 1/n; weights must still sum to one
        cap = max(MAX_TOKEN_WEIGHT, 1.0 / max(len(by_mint), 1))

        total = sum(c["kelly"] for c in chosen) or 1.0
        weights = {c["pool"]: c["kelly"] / total for c in chosen}

        # Both ceilings have to be enforced together. Running them in sequence
        # let the second undo the first: the token cap redistributed weight back
        # into ETH-SOL right after the position cap had trimmed it, and ETH ended
        # up with half the core sleeve. Neither cap can bind tighter than 1/n of
        # its own kind, and with only two tokens available the two can genuinely
        # conflict - in which case the token cap wins and the breach is reported
        # rather than hidden.
        pos_cap = max(MAX_POSITION_WEIGHT, 1.0 / n)
        cap = max(MAX_TOKEN_WEIGHT, 1.0 / max(len(by_mint), 1))

        def clip(groups, ceiling):
            over = {k: g for k, g in groups.items()
                    if sum(weights[x] for x in g) > ceiling + 1e-9}
            if not over:
                return False
            freed = 0.0
            for g in over.values():
                share = sum(weights[x] for x in g)
                excess = share - ceiling
                for x in g:
                    weights[x] -= excess * (weights[x] / share)
                freed += excess
            room = [x for k, g in groups.items() if k not in over for x in g]
            base = sum(weights[x] for x in room)
            if not room or base <= 0:
                return False
            for x in room:
                weights[x] += freed * (weights[x] / base)
            return True

        singles = {p: [p] for p in weights}
        for _ in range(60):
            a_ = clip(by_mint, cap)          # token ceiling
            b_ = clip(singles, pos_cap)      # position ceiling
            if not a_ and not b_:
                break
        breaches = [p for p, w in weights.items() if w > pos_cap + 1e-6]

        alloc = [dict(c, usd=deployable * weights[c["pool"]]) for c in chosen]
        below = [a for a in alloc if a["usd"] < floor]
        if below:
            rejected_floor = [a["name"] for a in below]
            continue                       # too many positions for this budget

        allocations, dropped = alloc, rejected_floor
        break
    else:
        return [], dict(reason=f"budget {budget:.0f} cannot carry a position at the "
                               f"{floor:.0f} floor plus {rent:.0f} rent",
                        rejected=rejected)

    return allocations, dict(
        budget=budget, reserve=reserve, rent_total=n * rent,
        gas_buffer=GAS_BUFFER_USD, deployable=deployable,
        cash=cash, cash_sol=cash * CASH_SOL_SHARE,
        cash_usdc=cash * CASH_USDC_SHARE,
        floor=floor, positions=len(allocations), dropped=dropped,
        min_edge=min_edge, rejected=rejected, token_cap=cap,
        position_cap=pos_cap, position_cap_breached=breaches,
        profile=profile, sigma_exponent=sig_exp, fraction=fraction)


def classify(c):
    """'core' or 'satellite', on facts rather than on the token's reputation.

    Core means the position should not surprise you: a verified mint, enough
    holders that one wallet cannot empty the pool, and volatility low enough
    that LVR stays small. Everything else that clears the red flags is a
    satellite - worth a small stake, never a large one.
    """
    if (c.get("verified")
            and (c.get("holders") or 0) >= CORE_MIN_HOLDERS
            and (c.get("sigma") or 1.0) <= CORE_MAX_SIGMA):
        return "core"
    return "satellite"


def plan_book(budget, candidates, sol_price, max_positions=12, sleeves=None,
              posture=DEFAULT_POSTURE):
    """Allocate across sleeves. Each is planned on its own share of the budget
    with its own profile, then merged.

    Capital a sleeve cannot place stays as cash rather than spilling into the
    other one: spilling would quietly turn a 70/30 book into whatever the
    market happened to offer that day, which is the opposite of a risk budget.
    """
    sleeves = sleeves or sleeves_for(posture)
    # one cash pile for the book, not one per sleeve
    cash = GAS_BUFFER_USD / CASH_SOL_SHARE
    investable = max(0.0, budget - cash)
    buckets = {}
    for c in candidates:
        buckets.setdefault(classify(c), []).append(c)

    out, meta = [], {}
    for name, (share, profile, _desc) in sleeves.items():
        sub_budget = investable * share
        cands = buckets.get(name, [])
        n_max = max(1, round(max_positions * share))
        allocs, m = plan(sub_budget, cands, sol_price, n_max, profile=profile,
                         reserve_cash=False)
        for a in allocs:
            a["sleeve"] = name
        out.extend(allocs)
        placed = sum(a["usd"] for a in allocs)
        meta[name] = dict(
            m, share=share, profile=profile, budget=sub_budget, posture=posture,
            placed=placed, candidates=len(cands),
            idle=sub_budget - placed - m.get("reserve", 0.0))

    rent_total = sum(m.get("rent_total", 0.0) for m in meta.values())
    placed_total = sum(a["usd"] for a in out)
    meta["book"] = dict(
        budget=budget, deployed=placed_total, rent_locked=rent_total,
        cash=cash, cash_sol=cash * CASH_SOL_SHARE,
        cash_usdc=cash * CASH_USDC_SHARE,
        idle=budget - placed_total - rent_total - cash)
    return out, meta


def geometry(sigma_daily, bin_step_bps, sleeve="core", edge=None,
             horizon_days=1.0, max_bins=1400):
    """-> (bins, shape, reason). The two decisions are one decision.

    Width comes first, from how often the sleeve is willing to fall out of
    range. Shape then follows from the coverage that width produces: a range
    covering two sigmas should concentrate at its centre, one covering half a
    sigma will be crossed end to end and should weight the edges instead.
    """
    target = COVERAGE_TARGET.get(sleeve, 1.0)
    bins = bins_for_range(sigma_daily, bin_step_bps, horizon_days, target, max_bins)
    shape, why = choose_shape(sigma_daily, bin_step_bps, bins, sleeve, edge,
                              horizon_days)
    cov = range_coverage(sigma_daily, bin_step_bps, bins, horizon_days)
    capped = " (capped at the 1400-bin limit)" if bins >= max_bins else ""
    return bins, shape, (f"{bins} bins for {cov:.2f}x sigma{capped}; {why}")


def bins_for_range(sigma_daily, bin_step_bps, horizon_days=1.0, sigmas=1.0,
                   max_bins=1400):
    """How many bins a position needs to cover `sigmas` of drift over `horizon`.

    With the 69-bin cap lifted, width is no longer chosen by picking a bin step
    whose 69 bins happen to reach far enough - it is chosen directly, and the
    bin step then only decides how finely that width is subdivided.

    Half-width in log-price is sigma*sqrt(T)*sigmas, and one bin spans
    ln(1 + step/1e4), so the position needs twice that many bins plus the
    active one.
    """
    import math
    if not sigma_daily or sigma_daily <= 0 or not bin_step_bps:
        return 69
    half_log = sigma_daily * math.sqrt(horizon_days) * sigmas
    per_bin = math.log(1 + bin_step_bps / 1e4)
    half = max(1, math.ceil(half_log / per_bin))
    n = 2 * half + 1
    return int(min(n, max_bins))


# ---------------------------------------------------------------- shape
# What the observed data says about the three distributions:
#
#   Curve concentrates near the active price. It earned the most fees of the
#   three in the live test - 4.16 against spot's 3.36 and bid-ask's 2.58 on the
#   same pool, same entry - and it also suffered the largest inventory loss,
#   -16.22 against -14.53. Concentration amplifies fee capture and inventory
#   damage together; it is leverage on the position, not free efficiency.
#
#   So the choice is not about which shape is better. It is about whether the
#   price is likely to stay where the concentration is, and that is measurable:
#   how many daily sigmas the range covers.
COVERAGE_CONCENTRATE = 1.5     # range wide enough that price should stay central
COVERAGE_SPREAD = 0.7          # below this the price traverses the whole range

# How wide a range each sleeve aims for, in daily sigmas. This is an operational
# choice - it decides how often the position falls out and has to be paid for
# again - and the shape then follows from the geometry it produces. Core buys
# resilience; satellite accepts more maintenance for tighter capital.
COVERAGE_TARGET = {"core": 2.0, "satellite": 1.0}


def range_coverage(sigma_daily, bin_step_bps, bins, horizon_days=1.0):
    """Half the range width, measured in daily standard deviations."""
    import math
    if not sigma_daily or sigma_daily <= 0 or not bin_step_bps:
        return 0.0
    half_log = (bins // 2) * math.log(1 + bin_step_bps / 1e4)
    return half_log / (sigma_daily * math.sqrt(horizon_days))


def choose_shape(sigma_daily, bin_step_bps, bins, sleeve="core", edge=None,
                 horizon_days=1.0):
    """-> (shape, reason). Chosen from coverage, not from preference."""
    cov = range_coverage(sigma_daily, bin_step_bps, bins, horizon_days)

    # A thin edge does not pay for concentration: curve's extra fee capture is
    # a fraction of an already small number, while its extra inventory loss is
    # not scaled down at all.
    if edge is not None and edge < 1.0 and cov < COVERAGE_CONCENTRATE:
        return "spot", (f"edge {edge:+.2f}%/day is too thin to pay for "
                        f"concentration at {cov:.2f}x sigma coverage")

    if cov >= COVERAGE_CONCENTRATE:
        return "curve", (f"range covers {cov:.2f}x daily sigma - the price should "
                         "stay near the centre, where curve puts the liquidity")
    if cov >= COVERAGE_SPREAD:
        return "spot", (f"range covers {cov:.2f}x daily sigma - too narrow to "
                        "concentrate, wide enough to sit evenly")
    return "bidask", (f"range covers only {cov:.2f}x daily sigma - the price will "
                      "cross the whole of it, so weight the edges it converts at")

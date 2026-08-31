#!/usr/bin/env python3
"""memet - Meteora DLMM pool screener backed by Postgres (db_memet).

  python3 ingest/main.py manage          act on the signals: close, rebalance, add
  python3 ingest/main.py exits           which open positions should be closed
  python3 ingest/main.py redflags        re-evaluate which pools are refused
  python3 ingest/main.py blocked         list refused pools and why
  python3 ingest/main.py paper open <pool>   open a simulated position
  python3 ingest/main.py paper mark          mark every open position to market
  python3 ingest/main.py paper report        PnL vs simply holding
  python3 ingest/main.py worker         long-running scheduler, logs to stdout (for pm2)
  python3 ingest/main.py poll           exact on-chain price for every pool (1 RPC call)
  python3 ingest/main.py ingest         pull pools, snapshot + score
  python3 ingest/main.py backfill       seed hourly candles from vendors
  python3 ingest/main.py volatility     recompute sigma / LVR / edge
  python3 ingest/main.py top            show the latest ranking
  python3 ingest/main.py history <pool> one pool across snapshots

Ranking column is `adjusted` = opportunity discounted by risk.
Set $MEMET_DSN to point at another database.
"""
import argparse, sys, time
from datetime import datetime, timezone

import actions, db, exits, gates, mintcheck, ohlcv, onchain, paper, redflags, scoring, sizing, sources, timeutil, volatility, worker, zapout


def cmd_ingest(a):
    now = datetime.now(timezone.utc)
    now_ms = time.time() * 1000
    cfg = dict(gates.DEFAULTS,
               min_tvl=a.min_tvl, min_volume=a.min_volume,
               min_holders=a.min_holders, min_age_hours=a.min_age_hours)

    pools = sources.fetch_pools(pages=a.pages)
    kept, rejects = [], {}
    for p in pools:
        why, base, quote = gates.check(p, cfg, now_ms)
        if why:
            rejects[why] = rejects.get(why, 0) + 1
            continue
        kept.append((p, base, quote))

    # price action for survivors only - 30 pools per DexScreener call
    pa = sources.fetch_price_action([p["address"] for p, _, _ in kept])

    with db.session() as (conn, cur):
        return _persist(cur, now, kept, pa, a, pools, rejects)


def _lvr_for(cur, addrs, hours, fee_map):
    """sigma/LVR per pool, computed before scoring so risk can price volatility
    instead of guessing at it from a single 24h price change."""
    own, vend = db.series_bulk(cur, addrs, hours)
    out = {}
    for addr in addrs:
        series = own.get(addr, [])
        src = "onchain"
        if len(series) <= volatility.MIN_OBS:
            series, src = vend.get(addr, []), "vendor"
        if len(series) <= volatility.MIN_OBS:
            continue
        fee_day, fee_pct = fee_map.get(addr, (None, None))
        r = volatility.assess(series, fee_day, fee_pct)
        if r["sigma_daily"] is None:
            continue
        r["source"] = src
        out[addr] = r
    return out


def _persist(cur, now, kept, pa, a, pools, rejects):
    snap_rows, pa_rows, score_rows = [], [], []
    metrics = {p["address"]: scoring.derive(p, base) for p, base, _ in kept}
    lvr_map = _lvr_for(
        cur, [p["address"] for p, _, _ in kept], 72,
        {addr: (m["fee_day"], m["base_fee"]) for addr, m in metrics.items()})

    for p, base, quote in kept:
        db.upsert_token(cur, p["token_x"])
        db.upsert_token(cur, p["token_y"])
        created = (datetime.fromtimestamp(p["created_at"] / 1000, timezone.utc)
                   if p.get("created_at") else None)
        db.upsert_pool(cur, p, base["address"], quote, created)
        snap_rows.append(db.snapshot_row(now, p, base))

        d = pa.get(p["address"])
        if d:
            pa_rows.append((now, p["address"], d["price_usd"], d["chg_5m"], d["chg_1h"],
                            d["chg_6h"], d["chg_24h"], d["buys_24h"], d["sells_24h"],
                            d["liquidity_usd"], d["fdv"]))

        m = metrics[p["address"]]
        lv = lvr_map.get(p["address"])
        opp = scoring.opportunity(m)
        rsk, flags = scoring.risk(m, d, lv)
        il = scoring.il_estimate((d or {}).get("chg_24h"), a.band)
        score_rows.append((now, p["address"], scoring.WEIGHTS_VERSION,
                           opp, rsk, scoring.combine(opp, rsk),
                           m["fee_day"], m["floor"], m["cv"], m["momentum"],
                           m["turnover"], il, (m["fee_day"] - il) if il is not None else None,
                           flags,
                           (lv or {}).get("sigma_daily"), (lv or {}).get("lvr_daily_pct"),
                           (lv or {}).get("edge_lvr_pct"), (lv or {}).get("breakeven_turnover"),
                           (lv or {}).get("source")))

    db.insert_snapshots(cur, snap_rows)
    db.insert_price_action(cur, pa_rows)
    db.insert_scores(cur, score_rows)

    rej = ", ".join(f"{k}={v}" for k, v in sorted(rejects.items(), key=lambda x: -x[1]))
    return (f"scanned {len(pools)} -> kept {len(kept)} | price data for {len(pa_rows)}"
            f" | rejected: {rej}")


def cmd_poll(a):
    """Exact price for every tracked pool in one getMultipleAccounts call.
    Cheap enough to run far more often than the metrics ingest."""
    now = datetime.now(timezone.utc)
    with db.session() as (conn, cur):
        pools = db.pools_for_pricing(cur)
        if not pools:
            return "no pools yet - run `ingest` first"
        got = onchain.fetch_prices(pools)
        db.insert_prices(cur, [(addr, now, aid, price, "onchain")
                               for addr, (aid, _bs, price) in got.items()])
    return f"priced {len(got)}/{len(pools)} pools on-chain"


def cmd_backfill(a):
    """Vendor candles, only for pools we have no recent history for.
    Our own `poll` series supersedes this as soon as it is long enough."""
    by_source, missing = {}, 0
    with db.session() as (conn, cur):
        targets = db.pools_missing_ohlcv(cur, a.hours)
        if a.limit:
            targets = targets[: a.limit]
        for pool in targets:
            rows, src = ohlcv.fetch(pool, a.hours)
            if not rows:
                missing += 1
                continue
            by_source[src] = by_source.get(src, 0) + 1
            db.insert_ohlcv(cur, [(pool, ts, o, h, l, c, v, src)
                                  for ts, o, h, l, c, v in rows])
            conn.commit()          # keep partial progress if a later vendor call dies
    got = sum(by_source.values())
    return (f"covered {got}/{len(targets)} "
            f"({', '.join(f'{k}={v}' for k, v in by_source.items()) or 'none'}), "
            f"{missing} unavailable from any vendor")


def cmd_volatility(a):
    """Compute sigma, LVR and the LVR edge for the latest score row of each pool.
    Prefers our own on-chain series; falls back to vendor candles."""
    with db.session() as (conn, cur):
        return _volatility(cur, a)


def _volatility(cur, a):
    cur.execute("""SELECT pool, ts, fee_day_pct::float8, base_fee_pct::float8, turnover::float8
                   FROM v_latest_scores""")
    rows = cur.fetchall()
    now = datetime.now(timezone.utc)
    updates, vol_rows, sources = [], [], {}

    for pool, ts, fee_day, fee_pct, turnover in rows:
        # our own series wins once it is long enough; sigma is scaled by the
        # real timestamps either way, so the two sources stay comparable
        own = db.own_price_series(cur, pool, a.hours)
        if len(own) > volatility.MIN_OBS:
            series, src = own, "onchain"
        else:
            series, src = db.ohlcv_series(cur, pool, a.hours), "vendor"
        if len(series) <= volatility.MIN_OBS:
            sources["none"] = sources.get("none", 0) + 1
            continue
        r = volatility.assess(series, fee_day, fee_pct)
        if r["sigma_daily"] is None:
            continue
        sources[src] = sources.get(src, 0) + 1
        updates.append((pool, ts.isoformat(), r["sigma_daily"], r["lvr_daily_pct"],
                        r["edge_lvr_pct"], r["breakeven_turnover"], src))
        vol_rows.append((pool, now, a.hours, r["sigma_daily"], r["lvr_daily_pct"],
                         r["n_obs"], src))

    if updates:
        db.update_score_lvr(cur, updates)
        db.insert_volatility(cur, vol_rows)
    return (f"volatility for {len(updates)}/{len(rows)} pools "
            f"({', '.join(f'{k}={v}' for k, v in sources.items())})")


def cmd_worker(a):
    """Run poll and the metrics pipeline forever on a wall-clock grid."""
    class Args:
        def __init__(self, **kw): self.__dict__.update(kw)

    ing = Args(pages=a.pages, min_tvl=a.min_tvl, min_volume=a.min_volume,
               min_holders=a.min_holders, min_age_hours=a.min_age_hours, band=a.band)
    back = Args(hours=100, limit=25)
    vol = Args(hours=72)
    rf = Args(max_age_hours=24)
    # SPOT is the playbook's default shape: even distribution, lower maintenance.
    # Curve concentrates near the active price and needs more rebalancing, which
    # is the opposite of what a stability posture wants.
    mg = Args(budget=a.budget, max_positions=a.max_positions,
              shape="spot", bins=69, profile=a.profile, posture=a.posture,
              emit_intents=a.emit_intents)

    def pipeline():
        """metrics -> candles for anything missing -> sigma/LVR, as one tick"""
        parts = [cmd_ingest(ing), cmd_backfill(back), cmd_volatility(vol),
                 cmd_redflags(rf), cmd_manage(mg)]
        with db.session() as (conn, cur):
            db.roll_up_prices(cur)
        return " | ".join(p for p in parts if p)

    def poll_and_mark():
        priced = cmd_poll(None)
        with db.session() as (conn, cur):
            marks = _paper_mark(cur)
        return f"{priced} | {marks}"

    return worker.Worker([
        worker.Task("poll", poll_and_mark, a.poll_interval),
        worker.Task("pipeline", pipeline, a.ingest_interval),
    ]).run()


def _quote_usd(cur, pool, price_quote_per_base):
    """USD per unit of the quote token. Base price comes from the snapshot,
    so quote_usd = base_price_usd / (quote per base)."""
    row = db.quote_usd(cur, pool)
    if not row or not row[1] or not price_quote_per_base:
        return None
    _sym, base_price_usd, _q = row
    return base_price_usd / price_quote_per_base


def cmd_paper_open(a):
    with db.session() as (conn, cur):
        meta = db.pool_for_paper(cur, a.pool)
        if not meta:
            return "unknown pool - run ingest first"
        flag = db.is_blocked(cur, a.pool)
        if flag and flag[0] and not a.force:
            why = "\n  · ".join(flag[1] or [])
            return f"REFUSED - this pool is red-flagged:\n  · {why}\n(use --force to override)"
        _addr, name, bin_step, qsym, dec_x, dec_y, _mx, _my = meta
        pr = db.latest_price(cur, a.pool)
        if not pr:
            return "no on-chain price yet - run `poll` first"
        ts, active_id, price = pr
        qusd = _quote_usd(cur, a.pool, price)
        if not qusd:
            return "cannot value the quote leg yet (no snapshot base_price)"

        # offset lets several positions tile or straddle one pool: the 69-bin
        # cap is per position, not per pool
        pid = _open_paper(cur, a.pool, a.capital, a.shape, a.bins, a.strategy,
                          a.notes, offset=a.offset, auto=False)
        if pid is None:
            return "could not open - missing price or metadata"
        n_bins = min(a.bins, paper.MAX_BINS)
        center = active_id + a.offset
    off = f" offset {a.offset:+d}" if a.offset else ""
    return (f"opened #{pid} {name} {a.shape} {n_bins} bins{off} ${a.capital:.2f} "
            f"@ {price:.8f} (centre bin {center}, active {active_id})")


def cmd_paper_mark(a):
    with db.session() as (conn, cur):
        return _paper_mark(cur)


def _paper_mark(cur):
    marked, closed = 0, 0
    sol = db.sol_price_usd(cur) or 0.0
    urgent = 0
    for (pid, pool, shape, n_bins, center, capital, bins_raw, e_base, e_quote,
         fees, rebals, last_active, opened_at, tx_count, rent_sol,
         was_in_range, entry_sigma, out_since, out_side,
         ever_in_range) in db.open_paper_positions(cur):
        meta = db.pool_for_paper(cur, pool)
        pr = db.latest_price(cur, pool)
        if not meta or not pr:
            continue
        _a, _n, bin_step, _q, dec_x, dec_y, _mx, _my = meta
        ts, active_id, price = pr
        qusd = _quote_usd(cur, pool, price)
        if not qusd:
            continue

        bins = paper.loads(bins_raw)
        bins, crossed = paper.walk(bins, last_active, active_id, bin_step, dec_x, dec_y)

        half = n_bins // 2
        off = active_id - center
        in_range = abs(off) <= half
        cur_side = exits.side(active_id, center, n_bins)
        # the clock starts when the range is first left, and resets on re-entry
        if cur_side is None:
            out_since, out_side = None, None
        elif out_since is None or cur_side != out_side:
            out_since, out_side = ts, cur_side

        # fees accrue only for the time since the previous mark, and only in range
        cur.execute("""SELECT max(ts) FROM paper_marks WHERE position_id = %s""", (pid,))
        prev_ts = cur.fetchone()[0] or opened_at
        hours = max(0.0, (ts - prev_ts).total_seconds() / 3600.0)
        rate = db.latest_fee_rate(cur, pool) or 0.0
        fees = float(fees) + paper.fee_accrual(
            float(capital), rate, shape, n_bins, off if in_range else None, hours)

        # a rebalance is a transition out of range, not every tick spent there;
        # counting ticks made a quiet position look like a frantic one
        left_range = (was_in_range is True) and not in_range
        rebals = int(rebals) + (1 if left_range else 0)
        tx_count = int(tx_count) + (paper.TX_REBALANCE if left_range else 0)

        base_amt, quote_amt = paper.totals(bins)
        value = paper.value_usd(bins, price, qusd)
        hold = (float(e_base) * price + float(e_quote)) * qusd
        pnl = value + fees - hold
        gas_usd, rent_usd = paper.costs_usd(tx_count, sol)
        net = pnl - gas_usd

        db.insert_paper_mark(cur, (pid, ts, price, active_id, in_range,
                                   base_amt, quote_amt, value, fees, hold, pnl,
                                   gas_usd, rent_usd, net))
        db.update_paper_position(cur, pid, paper.dumps(bins), fees, rebals,
                                 active_id, tx_count,
                                 paper.tx_cost_sol(tx_count), in_range)

        live = db.live_signals(cur, pool)
        if entry_sigma is None and live.get("sigma_daily"):
            db.set_entry_context(cur, pid, live["sigma_daily"], live.get("edge_lvr_pct"))
            entry_sigma = live["sigma_daily"]
        hours_out = ((ts - out_since).total_seconds() / 3600.0) if out_since else 0.0
        urgency, reasons = exits.evaluate(
            dict(entry_sigma=float(entry_sigma) if entry_sigma else None,
                 out_side=out_side, hours_out=hours_out,
                 ever_in_range=ever_in_range or in_range),
            dict(live, pnl_pct=(net / float(capital) * 100.0) if capital else None))
        db.update_exit_state(cur, pid, out_since, out_side, urgency, reasons, in_range)
        if urgency == "hard":
            urgent += 1

        marked += 1
        if not in_range:
            closed += 1
    return (f"marked {marked} paper positions ({closed} out of range, "
            f"{urgent} flagged to exit)")


def cmd_paper_report(a):
    with db.session() as (conn, cur):
        cur.execute("""SELECT id, name, strategy, shape, n_bins, capital_usd,
                              hours_open, price, in_range, value_usd, fees_usd,
                              hold_usd, pnl_vs_hold, pnl_pct, rebalances, marked_at,
                              gas_usd, rent_usd, net_pnl, min_bin, max_bin,
                              min_price::float8, max_price::float8
                       FROM v_paper_latest WHERE closed_at IS NULL
                       ORDER BY pnl_pct DESC NULLS LAST""")
        rows = cur.fetchall()
    if not rows:
        return "no paper positions yet - `paper open <pool>` to start one"
    print(f"\n{'#':>3} {'pool':<14}{'shape':>7}{'bins':>6}{'bin range':>17}"
          f"{'price range':>25}{'cap':>7}{'fees':>7}{'net':>8}{'net%':>8}{'rng':>5}")
    print("-" * 108)
    for (pid, name, strat, shape, nb, cap, hrs, price, inr, val, fees,
         hold, pnl, pnlpct, reb, _ts, gas, rent, net,
         minb, maxb, minp, maxp) in rows:
        def f(v, d=2, sign=""):
            return format(float(v), f"{sign},.{d}f") if v is not None else "-"
        def px(v):
            if v is None: return "-"
            return f"{v:,.2f}" if v >= 100 else (f"{v:.4f}" if v >= 1 else f"{v:.8f}")
        rng = f"{minb} … {maxb}" if minb is not None else "-"
        prng = f"{px(minp)} – {px(maxp)}"
        print(f"{pid:>3} {name[:13]:<14}{shape:>7}{nb:>6}{rng:>17}{prng:>25}"
              f"{f(cap,0):>7}{f(fees):>7}{f(net,2,'+'):>8}{f(pnlpct,3,'+'):>8}"
              f"{'in' if inr else 'OUT':>5}")
    print("\nnet = value + fees - hold - gas. Positive means LPing beat holding")
    print("the same tokens, after transaction costs. rent is locked in the position")
    print("account and refunded on close - shown, but not deducted.\n")
    return None




def _open_paper(cur, pool, capital, shape, n_bins, strategy, notes,
                offset=0, parent=None, generation=0, auto=True):
    """Shared by `paper open`, rebalance and add. Returns the new id, or None."""
    meta = db.pool_for_paper(cur, pool)
    pr = db.latest_price(cur, pool)
    if not meta or not pr:
        return None
    _a, _n, bin_step, _q, dec_x, dec_y, _mx, _my = meta
    ts, active_id, price = pr
    qusd = _quote_usd(cur, pool, price)
    if not qusd:
        return None
    n_bins = min(n_bins, paper.MAX_BINS)
    if n_bins % 2 == 0:
        n_bins -= 1
    center = active_id + offset
    bins, base_tot, quote_tot = paper.open_position(
        capital, center, shape, n_bins, bin_step, dec_x, dec_y, qusd, price)
    pid = db.insert_paper_position(cur, (
        pool, strategy, shape, n_bins, center, capital, price,
        paper.dumps(bins), base_tot, quote_tot, active_id, notes,
        paper.POSITION_RENT_SOL, paper.TX_OPEN,
        paper.tx_cost_sol(paper.TX_OPEN), abs(offset) <= n_bins // 2))
    cur.execute("""UPDATE paper_positions SET parent_id=%s, generation=%s, auto=%s
                   WHERE id=%s""", (parent, generation, auto, pid))
    return pid


def _dedupe(kind, pool, cycle, extra=""):
    """One intent per decision per cycle. The cycle is the pipeline slot, so a
    restart inside the same 15 minutes re-emits an identical key and is ignored."""
    return f"{kind}:{pool}:{cycle}:{extra}"


def cmd_manage(a):
    """Close, re-centre and add - the execution layer over the exit signals."""
    with db.session() as (conn, cur):
        sol = db.sol_price_usd(cur) or 0.0
        cycle = int(time.time() // 900)          # the pipeline slot this belongs to
        gas_close = paper.tx_cost_sol(1) * sol
        gas_reb = paper.tx_cost_sol(paper.TX_REBALANCE) * sol
        did = {"close": 0, "rebalance": 0, "add": 0}
        log = []

        # what the allocator would fund right now: the yardstick for whether a
        # position still deserves its slot
        cands = db.tradeable(cur, limit=80, max_risk=60)
        planned, _pm = sizing.plan_book(a.budget or 800.0, cands, sol,
                                        a.max_positions, posture=a.posture)
        funded = {x["pool"] for x in planned}

        cur.execute("""SELECT v.id, v.exit_urgency, v.exit_reasons, v.pnl_pct::float8,
                              v.pool, v.name, p.center_bin, p.last_active, po.bin_step,
                              p.out_side, v.value_usd::float8, v.base_amt::float8,
                              v.quote_amt::float8, v.price::float8,
                              po.base_fee_pct::float8
                       FROM v_paper_latest v
                       JOIN paper_positions p ON p.id = v.id
                       JOIN pools po ON po.address = v.pool
                       WHERE v.closed_at IS NULL""")
        for (pid, urgency, reasons, pnl_pct, pool, name, center, last_active,
             bin_step, out_side, value_usd, base_amt, quote_amt, price,
             fee_pct) in cur.fetchall():
            meta = db.position_for_action(cur, pid)
            if not meta:
                continue
            _pool, shape, n_bins, capital, generation, strategy, fees = meta
            live = db.live_signals(cur, pool)
            bv = (base_amt or 0) * (price or 0)
            share = bv / (bv + (quote_amt or 0)) if (bv + (quote_amt or 0)) > 0 else None
            cur.execute("""SELECT tvl::float8 FROM snapshots WHERE pool=%s
                           ORDER BY ts DESC LIMIT 1""", (pool,))
            tvl_row = cur.fetchone()
            cost = paper.rebalance_cost(
                float(value_usd or capital), share, 0.5, fee_pct,
                tvl_row[0] if tvl_row else None, sol)
            verb, reason = actions.decide(
                dict(capital=float(capital), generation=generation, pool=pool,
                     bin_step=bin_step, out_side=out_side,
                     bins_out=actions.bins_out(last_active or center, center, n_bins)),
                live, dict(funded=funded, cost=cost), urgency or "none",
                list(reasons or []))
            if verb == actions.HOLD:
                continue

            mark = db.latest_mark(cur, pid)
            value = float(mark[0]) if mark else float(capital)
            realized = float(mark[3]) if mark and mark[3] is not None else None

            if verb == actions.CLOSE:
                db.close_position(cur, pid, reason, realized, float(fees or 0))
                db.log_action(cur, "close", reason, pool=pool, position_id=pid,
                              pnl=realized, gas=gas_close)
                if a.emit_intents:
                    # a memecoin position returns the memecoin; Zap Out swaps it
                    # on the way out rather than leaving it to be held
                    cur.execute("""SELECT po.base_mint, po.mint_y, t.symbol
                                   FROM pools po LEFT JOIN tokens t ON t.mint = po.base_mint
                                   WHERE po.address = %s""", (pool,))
                    mrow = cur.fetchone() or (None, None, None)
                    out_mint, out_why = zapout.output_mint(
                        mrow[0], mrow[1], strategy, live.get("sigma_daily"))
                    db.record_intent(cur, "close", pool,
                                     dict(position_id=pid, value_usd=value,
                                          zap_out_to=out_mint, zap_out_why=out_why),
                                     reason, _dedupe("close", pool, cycle, str(pid)),
                                     position_id=pid)
                did["close"] += 1
                log.append(f"closed #{pid} {name}: {reason}")

            elif verb == actions.REBALANCE:
                # the position is worth `value` now; that is what gets redeployed,
                # minus the cost of the two transactions it takes to move it
                redeploy = max(0.0, value - cost["total"])
                db.close_position(cur, pid, f"rebalanced: {reason}", realized,
                                  float(fees or 0))
                new_id = _open_paper(cur, pool, redeploy, shape, n_bins, strategy,
                                     f"rebalanced from #{pid}", parent=pid,
                                     generation=generation + 1)
                db.log_action(cur, "rebalance",
                              f"{reason} [gas ${cost['gas']:.3f} + swap "
                              f"${cost['swap_fee']:.2f} + slip ${cost['slippage']:.2f}]",
                              pool=pool, position_id=pid, new_position_id=new_id,
                              capital=redeploy, pnl=realized, gas=cost["total"])
                did["rebalance"] += 1
                if a.emit_intents:
                    db.record_intent(cur, "rebalance", pool,
                                     dict(position_id=pid, new_capital=redeploy,
                                          shape=shape, bins=n_bins,
                                          swap_usd=cost.get("swapped"),
                                          est_cost_usd=cost.get("total")),
                                     reason, _dedupe("rebalance", pool, cycle, str(pid)),
                                     position_id=pid)
                log.append(f"re-centred #{pid} -> #{new_id} {name} (gen {generation + 1})")

        # size the book from the budget rather than a fixed ticket per position
        if a.budget:
            held = db.held_exposure(cur)
            deployed = db.deployed_total(cur)
            free = max(0.0, a.budget - deployed - sizing.GAS_BUFFER_USD
                       - db.open_position_count(cur) * sizing.rent_usd(sol))
            cands = [c for c in db.tradeable(cur, limit=80, max_risk=60)
                     if c["mint"] not in held]
            allocs, meta = sizing.plan_book(a.budget, cands, sol, a.max_positions,
                                            posture=a.posture)
            sleeve_state = {
                name: dict(share=m.get("share"), profile=m.get("profile"),
                           target=m.get("budget"), planned=m.get("placed"),
                           candidates=m.get("candidates"))
                for name, m in meta.items() if name != "book"}
            # the floor is a function of the SOL price, not of any sleeve's
            # result - digging it out of meta returned 0.0 whenever a sleeve had
            # no candidates left, and a $14 position slipped through
            floor = sizing.min_position(sol)
            for x in allocs:
                if free < floor + sizing.rent_usd(sol):
                    break
                size = min(x["usd"], free - sizing.rent_usd(sol))
                if size < floor:
                    continue
                # width and shape are chosen from the pool's own volatility
                # rather than fixed: see sizing.geometry
                cur.execute("SELECT bin_step FROM pools WHERE address=%s", (x["pool"],))
                bstep = (cur.fetchone() or [None])[0]
                bins, shape, geo = sizing.geometry(
                    x["sigma"], bstep, x["sleeve"], x["edge"])
                pid = _open_paper(cur, x["pool"], size, shape, bins,
                                  x["sleeve"],
                                  f"{x['sleeve']}: edge={x['edge']:.2f} "
                                  f"sigma={x['sigma']*100:.1f}% kelly={x['kelly']:.3f} | {geo}")
                if not pid:
                    continue
                db.log_action(cur, "add",
                              f"{x['sleeve']} sleeve, kelly {x['kelly']:.3f} "
                              f"(edge {x['edge']:+.2f}, sigma {x['sigma'] * 100:.1f}%, "
                              f"risk {x['risk']:.1f})",
                              pool=x["pool"], new_position_id=pid, capital=size,
                              gas=paper.tx_cost_sol(1) * sol)
                if a.emit_intents:
                    db.record_intent(cur, "open", x["pool"],
                                     dict(capital_usd=size, shape=a.shape,
                                          bins=a.bins, sleeve=x["sleeve"],
                                          edge=x["edge"], sigma=x["sigma"]),
                                     f"{x['sleeve']} sleeve, kelly {x['kelly']:.3f}",
                                     _dedupe("open", x["pool"], cycle),
                                     position_id=pid)
                free -= size + sizing.rent_usd(sol)
                did["add"] += 1
                log.append(f"[{x['sleeve']:<9}] added {x['name']} ${size:.0f} "
                           f"{shape}/{bins}bin (edge {x['edge']:+.2f}, "
                           f"sigma {x['sigma'] * 100:.0f}%)")

            # record what the split actually came out as, from the allocator
            deployed_now = db.deployed_total(cur)
            n_open = db.open_position_count(cur)
            rent_now = n_open * sizing.rent_usd(sol)
            cash_now = meta["book"]["cash"]
            meta["book"].update(
                deployed=deployed_now, rent_locked=rent_now,
                idle=a.budget - deployed_now - rent_now - cash_now)
            db.record_book_state(cur, meta, sol, sleeve_state)

    for line in log:
        print("  " + line)
    return (f"closed {did['close']}, rebalanced {did['rebalance']}, "
            f"added {did['add']}")


def cmd_exits(a):
    with db.session() as (conn, cur):
        cur.execute("""SELECT id, name, shape, n_bins, round(pnl_pct,2), exit_urgency,
                              exit_reasons, out_side, hours_out, in_range
                       FROM v_paper_latest WHERE closed_at IS NULL
                       ORDER BY CASE exit_urgency WHEN 'hard' THEN 0 WHEN 'soft' THEN 1
                                ELSE 2 END, pnl_pct""")
        rows = cur.fetchall()
    hard = [r for r in rows if r[5] == "hard"]
    soft = [r for r in rows if r[5] == "soft"]
    print(f"\n{len(hard)} to close now, {len(soft)} to watch, "
          f"{len(rows) - len(hard) - len(soft)} fine\n")
    for pid, name, shape, nb, pnl, urg, reasons, oside, hout, inr in rows:
        if urg == "none":
            continue
        mark = "CLOSE" if urg == "hard" else "watch"
        print(f"  [{mark}] #{pid} {name} {shape}/{nb}  {pnl:+.2f}% vs hold")
        for r in reasons or []:
            print(f"           · {r}")
    print()
    return None


def cmd_redflags(a):
    """Refresh on-chain mint facts, then decide which pools are refused outright."""
    with db.session() as (conn, cur):
        stale = db.mints_needing_check(cur, a.max_age_hours)
        checked = mintcheck.check(stale) if stale else {}
        if checked:
            db.update_mint_facts(cur, [
                (m, f["token_program"], f["mint_auth_active"], f["freeze_auth_active"],
                 f["extensions"], f["transfer_fee_bps"]) for m, f in checked.items()])

        rows, blocks, hard_n = db.redflag_inputs(cur), [], 0
        for (addr, blacklisted, bin_step, fee_mode, mint, verified, ma, fa,
             ext, tfee, holders, fee_day, edge, lvr, turn, brk, sigma,
             mcap, tvl, from_peak, ch72, dd_obs) in rows:
            pool = dict(is_blacklisted=blacklisted, bin_step=bin_step,
                        collect_fee_mode=fee_mode)
            token = dict(is_verified=verified, mint_auth_active=ma,
                         freeze_auth_active=fa, extensions=ext,
                         transfer_fee_bps=tfee, holders=holders)
            score = dict(fee_day_pct=fee_day, edge_lvr_pct=edge, lvr_daily_pct=lvr,
                         turnover=turn, breakeven_turnover=brk, sigma_daily=sigma,
                         mcap_tvl=(mcap / tvl) if (mcap and tvl) else None,
                         from_peak_pct=from_peak, change_72h_pct=ch72,
                         dd_obs=dd_obs)
            blocked, reasons = redflags.evaluate(pool, token, score)
            if any(redflags.is_hard(r) for r in reasons):
                hard_n += 1
            blocks.append((addr, blocked, reasons))
        db.set_blocks(cur, blocks)
        n = sum(1 for _, b, _ in blocks if b)
    return (f"checked {len(checked)} mints | blocked {n}/{len(rows)} pools "
            f"({hard_n} for token or venue reasons)")


def cmd_blocked(a):
    with db.session() as (conn, cur):
        cur.execute("""SELECT name, pool, block_reasons, fee_day_pct::float8,
                              edge_lvr_pct::float8
                       FROM v_latest_scores WHERE blocked
                       ORDER BY fee_day_pct DESC NULLS LAST LIMIT %s""", (a.limit,))
        rows = cur.fetchall()
    if not rows:
        return "nothing blocked"
    print(f"\n{len(rows)} pools refused. Sorted by advertised fee — the top of this")
    print("list is what a naive APR screen would have recommended.\n")
    for name, pool, reasons, fee, edge in rows:
        f = f"{fee:.2f}%/day" if fee is not None else "–"
        e = f"{edge:+.2f}" if edge is not None else "–"
        print(f"  {name[:22]:<23} fee {f:>10}   edge {e:>7}")
        for r in reasons or []:
            print(f"      · {r}")
    print()
    return None


def cmd_top(a):
    with db.session() as (conn, cur):
        cur.execute("""
        SELECT name, pool, adjusted, opportunity, risk, fee_day_pct, floor_pct,
               cv, momentum, il_est_pct, edge_pct, bin_step, risk_flags, ts,
               sigma_daily, lvr_daily_pct, edge_lvr_pct, breakeven_turnover, turnover
        FROM v_latest_scores
        WHERE risk <= %s AND opportunity >= %s
        ORDER BY adjusted DESC LIMIT %s
        """, (a.max_risk, a.min_opportunity, a.limit))
        rows = cur.fetchall()
    if not rows:
        print("no rows - run `ingest` first, or loosen --max-risk"); return

    print(f"\nlatest snapshot {timeutil.local(rows[0][13]):%Y-%m-%d %H:%M} WIB"
          f"   ranked by adjusted score\n")
    h = (f"{'#':>2} {'pool':<18}{'adj':>6}{'risk':>6}{'fee/d':>7}{'floor':>7}"
         f"{'sigma':>7}{'LVR':>7}{'EDGE':>8}{'brkevn':>7}{'turn':>6}{'bs':>4}  flags")
    print(h); print("-" * 110)
    for i, r in enumerate(rows, 1):
        (name, pool, adj, opp, rsk, fee, floor, cv, mom, il, edge, bs, flags, _,
         sigma, lvr, edge_lvr, brk, turnover) = r
        f = lambda v, s="{:.2f}": s.format(float(v)) if v is not None else "  –"
        sig = f"{float(sigma) * 100:.1f}%" if sigma is not None else "  –"
        print(f"{i:>2} {name[:17]:<18}{f(adj,'{:.1f}'):>6}{f(rsk,'{:.1f}'):>6}"
              f"{f(fee):>6}%{f(floor):>7}{sig:>7}{f(lvr):>7}{f(edge_lvr,'{:+.2f}'):>8}"
              f"{f(brk,'{:.1f}'):>7}{f(turnover,'{:.1f}'):>6}{bs:>4}  {','.join(flags or [])[:30]}")
    print("\nadj = opp x (1 - risk/100)   fee/d = today's fees as % of TVL   floor = worst of 6 windows")
    print("sigma = realised daily volatility   LVR = sigma^2/8, the adverse-selection cost")
    print("EDGE = fee/d - LVR  <- the one that decides profit   brkevn = turnover needed to break even\n")


def cmd_history(a):
    with db.session() as (conn, cur):
        cur.execute("""
        SELECT s.ts, s.tvl, s.ftr_24h, s.vol_24h, sc.adjusted, sc.risk
        FROM snapshots s
        LEFT JOIN scores sc ON sc.pool = s.pool AND sc.ts = s.ts
        WHERE s.pool = %s ORDER BY s.ts DESC LIMIT %s
        """, (a.pool, a.limit))
        rows = cur.fetchall()
    if not rows:
        print("no snapshots for that pool"); return
    print(f"\n{'when (WIB)':<20}{'tvl':>12}{'fee/day':>9}{'vol24':>12}{'adj':>7}{'risk':>7}")
    print("-" * 67)
    for ts, tvl, ftr, vol, adj, rsk in rows:
        g = lambda v, s="{:.2f}": s.format(float(v)) if v is not None else "n/a"
        print(f"{timeutil.local(ts):%Y-%m-%d %H:%M}    {g(tvl,'{:,.0f}'):>12}{g(ftr):>9}"
              f"{g(vol,'{:,.0f}'):>12}{g(adj,'{:.1f}'):>7}{g(rsk,'{:.1f}'):>7}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest", help="fetch, snapshot and score")
    i.add_argument("--pages", type=int, default=3, help="1000 pools per page, TVL-sorted")
    i.add_argument("--min-tvl", type=float, default=50_000)
    i.add_argument("--min-volume", type=float, default=100_000)
    i.add_argument("--min-holders", type=int, default=500)
    i.add_argument("--min-age-hours", type=float, default=24)
    i.add_argument("--band", type=float, default=20.0, help="LP range width %% for IL estimate")
    i.set_defaults(fn=cmd_ingest)

    w = sub.add_parser("worker", help="long-running scheduler for pm2/systemd")
    w.add_argument("--poll-interval", type=int, default=120,
                   help="seconds between on-chain price polls")
    w.add_argument("--ingest-interval", type=int, default=900, help="seconds between metric runs")
    w.add_argument("--pages", type=int, default=3)
    w.add_argument("--min-tvl", type=float, default=50_000)
    w.add_argument("--min-volume", type=float, default=100_000)
    w.add_argument("--min-holders", type=int, default=500)
    w.add_argument("--min-age-hours", type=float, default=24)
    w.add_argument("--band", type=float, default=20.0)
    w.add_argument("--budget", type=float, default=0.0,
                   help="total capital for the whole book (0 disables adding)")
    w.add_argument("--max-positions", type=int, default=12)
    w.add_argument("--profile", choices=list(sizing.PROFILES),
                   default=sizing.DEFAULT_PROFILE)
    w.add_argument("--posture", choices=list(sizing.POSTURES),
                   default=sizing.DEFAULT_POSTURE)
    w.add_argument("--emit-intents", action="store_true",
                   help="queue decisions for the executor as well as the paper book")
    w.set_defaults(fn=cmd_worker)

    rf = sub.add_parser("redflags", help="re-evaluate refusals")
    rf.add_argument("--max-age-hours", type=int, default=24,
                    help="re-read mint accounts older than this")
    rf.set_defaults(fn=cmd_redflags)

    mn = sub.add_parser("manage", help="act on the signals: close, rebalance, add")
    mn.add_argument("--budget", type=float, default=0.0,
                    help="total capital for the whole book (0 disables adding)")
    mn.add_argument("--max-positions", type=int, default=12)
    # spot, matching the worker and the playbook: even distribution, lower
    # maintenance. Running `manage` by hand used to open curve positions while
    # the worker opened spot ones, so the same command produced two books.
    mn.add_argument("--shape", choices=["spot", "curve", "bidask"], default="spot")
    mn.add_argument("--bins", type=int, default=69)
    mn.add_argument("--profile", choices=list(sizing.PROFILES),
                    default=sizing.DEFAULT_PROFILE)
    mn.add_argument("--posture", choices=list(sizing.POSTURES),
                    default=sizing.DEFAULT_POSTURE,
                    help="how much of the book may be speculative")
    mn.add_argument("--emit-intents", action="store_true",
                    help="queue decisions for the executor as well as the paper book")
    mn.set_defaults(fn=cmd_manage)

    ex = sub.add_parser("exits", help="which open positions should be closed")
    ex.set_defaults(fn=cmd_exits)

    bl = sub.add_parser("blocked", help="list refused pools and why")
    bl.add_argument("--limit", type=int, default=30)
    bl.set_defaults(fn=cmd_blocked)

    pp = sub.add_parser("paper", help="simulated positions, no capital at risk")
    psub = pp.add_subparsers(dest="paper_cmd", required=True)
    po = psub.add_parser("open")
    po.add_argument("pool")
    po.add_argument("--capital", type=float, default=1000.0)
    po.add_argument("--shape", choices=["spot", "curve", "bidask"], default="curve")
    po.add_argument("--bins", type=int, default=69)
    po.add_argument("--strategy", default="manual")
    po.add_argument("--notes", default=None)
    po.add_argument("--force", action="store_true", help="open despite red flags")
    po.add_argument("--offset", type=int, default=0,
                    help="centre this position N bins away from the active bin")
    po.set_defaults(fn=cmd_paper_open)
    pm = psub.add_parser("mark"); pm.set_defaults(fn=cmd_paper_mark)
    prp = psub.add_parser("report"); prp.set_defaults(fn=cmd_paper_report)

    p = sub.add_parser("poll", help="on-chain price for every pool (1 RPC call)")
    p.set_defaults(fn=cmd_poll)

    b = sub.add_parser("backfill", help="seed hourly candles from vendors")
    b.add_argument("--hours", type=int, default=100)
    b.add_argument("--limit", type=int, default=0, help="0 = all pools missing history")
    b.set_defaults(fn=cmd_backfill)

    v = sub.add_parser("volatility", help="recompute sigma / LVR / edge")
    v.add_argument("--hours", type=int, default=72)
    v.set_defaults(fn=cmd_volatility)

    t = sub.add_parser("top", help="latest ranking")
    t.add_argument("--limit", type=int, default=20)
    t.add_argument("--max-risk", type=float, default=100)
    t.add_argument("--min-opportunity", type=float, default=0)
    t.set_defaults(fn=cmd_top)

    h = sub.add_parser("history", help="one pool over time")
    h.add_argument("pool")
    h.add_argument("--limit", type=int, default=30)
    h.set_defaults(fn=cmd_history)

    a = ap.parse_args()
    out = a.fn(a)
    # one-shot commands return their summary; the worker returns an exit code
    if isinstance(out, str):
        print(out)
        return 0
    return out


if __name__ == "__main__":
    sys.exit(main())

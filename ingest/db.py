"""Postgres access for db_memet. Connection comes from $MEMET_DSN."""
import contextlib, os, psycopg2, psycopg2.extras

DSN = os.environ.get("MEMET_DSN", "dbname=db_memet")


def connect():
    c = psycopg2.connect(DSN)
    c.autocommit = False
    return c


@contextlib.contextmanager
def session():
    """Connection + cursor that always close.

    The worker runs for weeks; a command that raised mid-tick used to leak its
    connection, and enough of those exhaust max_connections while the process
    still looks healthy. Rolls back on error, commits on success.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_token(cur, t):
    cur.execute("""
        INSERT INTO tokens (mint, symbol, name, decimals, is_verified,
                            freeze_disabled, holders, total_supply)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (mint) DO UPDATE SET
            symbol=EXCLUDED.symbol, name=EXCLUDED.name,
            is_verified=EXCLUDED.is_verified,
            freeze_disabled=EXCLUDED.freeze_disabled,
            holders=EXCLUDED.holders, total_supply=EXCLUDED.total_supply,
            last_seen=now()
    """, (t["address"], t.get("symbol"), t.get("name"), t.get("decimals"),
          t.get("is_verified"), t.get("freeze_authority_disabled"),
          t.get("holders"), t.get("total_supply")))


def upsert_pool(cur, p, base_mint, quote_symbol, created_at):
    cfg = p["pool_config"]
    cur.execute("""
        INSERT INTO pools (address, name, mint_x, mint_y, base_mint, quote_symbol,
                           bin_step, base_fee_pct, max_fee_pct, protocol_fee_pct,
                           collect_fee_mode, launchpad, created_at, is_blacklisted)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (address) DO UPDATE SET
            name=EXCLUDED.name, base_fee_pct=EXCLUDED.base_fee_pct,
            max_fee_pct=EXCLUDED.max_fee_pct,
            collect_fee_mode=EXCLUDED.collect_fee_mode,
            is_blacklisted=EXCLUDED.is_blacklisted, last_seen=now()
    """, (p["address"], p.get("name"), p["token_x"]["address"], p["token_y"]["address"],
          base_mint, quote_symbol, cfg.get("bin_step"), cfg.get("base_fee_pct"),
          cfg.get("max_fee_pct"), cfg.get("protocol_fee_pct"),
          cfg.get("collect_fee_mode"),
          p.get("launchpad") or None, created_at, p.get("is_blacklisted", False)))


SNAP_COLS = ("ts,pool,tvl,current_price,token_x_amount,token_y_amount,dynamic_fee_pct,"
             "base_mcap,base_price,"
             "vol_30m,vol_1h,vol_2h,vol_4h,vol_12h,vol_24h,"
             "fee_30m,fee_1h,fee_2h,fee_4h,fee_12h,fee_24h,"
             "ftr_30m,ftr_1h,ftr_2h,ftr_4h,ftr_12h,ftr_24h,cum_volume,cum_fees")
W = ("30m", "1h", "2h", "4h", "12h", "24h")


def snapshot_row(ts, p, base):
    cm = p.get("cumulative_metrics") or {}
    return (ts, p["address"], p.get("tvl"), p.get("current_price"),
            p.get("token_x_amount"), p.get("token_y_amount"), p.get("dynamic_fee_pct"),
            base.get("market_cap"), base.get("price"),
            *[p["volume"].get(w) for w in W],
            *[p["fees"].get(w) for w in W],
            *[p["fee_tvl_ratio"].get(w) for w in W],
            cm.get("volume"), cm.get("fees"))


def insert_snapshots(cur, rows):
    psycopg2.extras.execute_values(
        cur, f"INSERT INTO snapshots ({SNAP_COLS}) VALUES %s ON CONFLICT (pool, ts) DO NOTHING",
        rows, page_size=500)


def insert_price_action(cur, rows):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO price_action (ts,pool,price_usd,chg_5m,chg_1h,chg_6h,chg_24h,
                                  buys_24h,sells_24h,liquidity_usd,fdv) VALUES %s
        ON CONFLICT (pool, ts) DO NOTHING""", rows)


def insert_scores(cur, rows):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO scores (ts,pool,weights_version,opportunity,risk,adjusted,
                            fee_day_pct,floor_pct,cv,momentum,turnover,
                            il_est_pct,edge_pct,risk_flags,
                            sigma_daily,lvr_daily_pct,edge_lvr_pct,
                            breakeven_turnover,vol_source) VALUES %s
        ON CONFLICT (pool, ts, weights_version) DO UPDATE SET
            opportunity=EXCLUDED.opportunity, risk=EXCLUDED.risk,
            adjusted=EXCLUDED.adjusted, risk_flags=EXCLUDED.risk_flags,
            sigma_daily=EXCLUDED.sigma_daily, lvr_daily_pct=EXCLUDED.lvr_daily_pct,
            edge_lvr_pct=EXCLUDED.edge_lvr_pct,
            breakeven_turnover=EXCLUDED.breakeven_turnover,
            vol_source=EXCLUDED.vol_source""", rows)


# ---------------------------------------------------------------- prices / volatility
def insert_prices(cur, rows):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO prices (pool, ts, active_id, price, source) VALUES %s
        ON CONFLICT (pool, ts) DO NOTHING""", rows, page_size=500)


def insert_ohlcv(cur, rows):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO ohlcv (pool, ts, open, high, low, close, volume, source) VALUES %s
        ON CONFLICT (pool, ts) DO NOTHING""", rows, page_size=500)


def insert_volatility(cur, rows):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO volatility (pool, ts, window_hours, sigma_daily, lvr_daily_pct, n_obs, source)
        VALUES %s ON CONFLICT (pool, ts, window_hours) DO UPDATE
        SET sigma_daily=EXCLUDED.sigma_daily, lvr_daily_pct=EXCLUDED.lvr_daily_pct,
            n_obs=EXCLUDED.n_obs, source=EXCLUDED.source""", rows)


def pools_for_pricing(cur):
    """(address, dec_x, dec_y) for every pool we track."""
    cur.execute("""SELECT p.address, tx.decimals, ty.decimals
                   FROM pools p JOIN tokens tx ON tx.mint = p.mint_x
                                JOIN tokens ty ON ty.mint = p.mint_y
                   WHERE p.is_blacklisted = FALSE""")
    return cur.fetchall()


def own_price_series(cur, pool, hours=72):
    """(ts, price) oldest first. Timestamps matter: sigma must be scaled by the
    real spacing between observations, not by an assumed cadence."""
    cur.execute("""SELECT ts, price::float8 FROM prices
                   WHERE pool = %s AND ts > now() - make_interval(hours => %s)
                     AND price > 0
                   ORDER BY ts""", (pool, hours))
    return cur.fetchall()


def ohlcv_series(cur, pool, hours=72):
    """(ts, close) oldest first."""
    cur.execute("""SELECT ts, close::float8 FROM ohlcv
                   WHERE pool = %s AND ts > now() - make_interval(hours => %s)
                     AND close > 0
                   ORDER BY ts""", (pool, hours))
    return cur.fetchall()


def pools_missing_ohlcv(cur, hours=72):
    cur.execute("""SELECT v.pool FROM v_latest_scores v
                   WHERE NOT EXISTS (
                       SELECT 1 FROM ohlcv o WHERE o.pool = v.pool
                       AND o.ts > now() - make_interval(hours => %s))""", (hours,))
    return [r[0] for r in cur.fetchall()]


def update_score_lvr(cur, rows):
    psycopg2.extras.execute_values(cur, """
        UPDATE scores s SET sigma_daily = v.sigma_daily, lvr_daily_pct = v.lvr,
                            edge_lvr_pct = v.edge, breakeven_turnover = v.bet,
                            vol_source = v.src
        FROM (VALUES %s) AS v(pool, ts, sigma_daily, lvr, edge, bet, src)
        WHERE s.pool = v.pool AND s.ts = v.ts::timestamptz""", rows)


def series_bulk(cur, pools, hours=72):
    """{pool: [(ts, price)]} for many pools in two queries instead of 2N.

    Our own on-chain series wins wherever it is long enough; vendor candles
    fill the rest. Both carry real timestamps, so sigma is comparable either way.
    """
    if not pools:
        return {}, {}
    own = {}
    cur.execute("""SELECT pool, ts, price::float8 FROM prices
                   WHERE pool = ANY(%s) AND ts > now() - make_interval(hours => %s)
                     AND price > 0 ORDER BY pool, ts""", (list(pools), hours))
    for pool, ts, price in cur.fetchall():
        own.setdefault(pool, []).append((ts, price))

    vend = {}
    cur.execute("""SELECT pool, ts, close::float8 FROM ohlcv
                   WHERE pool = ANY(%s) AND ts > now() - make_interval(hours => %s)
                     AND close > 0 ORDER BY pool, ts""", (list(pools), hours))
    for pool, ts, close in cur.fetchall():
        vend.setdefault(pool, []).append((ts, close))
    return own, vend


# ---------------------------------------------------------------- paper trading
def pool_for_paper(cur, pool):
    cur.execute("""SELECT p.address, p.name, p.bin_step, p.quote_symbol,
                          tx.decimals, ty.decimals, tx.mint, ty.mint
                   FROM pools p JOIN tokens tx ON tx.mint = p.mint_x
                                JOIN tokens ty ON ty.mint = p.mint_y
                   WHERE p.address = %s""", (pool,))
    return cur.fetchone()


def latest_price(cur, pool):
    cur.execute("""SELECT ts, active_id, price::float8 FROM prices
                   WHERE pool = %s ORDER BY ts DESC LIMIT 1""", (pool,))
    return cur.fetchone()


def latest_fee_rate(cur, pool):
    cur.execute("""SELECT fee_day_pct::float8 FROM v_latest_scores WHERE pool = %s""", (pool,))
    r = cur.fetchone()
    return r[0] if r else None


def bin_fees(cur, pool, bin_ids):
    """{bin_id: (fee_x_per_token, fee_y_per_token, liquidity, amount_x, amount_y)}
    as Decimals - the accumulators are u128 and a float loses the low bits a
    two-minute interval actually moves."""
    if not bin_ids:
        return {}
    cur.execute("""SELECT bin_id, fee_x_per_token, fee_y_per_token,
                          liquidity_supply, amount_x, amount_y
                     FROM bin_fees WHERE pool = %s AND bin_id = ANY(%s)""",
                (pool, list(bin_ids)))
    return {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()}


def fee_checkpoints(cur, position_id):
    cur.execute("""SELECT bin_id, fee_x_per_token, fee_y_per_token
                     FROM paper_fee_checkpoints WHERE position_id = %s""",
                (position_id,))
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def save_fee_checkpoints(cur, position_id, chain):
    """Checkpoint every bin we hold, including ones that earned nothing this
    tick - the next delta has to start from where this one ended."""
    if not chain:
        return
    rows = [(position_id, bid, v[0], v[1]) for bid, v in chain.items()]
    cur.executemany("""INSERT INTO paper_fee_checkpoints
            (position_id, bin_id, fee_x_per_token, fee_y_per_token, synced_at)
            VALUES (%s,%s,%s,%s,now())
            ON CONFLICT (position_id, bin_id) DO UPDATE SET
              fee_x_per_token = EXCLUDED.fee_x_per_token,
              fee_y_per_token = EXCLUDED.fee_y_per_token,
              synced_at = now()""", rows)


def update_paper_claim(cur, position_id, cx, cy, usd):
    cur.execute("""UPDATE paper_positions
                      SET claim_x = %s, claim_y = %s, claim_fees_usd = %s,
                          claim_synced_at = now()
                    WHERE id = %s""", (cx, cy, usd, position_id))


def quote_usd(cur, pool):
    """USD price of the quote leg, from the token row the API already gives us."""
    cur.execute("""SELECT t.symbol, s.base_price::float8, p.quote_symbol
                   FROM pools p
                   JOIN tokens t ON t.mint = p.base_mint
                   LEFT JOIN LATERAL (SELECT base_price FROM snapshots n
                                      WHERE n.pool = p.address ORDER BY ts DESC LIMIT 1) s ON TRUE
                   WHERE p.address = %s""", (pool,))
    return cur.fetchone()


def insert_paper_position(cur, row):
    cur.execute("""INSERT INTO paper_positions
        (pool, strategy, shape, n_bins, center_bin, capital_usd, entry_price,
         bins, entry_base, entry_quote, last_active, notes,
         rent_sol, tx_count, gas_sol, was_in_range)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", row)
    return cur.fetchone()[0]


def open_paper_positions(cur):
    cur.execute("""SELECT id, pool, shape, n_bins, center_bin, capital_usd,
                          bins, entry_base, entry_quote, fees_usd, rebalances,
                          last_active, opened_at, tx_count, rent_sol, was_in_range,
                          entry_sigma, out_since, out_side, ever_in_range
                   FROM paper_positions WHERE closed_at IS NULL""")
    return cur.fetchall()


def update_paper_position(cur, pid, bins_json, fees, rebalances, last_active,
                          tx_count, gas_sol, was_in_range):
    cur.execute("""UPDATE paper_positions SET bins=%s, fees_usd=%s, rebalances=%s,
                          last_active=%s, tx_count=%s, gas_sol=%s, was_in_range=%s
                   WHERE id=%s""",
                (bins_json, fees, rebalances, last_active, tx_count, gas_sol,
                 was_in_range, pid))


def insert_paper_mark(cur, row):
    cur.execute("""INSERT INTO paper_marks
        (position_id, ts, price, active_id, in_range, base_amt, quote_amt,
         value_usd, fees_usd, hold_usd, pnl_vs_hold, gas_usd, rent_usd, net_pnl,
         claim_fees_usd, claim_net_pnl)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (position_id, ts) DO NOTHING""", row)


def paper_claim(cur, position_id):
    """(claim_x, claim_y) so far, in whole tokens."""
    cur.execute("""SELECT claim_x::float8, claim_y::float8
                     FROM paper_positions WHERE id = %s""", (position_id,))
    r = cur.fetchone()
    return (r[0], r[1]) if r else (0.0, 0.0)


def close_paper_position(cur, pid):
    cur.execute("UPDATE paper_positions SET closed_at = now() WHERE id = %s", (pid,))


# ---------------------------------------------------------------- red flags
def mints_needing_check(cur, max_age_hours=24):
    cur.execute("""SELECT mint FROM tokens
                   WHERE mint_checked_at IS NULL
                      OR mint_checked_at < now() - make_interval(hours => %s)""",
                (max_age_hours,))
    return [r[0] for r in cur.fetchall()]


def update_mint_facts(cur, rows):
    psycopg2.extras.execute_values(cur, """
        UPDATE tokens t SET token_program=v.prog, mint_auth_active=v.ma,
                            freeze_auth_active=v.fa, extensions=v.ext,
                            transfer_fee_bps=v.fee, mint_checked_at=now()
        FROM (VALUES %s) AS v(mint, prog, ma, fa, ext, fee)
        WHERE t.mint = v.mint""", rows,
        template="(%s,%s,%s::boolean,%s::boolean,%s::text[],%s::int)")


def redflag_inputs(cur):
    """Everything evaluate() needs, one row per pool."""
    cur.execute("""
        SELECT p.address, p.is_blacklisted, p.bin_step, p.collect_fee_mode,
               t.mint, t.is_verified, t.mint_auth_active, t.freeze_auth_active,
               t.extensions, t.transfer_fee_bps, t.holders,
               v.fee_day_pct::float8, v.edge_lvr_pct::float8, v.lvr_daily_pct::float8,
               v.turnover::float8, v.breakeven_turnover::float8, v.sigma_daily::float8,
               s.base_mcap::float8, s.tvl::float8,
               d.from_peak_pct::float8, d.change_72h_pct::float8, d.n_obs
        FROM pools p
        LEFT JOIN tokens t ON t.mint = p.base_mint
        LEFT JOIN v_latest_scores v ON v.pool = p.address
        LEFT JOIN LATERAL (SELECT base_mcap, tvl FROM snapshots n
                           WHERE n.pool = p.address ORDER BY ts DESC LIMIT 1) s ON TRUE
        LEFT JOIN v_drawdown d ON d.pool = p.address
    """)
    return cur.fetchall()


def set_blocks(cur, rows):
    psycopg2.extras.execute_values(cur, """
        UPDATE pools p SET blocked=v.blocked, block_reasons=v.reasons,
                           blocked_at=CASE WHEN v.blocked THEN COALESCE(p.blocked_at, now()) END
        FROM (VALUES %s) AS v(addr, blocked, reasons)
        WHERE p.address = v.addr""", rows,
        template="(%s,%s::boolean,%s::text[])")


def is_blocked(cur, pool):
    cur.execute("SELECT blocked, block_reasons FROM pools WHERE address = %s", (pool,))
    return cur.fetchone()


def sol_price_usd(cur):
    """SOL in USD from the most recent snapshot of any SOL-quoted pool."""
    cur.execute("""SELECT s.base_price::float8 FROM snapshots s
                   JOIN pools p ON p.address = s.pool
                   WHERE p.name LIKE 'SOL-%' AND s.base_price > 0
                   ORDER BY s.ts DESC LIMIT 1""")
    r = cur.fetchone()
    return r[0] if r else None


def live_signals(cur, pool):
    """Current pool state the exit rules need."""
    cur.execute("""SELECT sigma_daily::float8, edge_lvr_pct::float8, blocked, block_reasons
                   FROM v_latest_scores WHERE pool = %s""", (pool,))
    r = cur.fetchone()
    return dict(sigma_daily=r[0], edge_lvr_pct=r[1], blocked=r[2],
                block_reasons=r[3]) if r else {}


def set_entry_context(cur, pid, sigma, edge):
    cur.execute("""UPDATE paper_positions SET entry_sigma=%s, entry_edge=%s
                   WHERE id=%s AND entry_sigma IS NULL""", (sigma, edge, pid))


def update_exit_state(cur, pid, out_since, out_side, urgency, reasons, in_range):
    cur.execute("""UPDATE paper_positions SET out_since=%s, out_side=%s,
                          exit_urgency=%s, exit_reasons=%s,
                          ever_in_range = ever_in_range OR %s
                   WHERE id=%s""",
                (out_since, out_side, urgency, reasons, in_range, pid))


# ---------------------------------------------------------------- actions
def close_position(cur, pid, reason, realized_pnl, realized_fees):
    cur.execute("""UPDATE paper_positions
                   SET closed_at=now(), close_reason=%s,
                       realized_pnl=%s, realized_fees=%s
                   WHERE id=%s AND closed_at IS NULL""",
                (reason, realized_pnl, realized_fees, pid))


def log_action(cur, kind, reason, pool=None, position_id=None,
               new_position_id=None, capital=None, pnl=None, gas=None):
    cur.execute("""INSERT INTO actions
        (kind, position_id, new_position_id, pool, reason, capital_usd, pnl_usd, gas_usd)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (kind, position_id, new_position_id, pool, reason, capital, pnl, gas))


def position_for_action(cur, pid):
    cur.execute("""SELECT p.pool, p.shape, p.n_bins, p.capital_usd, p.generation,
                          p.strategy, p.fees_usd
                   FROM paper_positions p WHERE p.id=%s""", (pid,))
    return cur.fetchone()


def open_position_count(cur):
    cur.execute("SELECT count(*) FROM paper_positions WHERE closed_at IS NULL")
    return cur.fetchone()[0]


def held_exposure(cur):
    """{base_mint: usd}. Keyed by TOKEN, not pool: one token often has several
    pools at different bin steps, and the risk being taken is the token's."""
    cur.execute("""SELECT po.base_mint, sum(p.capital_usd)::float8
                   FROM paper_positions p JOIN pools po ON po.address = p.pool
                   WHERE p.closed_at IS NULL GROUP BY 1""")
    return {r[0]: r[1] for r in cur.fetchall()}


def deployed_total(cur):
    cur.execute("""SELECT COALESCE(sum(capital_usd),0)::float8
                   FROM paper_positions WHERE closed_at IS NULL""")
    return cur.fetchone()[0]


def tradeable(cur, limit=40, max_risk=45):
    """Candidates with everything the allocator needs.

    n_obs must count the series sigma was actually computed from. Counting only
    `prices` rejected every candidate on a fresh deployment: sigma came from 100
    vendor candles while the on-chain series was an hour old with 11 points, and
    the data-quality floor read that as "not enough data" for pools that had
    plenty."""
    cur.execute("""SELECT v.pool, v.name, p.base_mint, v.edge_lvr_pct::float8,
                          v.sigma_daily::float8, v.risk::float8,
                          CASE WHEN v.vol_source = 'vendor'
                               THEN (SELECT count(*) FROM ohlcv o WHERE o.pool = v.pool)
                               ELSE (SELECT count(*) FROM prices pr WHERE pr.pool = v.pool)
                          END AS n_obs,
                          t.is_verified, t.holders
                   FROM v_tradeable v JOIN pools p ON p.address = v.pool
                   JOIN tokens t ON t.mint = p.base_mint
                   WHERE v.risk < %s LIMIT %s""", (max_risk, limit))
    return [dict(pool=r[0], name=r[1], mint=r[2], edge=r[3], sigma=r[4],
                 risk=r[5], n_obs=r[6], verified=r[7], holders=r[8])
            for r in cur.fetchall()]


def latest_mark(cur, pid):
    cur.execute("""SELECT value_usd::float8, fees_usd::float8, hold_usd::float8,
                          net_pnl::float8
                   FROM paper_marks WHERE position_id=%s ORDER BY ts DESC LIMIT 1""", (pid,))
    return cur.fetchone()


def record_book_state(cur, meta, sol_price, sleeves):
    """Snapshot the capital structure the allocator just produced."""
    b = meta.get("book") or {}
    cur.execute("""INSERT INTO book_state
        (budget, deployed, rent_locked, cash, cash_usdc, cash_sol, idle,
         sol_price, sleeves)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (ts) DO NOTHING""",
                (b.get("budget"), b.get("deployed"), b.get("rent_locked"),
                 b.get("cash"), b.get("cash_usdc"), b.get("cash_sol"),
                 b.get("idle"), sol_price, psycopg2.extras.Json(sleeves)))


def roll_up_prices(cur):
    """Fold raw prices into hourly candles and drop the raw rows past a week.
    Volatility only looks back 72h, so nothing the engine reads is lost."""
    cur.execute("SELECT roll_up_prices()")


# ---------------------------------------------------------------- intents
def record_intent(cur, kind, pool, params, reason, dedupe_key, position_id=None):
    """Queue an execution intent. The dedupe key makes this idempotent: a worker
    restart mid-cycle re-emits the same decision and must not double-execute."""
    cur.execute("""INSERT INTO intents
        (kind, pool, position_id, params, reason, dedupe_key)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id""",
                (kind, pool, position_id, psycopg2.extras.Json(params), reason,
                 dedupe_key))
    row = cur.fetchone()
    return row[0] if row else None

import pg from "pg";

const { Pool } = pg;
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL ?? "postgres:///db_memet",
});

export interface Intent {
  id: number;
  kind: string;
  pool: string;
  position_id: number | null;
  params: Record<string, any>;
  reason: string;
}

/** Claim one pending intent. FOR UPDATE SKIP LOCKED so two executors never
 *  pick the same row - the queue is the only coordination they need. */
export async function claim(): Promise<Intent | null> {
  const c = await pool.connect();
  try {
    await c.query("BEGIN");
    const r = await c.query(
      `SELECT id, kind, pool, position_id, params, reason
         FROM intents WHERE status = 'pending'
         ORDER BY created_at LIMIT 1
         FOR UPDATE SKIP LOCKED`,
    );
    if (r.rowCount === 0) {
      await c.query("ROLLBACK");
      return null;
    }
    await c.query(
      "UPDATE intents SET status='simulating', picked_at=now() WHERE id=$1",
      [r.rows[0].id],
    );
    await c.query("COMMIT");
    return r.rows[0] as Intent;
  } catch (e) {
    await c.query("ROLLBACK");
    throw e;
  } finally {
    c.release();
  }
}

export async function resolve(
  id: number,
  status: string,
  fields: { units?: number; logs?: string[]; costUsd?: number; error?: string } = {},
) {
  await pool.query(
    `UPDATE intents SET status=$2, resolved_at=now(), sim_units=$3,
            sim_logs=$4, est_cost_usd=$5, error=$6 WHERE id=$1`,
    [id, status, fields.units ?? null, fields.logs ?? null,
     fields.costUsd ?? null, fields.error ?? null],
  );
}

export async function spendWindow() {
  const r = await pool.query(`
    SELECT
      COALESCE(SUM((params->>'capital_usd')::numeric) FILTER
        (WHERE created_at > now() - interval '1 hour'), 0) AS usd_hour,
      COUNT(*) FILTER (WHERE created_at > now() - interval '1 hour'
                         AND status IN ('sent','confirmed','simulated')) AS tx_hour,
      COALESCE(SUM((params->>'capital_usd')::numeric) FILTER
        (WHERE created_at > now() - interval '1 day'), 0) AS usd_day
    FROM intents`);
  return {
    usdHour: Number(r.rows[0].usd_hour),
    txHour: Number(r.rows[0].tx_hour),
    usdDay: Number(r.rows[0].usd_day),
  };
}

export async function poolMeta(address: string) {
  const r = await pool.query(
    `SELECT p.address, p.name, p.bin_step, p.mint_x, p.mint_y,
            tx.decimals AS dec_x, ty.decimals AS dec_y
       FROM pools p
       JOIN tokens tx ON tx.mint = p.mint_x
       JOIN tokens ty ON ty.mint = p.mint_y
      WHERE p.address = $1`,
    [address],
  );
  return r.rows[0] ?? null;
}

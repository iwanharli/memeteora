/**
 * Reads the DLMM fee accumulators for every bin an open paper position sits
 * in, and writes them to `bin_fees`.
 *
 * This is the measurement half of "real fees at paper size". The program
 * settles a claim as
 *
 *     claimable = (bin.feeAmountPerTokenStored - checkpoint) * liquidity_share
 *
 * so the accumulator is the only thing that has to come from the chain; the
 * share is whatever the paper position holds. Reading it needs no key, no
 * position and no transaction - these are public account reads.
 *
 * Like the rest of exec/, this process never signs and never sends.
 */
import DLMM, { deriveBinArray, binIdToBinArrayIndex, LBCLMM_PROGRAM_IDS } from "@meteora-ag/dlmm";
import { Connection, PublicKey } from "@solana/web3.js";
import BN from "bn.js";
import { pool as db } from "./db.js";

// || not ??: pm2 passes an unset SOLANA_RPC through as an empty string,
// which ?? happily accepts and the Connection constructor then rejects.
const RPC = process.env.SOLANA_RPC || "https://api.mainnet-beta.solana.com";
const connection = new Connection(RPC, "confirmed");
const PROGRAM_ID = new PublicKey(LBCLMM_PROGRAM_IDS["mainnet-beta"]);

const BINS_PER_ARRAY = 70;
// getMultipleAccounts caps at 100 and a bin array is ~10KB; well under the
// response limit at this size, and one round trip instead of sixteen.
const FETCH_CHUNK = 50;

interface Range { pool: string; lower: number; upper: number }

/** The bin ranges we need, one per pool, unioned across open positions -
 *  two positions in the same pool overlap heavily and there is no point
 *  reading the same account twice. */
async function ranges(): Promise<Range[]> {
  const r = await db.query<{ pool: string; lower: string; upper: string }>(
    `SELECT pool,
            min(center_bin - n_bins / 2) AS lower,
            max(center_bin + n_bins / 2) AS upper
       FROM paper_positions
      WHERE closed_at IS NULL
      GROUP BY pool`,
  );
  return r.rows.map((x) => ({ pool: x.pool, lower: Number(x.lower), upper: Number(x.upper) }));
}

function arrayIndexes(lower: number, upper: number): number[] {
  const lo = binIdToBinArrayIndex(new BN(lower)).toNumber();
  const hi = binIdToBinArrayIndex(new BN(upper)).toNumber();
  const out: number[] = [];
  for (let i = lo; i <= hi; i++) out.push(i);
  return out;
}

/** Bin ids run from index*70 upward, and floor division is what the program
 *  uses, so a negative index still starts at index*70 - no off-by-one at the
 *  boundary where bin ids go negative. */
function firstBinOfArray(index: number): number {
  return index * BINS_PER_ARRAY;
}

export async function sync(): Promise<{ pools: number; bins: number; accounts: number }> {
  const rs = await ranges();
  if (rs.length === 0) return { pools: 0, bins: 0, accounts: 0 };

  const program = (await DLMM.create(connection, new PublicKey(rs[0].pool))).program;

  let bins = 0;
  let accounts = 0;
  for (const r of rs) {
    const lbPair = new PublicKey(r.pool);
    const idxs = arrayIndexes(r.lower, r.upper);
    const keys = idxs.map((i) => deriveBinArray(lbPair, new BN(i), PROGRAM_ID)[0]);

    const rows: any[][] = [];
    for (let i = 0; i < keys.length; i += FETCH_CHUNK) {
      const slice = keys.slice(i, i + FETCH_CHUNK);
      const fetched = await program.account.binArray.fetchMultiple(slice);
      accounts += slice.length;
      for (let j = 0; j < fetched.length; j++) {
        const acc: any = fetched[j];
        // An array with no liquidity yet has never been initialised. Nothing
        // has been earned there, so there is nothing to record.
        if (!acc) continue;
        const base = firstBinOfArray(idxs[i + j]);
        for (let k = 0; k < acc.bins.length; k++) {
          const b = acc.bins[k];
          rows.push([
            r.pool, base + k,
            b.feeAmountXPerTokenStored.toString(),
            b.feeAmountYPerTokenStored.toString(),
            b.liquiditySupply.toString(),
            b.amountX.toString(), b.amountY.toString(),
          ]);
        }
      }
    }
    bins += rows.length;
    await upsert(rows);
  }
  return { pools: rs.length, bins, accounts };
}

/** One statement per pool rather than per bin: a 1099-bin position is 16
 *  arrays of 70, and 1120 round trips per pool per tick would cost more than
 *  the RPC read did. */
async function upsert(rows: any[][]): Promise<void> {
  if (rows.length === 0) return;
  const CHUNK = 500;
  for (let i = 0; i < rows.length; i += CHUNK) {
    const slice = rows.slice(i, i + CHUNK);
    const values: any[] = [];
    const tuples = slice.map((r, n) => {
      values.push(...r);
      const b = n * 7;
      return `($${b + 1},$${b + 2},$${b + 3},$${b + 4},$${b + 5},$${b + 6},$${b + 7})`;
    });
    await db.query(
      `INSERT INTO bin_fees
         (pool, bin_id, fee_x_per_token, fee_y_per_token,
          liquidity_supply, amount_x, amount_y)
       VALUES ${tuples.join(",")}
       ON CONFLICT (pool, bin_id) DO UPDATE SET
         ts = now(),
         fee_x_per_token = EXCLUDED.fee_x_per_token,
         fee_y_per_token = EXCLUDED.fee_y_per_token,
         liquidity_supply = EXCLUDED.liquidity_supply,
         amount_x = EXCLUDED.amount_x,
         amount_y = EXCLUDED.amount_y`,
      values,
    );
  }
}

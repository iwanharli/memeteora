/** Entry point for the fee sync. Reads public accounts only; never signs. */
import { sync } from "./binfees.js";
import { pool as db } from "./db.js";

const EVERY_MS = Number(process.env.FEE_SYNC_SECONDS ?? 600) * 1000;
const once = process.argv.includes("--once");

function log(msg: string) {
  console.log(`${new Date().toISOString()} ${msg}`);
}

async function tick() {
  const t0 = Date.now();
  try {
    const r = await sync();
    log(`synced ${r.bins} bins across ${r.pools} pools ` +
        `(${r.accounts} accounts, ${Date.now() - t0}ms)`);
  } catch (e: any) {
    // A failed sync is not fatal: the Python side falls back to the modelled
    // rate for that interval and the next tick picks the accumulators up
    // again, since they are cumulative rather than per-interval.
    log(`sync failed: ${e.message}`);
  }
}

(async () => {
  log(`fee sync · rpc ${process.env.SOLANA_RPC ? "custom" : "public mainnet"}` +
      (once ? " · once" : ` · every ${EVERY_MS / 1000}s`));
  await tick();
  if (once) { await db.end(); return; }
  setInterval(tick, EVERY_MS);
})();

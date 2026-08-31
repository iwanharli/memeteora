/**
 * memet-exec — reads execution intents, builds the transaction, simulates it,
 * and writes the result back. It does not sign and does not send.
 *
 *   npm run dry-run          follow the queue
 *   npm run once             drain what is queued, then exit
 *
 * Signing will be a separate, explicit step. Everything here is safe to run
 * against a live wallet address because no secret is read: the fee payer is a
 * PUBLIC key and simulation runs with signature verification off.
 */
import BN from "bn.js";
import { claim, resolve, spendWindow, poolMeta, pool } from "./db";
import { buildOpen, buildClose, simulate, payer, checkPayer, connection } from "./dlmm";
import { quote, impactPct } from "./jupiter";
import { DEFAULT_LIMITS, check, halted } from "./guards";

const LIVE = process.argv.includes("--live");
const ONCE = process.argv.includes("--once");
const POLL_MS = Number(process.env.EXEC_POLL_MS ?? 5000);

function log(level: string, msg: string) {
  const ts = new Date().toISOString().replace("T", " ").slice(0, 19);
  console.log(`${ts} ${level.padEnd(5)} exec  ${msg}`);
}

async function solPriceUsd(): Promise<number> {
  const r = await pool.query(
    `SELECT s.base_price::float8 AS p FROM snapshots s
       JOIN pools po ON po.address = s.pool
      WHERE po.name LIKE 'SOL-%' AND s.base_price > 0
      ORDER BY s.ts DESC LIMIT 1`,
  );
  return r.rows[0]?.p ?? 0;
}

async function handle(intent: Awaited<ReturnType<typeof claim>>) {
  if (!intent) return;
  const { id, kind, params, reason } = intent;
  const meta = await poolMeta(intent.pool);
  const name = meta?.name ?? intent.pool.slice(0, 8);

  const win = await spendWindow();
  const rejection = check(intent, DEFAULT_LIMITS, win.usdHour, win.txHour, win.usdDay);
  if (rejection) {
    log("WARN", `#${id} ${kind} ${name} REJECTED — ${rejection}`);
    await resolve(id, "rejected", { error: rejection });
    return;
  }

  try {
    const from = payer();
    const sol = await solPriceUsd();

    if (kind === "open") {
      const usd = Number(params.capital_usd ?? 0);
      const side = String(params.side ?? "both") as "both" | "quote" | "base";

      // a range below the price takes only the quote leg, above only the base;
      // straddling takes both, split evenly
      let xUsd = 0, yUsd = 0;
      if (side === "quote") yUsd = usd;
      else if (side === "base") xUsd = usd;
      else { xUsd = usd / 2; yUsd = usd / 2; }

      const xAmt = new BN(Math.floor((xUsd / (sol || 1)) * 10 ** (meta?.dec_x ?? 9)));
      const yAmt = new BN(Math.floor(yUsd * 10 ** (meta?.dec_y ?? 6)));

      const { tx, positionPubkey } = await buildOpen(
        intent.pool, from, xAmt, yAmt, Number(params.bins ?? 69),
        String(params.shape ?? "spot"), side,
      );
      const sim = await simulate(tx, from);
      const feeUsd = ((sim.units ?? 0) / 1e6) * 0.000005 * sol;
      if (sim.ok) {
        log("INFO", `#${id} open ${name} $${usd.toFixed(2)} ${side} — simulated ok, ` +
          `${sim.units} CU, position ${positionPubkey.toBase58().slice(0, 8)}…`);
        await resolve(id, "simulated", { units: sim.units, logs: sim.logs.slice(-8), costUsd: feeUsd });
      } else {
        log("WARN", `#${id} open ${name} — simulation failed: ${sim.error}`);
        await resolve(id, "failed", { logs: sim.logs.slice(-12), error: sim.error });
      }
      return;
    }

    if (kind === "close") {
      // needs the on-chain position address, which only exists once the open
      // has actually been executed - in dry-run there is nothing to close
      const onchain = params.position_pubkey as string | undefined;
      if (!onchain) {
        const why = "no on-chain position yet (dry-run has never opened one)";
        log("INFO", `#${id} close ${name} — skipped, ${why}`);
        await resolve(id, "rejected", { error: why });
        return;
      }
      const txs = await buildClose(intent.pool, from, onchain);
      let units = 0;
      for (const tx of txs) {
        const sim = await simulate(tx, from);
        if (!sim.ok) {
          await resolve(id, "failed", { logs: sim.logs.slice(-12), error: sim.error });
          log("WARN", `#${id} close ${name} — simulation failed: ${sim.error}`);
          return;
        }
        units += sim.units ?? 0;
      }
      log("INFO", `#${id} close ${name} — simulated ok across ${txs.length} tx, ${units} CU`);
      await resolve(id, "simulated", { units });
      return;
    }

    if (kind === "rebalance") {
      // the swap leg is what the engine could only estimate; price a real route
      const swapUsd = Number(params.swap_usd ?? 0);
      let note = "no swap leg";
      if (swapUsd > 0 && meta) {
        const amt = BigInt(Math.floor((swapUsd / (sol || 1)) * 10 ** meta.dec_x));
        const q = await quote(meta.mint_x, meta.mint_y, amt);
        note = q
          ? `swap $${swapUsd.toFixed(2)} routed, price impact ${impactPct(q).toFixed(3)}%`
          : "no route found for the swap leg";
      }
      log("INFO", `#${id} rebalance ${name} — ${note}`);
      await resolve(id, "simulated", { costUsd: Number(params.est_cost_usd ?? 0) });
      return;
    }

    await resolve(id, "rejected", { error: `unknown intent kind ${kind}` });
  } catch (e: any) {
    log("ERROR", `#${id} ${kind} ${name} — ${e.message}`);
    await resolve(id, "failed", { error: String(e.message).slice(0, 500) });
  }
}

async function main() {
  if (LIVE) {
    log("ERROR", "--live is not implemented. This build simulates only, by design.");
    process.exit(1);
  }
  log("INFO", `dry-run · rpc ${process.env.SOLANA_RPC ?? "public mainnet"} · ` +
    `limits $${DEFAULT_LIMITS.maxUsdPerTx}/tx, ${DEFAULT_LIMITS.maxTxPerHour}/h, ` +
    `$${DEFAULT_LIMITS.maxUsdPerDay}/day`);
  if (halted(DEFAULT_LIMITS)) log("WARN", "HALT file present — every intent will be rejected");

  // fail loudly at startup rather than on every intent
  try {
    const problem = await checkPayer(payer());
    if (problem) { log("ERROR", problem); process.exit(1); }
    log("INFO", `fee payer ${payer().toBase58().slice(0, 8)}… ok (public key only)`);
  } catch (e: any) {
    log("ERROR", e.message);
    process.exit(1);
  }

  let idle = 0;
  for (;;) {
    const intent = await claim();
    if (intent) {
      idle = 0;
      await handle(intent);
      continue;
    }
    if (ONCE) {
      log("INFO", "queue drained");
      break;
    }
    if (idle++ % 12 === 0) log("INFO", "waiting for intents");
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  await pool.end();
}

main().catch((e) => {
  log("ERROR", e.message);
  process.exit(1);
});

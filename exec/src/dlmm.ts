/**
 * Builds the DLMM transactions and simulates them. It never signs.
 *
 * Simulation still needs a fee payer, so a public key is read from
 * WALLET_PUBKEY. That is a public key only - no secret is read, held, or
 * required anywhere in this process. Simulation runs with sigVerify:false,
 * which is exactly what lets an unsigned transaction be checked.
 */
import DLMM, { StrategyType } from "@meteora-ag/dlmm";
import { Connection, PublicKey, Transaction } from "@solana/web3.js";
import BN from "bn.js";

const RPC = process.env.SOLANA_RPC ?? "https://api.mainnet-beta.solana.com";
export const connection = new Connection(RPC, "confirmed");

export function payer(): PublicKey {
  const k = process.env.WALLET_PUBKEY;
  if (!k) {
    throw new Error(
      "WALLET_PUBKEY is not set. A PUBLIC key is needed as the simulated fee " +
        "payer; never put a private key here.",
    );
  }
  return new PublicKey(k);
}

/** Simulation needs the fee payer to be a funded system account: an address
 *  that does not exist on chain fails with AccountNotFound, and a
 *  program-owned account (a pool, say) fails with InvalidAccountForFee.
 *  Checked once at startup so the failure is reported plainly rather than
 *  surfacing later as an opaque simulation error on every intent. */
export async function checkPayer(from: PublicKey): Promise<string | null> {
  const info = await connection.getAccountInfo(from);
  if (!info) {
    return `${from.toBase58()} does not exist on chain. WALLET_PUBKEY must be a ` +
      `funded wallet address - simulation needs a fee payer that holds SOL. ` +
      `The public key is enough; no secret is ever read.`;
  }
  if (!info.owner.equals(new PublicKey("11111111111111111111111111111111"))) {
    return `${from.toBase58()} is owned by ${info.owner.toBase58()}, not the ` +
      `System Program. WALLET_PUBKEY must be a wallet address, not a pool or ` +
      `token account.`;
  }
  if (info.lamports < 10_000_000) {
    return `${from.toBase58()} holds only ${(info.lamports / 1e9).toFixed(4)} SOL. ` +
      `Simulation needs enough to cover rent and fees, roughly 0.1 SOL.`;
  }
  return null;
}

export function strategyFor(shape: string): StrategyType {
  switch (shape) {
    case "curve": return StrategyType.Curve;
    case "bidask": return StrategyType.BidAsk;
    default: return StrategyType.Spot;
  }
}

export interface SimResult {
  ok: boolean;
  units?: number;
  logs: string[];
  error?: string;
}

/** Simulate without signing. Compute units are the useful output: they tell us
 *  the transaction is buildable and roughly what it will cost to land. */
export async function simulate(tx: Transaction, from: PublicKey): Promise<SimResult> {
  tx.feePayer = from;
  const { blockhash } = await connection.getLatestBlockhash("confirmed");
  tx.recentBlockhash = blockhash;
  const res = await connection.simulateTransaction(tx, undefined, false);
  const logs = res.value.logs ?? [];
  if (res.value.err) {
    return { ok: false, logs, error: JSON.stringify(res.value.err) };
  }
  return { ok: true, units: res.value.unitsConsumed, logs };
}

export type Side = "both" | "quote" | "base";

/** Open: position account + liquidity in one transaction, exactly as the app does.
 *
 *  `side` decides where the range sits relative to the active bin, and therefore
 *  which token the deposit needs:
 *    both  - straddles the price, needs both legs
 *    quote - entirely below, holds only the quote token (USDC for SOL-USDC)
 *    base  - entirely above, holds only the base token
 *
 *  One-sided is not a special case in DLMM, it is just a range that does not
 *  contain the active bin. It is also the structure the playbook describes for
 *  staged conversion, and the only one testable on a quote-only balance.
 */
export async function buildOpen(
  poolAddress: string, from: PublicKey,
  totalXAmount: BN, totalYAmount: BN, bins: number, shape: string,
  side: Side = "both",
): Promise<{ tx: Transaction; positionPubkey: PublicKey }> {
  const dlmm = await DLMM.create(connection, new PublicKey(poolAddress));
  await dlmm.refetchStates();
  const active = await dlmm.getActiveBin();

  let minBinId: number;
  let maxBinId: number;
  if (side === "quote") {
    // strictly below the active bin: bin 0 of the range is one step down
    maxBinId = active.binId - 1;
    minBinId = maxBinId - (bins - 1);
  } else if (side === "base") {
    minBinId = active.binId + 1;
    maxBinId = minBinId + (bins - 1);
  } else {
    const half = Math.floor(bins / 2);
    minBinId = active.binId - half;
    maxBinId = active.binId + half;
  }

  // A throwaway keypair only supplies the position address for simulation.
  // It signs nothing and is discarded with the process.
  const { Keypair } = await import("@solana/web3.js");
  const positionKp = Keypair.generate();

  const tx = await dlmm.initializePositionAndAddLiquidityByStrategy({
    positionPubKey: positionKp.publicKey,
    user: from,
    totalXAmount,
    totalYAmount,
    strategy: { maxBinId, minBinId, strategyType: strategyFor(shape) },
  });
  return { tx: tx as Transaction, positionPubkey: positionKp.publicKey };
}

/** Close: withdraw all bins, then close the account and reclaim the rent. */
export async function buildClose(
  poolAddress: string, from: PublicKey, positionPubkey: string,
): Promise<Transaction[]> {
  const dlmm = await DLMM.create(connection, new PublicKey(poolAddress));
  const { userPositions } = await dlmm.getPositionsByUserAndLbPair(from);
  const pos = userPositions.find((p) => p.publicKey.toBase58() === positionPubkey);
  if (!pos) throw new Error(`position ${positionPubkey} not found for this wallet`);

  const binIds = pos.positionData.positionBinData.map((b) => b.binId);
  const txs = await dlmm.removeLiquidity({
    position: pos.publicKey,
    user: from,
    fromBinId: Math.min(...binIds),
    toBinId: Math.max(...binIds),
    bps: new BN(10_000),          // all of it
    shouldClaimAndClose: true,
  });
  return Array.isArray(txs) ? (txs as Transaction[]) : [txs as Transaction];
}

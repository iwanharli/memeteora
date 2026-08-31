/**
 * Limits enforced here, in the executor, not in the engine that produces the
 * intents. The engine is the thing most likely to be wrong - it has three
 * minutes of validated history - so the ceiling on what it can do must live
 * somewhere it cannot reach.
 */
import { existsSync } from "node:fs";
import { join } from "node:path";

export interface Limits {
  maxUsdPerTx: number;
  maxTxPerHour: number;
  maxUsdPerDay: number;
  haltFile: string;
}

export const DEFAULT_LIMITS: Limits = {
  maxUsdPerTx: 300,
  maxTxPerHour: 12,
  maxUsdPerDay: 1200,
  haltFile: join(process.cwd(), "HALT"),
};

export function halted(limits: Limits): boolean {
  return existsSync(limits.haltFile);
}

/** Returns a rejection reason, or null when the intent is within limits. */
export function check(
  intent: { kind: string; params: Record<string, unknown> },
  limits: Limits,
  spentLastHour: number,
  txLastHour: number,
  spentToday: number,
): string | null {
  if (halted(limits)) return `HALT file present at ${limits.haltFile}`;

  const usd = Number(
    intent.params.capital_usd ?? intent.params.new_capital ?? intent.params.value_usd ?? 0,
  );
  if (usd > limits.maxUsdPerTx) {
    return `size $${usd.toFixed(2)} exceeds the $${limits.maxUsdPerTx} per-transaction ceiling`;
  }
  if (txLastHour >= limits.maxTxPerHour) {
    return `${txLastHour} transactions already in the last hour (limit ${limits.maxTxPerHour})`;
  }
  if (spentToday + usd > limits.maxUsdPerDay) {
    return `would take today's deployment to $${(spentToday + usd).toFixed(2)}, over the $${limits.maxUsdPerDay} daily ceiling`;
  }
  return null;
}

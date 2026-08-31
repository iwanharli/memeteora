/**
 * Jupiter quotes for the swap leg of a rebalance. Quote only - building the
 * swap transaction needs a signer, which this process deliberately does not have.
 *
 * The v6 host is gone; lite-api is the free tier and api.jup.ag wants a key.
 */
const BASE = process.env.JUPITER_API ?? "https://lite-api.jup.ag/swap/v1";

export interface Quote {
  inAmount: string;
  outAmount: string;
  priceImpactPct: string;
  routePlan: unknown[];
}

export async function quote(
  inputMint: string, outputMint: string, amount: bigint, slippageBps = 50,
): Promise<Quote | null> {
  const url =
    `${BASE}/quote?inputMint=${inputMint}&outputMint=${outputMint}` +
    `&amount=${amount}&slippageBps=${slippageBps}`;
  const r = await fetch(url);
  if (!r.ok) return null;
  return (await r.json()) as Quote;
}

/** Price impact is the number that decides whether a rebalance is worth it;
 *  the engine only ever estimated it from pool TVL. */
export function impactPct(q: Quote): number {
  return Math.abs(Number(q.priceImpactPct ?? 0)) * 100;
}

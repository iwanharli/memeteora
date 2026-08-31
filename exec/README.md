# memet-exec

Reads execution intents from `db_memet`, builds the Meteora DLMM transaction,
simulates it, and writes the result back.

**It does not sign and it does not send.** `--live` exits with an error; signing
will be a separate, explicit change.

## Why this is a separate process

There is no Python SDK that can build a DLMM position transaction — the PyPI
`meteora-dlmm` package only quotes swaps. So the split between deciding and
executing is forced by the tooling rather than chosen, which is convenient: the
Python engine cannot touch a key even by accident.

```
memet-worker (Python)        db_memet              memet-exec (TypeScript)
  decides            ──intent──▶ intents ◀──result──  builds, simulates
  holds no key                                        holds no key either (yet)
```

## Running it

```bash
cd exec && npm install
DATABASE_URL=postgres:///db_memet \
WALLET_PUBKEY=<your wallet address> \
  npm run once          # drain the queue, then exit
  npm run dry-run       # follow it
```

`WALLET_PUBKEY` is a **public** key. It must be a funded wallet address: an
address that does not exist on chain fails with `AccountNotFound`, and a
program-owned account (a pool) fails with `InvalidAccountForFee`. Both are
checked at startup so the failure is reported plainly instead of appearing as
an opaque simulation error on every intent.

## Limits

Enforced in `src/guards.ts`, in this process, not in the engine that produces
the intents. The engine is the thing most likely to be wrong, so the ceiling on
what it can do lives somewhere it cannot reach.

| Limit | Default |
|---|---|
| per transaction | $300 |
| per hour | 12 transactions |
| per day | $1,200 |
| kill switch | a file named `HALT` in the working directory |

## Reading the results

```sql
SELECT * FROM v_intents;          -- queue with status and errors
SELECT * FROM v_intent_summary;   -- counts and compute units by kind
```

A `failed` status with `InstructionError` is usually the simulation working
correctly: the wallet does not hold the tokens the deposit needs. That is the
whole point of simulating first.

## What is deliberately missing

- Signing and sending
- On-chain position reconciliation (the engine will hallucinate positions until
  this exists — Solana transactions can fail silently)
- Zap In/Out handling

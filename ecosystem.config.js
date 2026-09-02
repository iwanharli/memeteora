// pm2 process definitions. Both apps log to stdout/stderr and are managed
// entirely by pm2 - no daemonising, no self-written log files, no cron.
//
//   pm2 start ecosystem.config.js
//   pm2 logs memet-worker
//
// Configuration comes from .env in this directory (gitignored, chmod 600).
// The DSN is a libpq keyword string and contains spaces, so it must stay
// quoted there; dotenv handles that, a bare shell `source` does not.

const { readFileSync, existsSync } = require("fs");
const { join } = require("path");

function loadEnv() {
  const file = join(__dirname, ".env");
  if (!existsSync(file)) return {};
  const out = {};
  for (const line of readFileSync(file, "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    out[m[1]] = m[2].trim().replace(/^["'](.*)["']$/, "$1");
  }
  return out;
}

const env = loadEnv();
const PY = process.env.MEMET_PYTHON || join(__dirname, ".venv/bin/python");

module.exports = {
  apps: [
    {
      name: "memet-worker",
      script: "ingest/main.py",
      interpreter: PY,
      // budget and posture are the two settings worth changing by hand;
      // everything else the engine decides for itself
      args: "worker --budget 800 --max-positions 12 --posture stability",
      cwd: __dirname,
      instances: 1,          // two schedulers would double-write every snapshot
      exec_mode: "fork",
      autorestart: true,
      restart_delay: 10000,  // back off rather than hammer a broken API
      max_restarts: 20,
      min_uptime: "60s",
      kill_timeout: 30000,   // let an in-flight tick finish on SIGTERM
      max_memory_restart: "400M",
      env: {
        PYTHONUNBUFFERED: "1",   // without this pm2 sees nothing until the buffer flushes
        MEMET_DSN: env.MEMET_DSN || "dbname=db_memet",
      },
    },
    {
      // Reads the DLMM fee accumulators for the bins our paper positions hold.
      // Public account reads only - no key, no position, no transaction. The
      // interval is decoupled from the two-minute mark because the
      // accumulators are cumulative: a mark that lands between syncs simply
      // credits nothing and the next one catches up.
      name: "memet-fees",
      script: "npm",
      args: "run fees",
      cwd: join(__dirname, "exec"),
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      restart_delay: 15000,
      min_uptime: "60s",
      max_memory_restart: "300M",
      env: {
        // node-postgres reads a host-less URL as TCP to localhost, where
        // pg_hba demands a password; libpq and sqlx read the same string as
        // the unix socket. Naming the socket explicitly is what makes this
        // work as root without putting a password in the process env.
        DATABASE_URL: env.EXEC_DATABASE_URL ||
          "postgres:///db_memet?host=/var/run/postgresql",
        FEE_SYNC_SECONDS: env.FEE_SYNC_SECONDS || "600",
        // the public endpoint rate-limits well before this matters, but a
        // paid one is what makes a shorter interval safe
        SOLANA_RPC: env.SOLANA_RPC || "",
      },
    },
    {
      name: "memet-web",
      script: "./web/target/release/memet-web",
      cwd: __dirname,
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      restart_delay: 5000,
      min_uptime: "30s",
      kill_timeout: 10000,
      max_memory_restart: "300M",
      env: {
        DATABASE_URL: env.DATABASE_URL || "postgres:///db_memet",
        BIND_ADDR: env.BIND_ADDR || "127.0.0.1:8080",
        RUST_LOG: "memet_web=info,tower_http=warn",
      },
    },
  ],
};

// pm2 process definitions. Both apps log to stdout/stderr and are managed
// entirely by pm2 - no daemonising, no self-written log files, no cron.
//
//   pm2 start ecosystem.config.js
//   pm2 logs memet-worker
//   pm2 restart memet-worker
//
// Override the database with MEMET_DSN / DATABASE_URL in the environment
// rather than editing this file.

const PY = process.env.MEMET_PYTHON || "python3";
const DSN = process.env.MEMET_DSN || "dbname=db_memet";
const DB_URL = process.env.DATABASE_URL || "postgres:///db_memet";

module.exports = {
  apps: [
    {
      name: "memet-worker",
      script: "ingest/main.py",
      interpreter: PY,
      args: "worker",
      cwd: __dirname,
      // one scheduler only: two would double-write every snapshot
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      // the worker exits non-zero only when a task fails repeatedly;
      // back off rather than hammering a broken API or database
      restart_delay: 10000,
      max_restarts: 20,
      min_uptime: "60s",
      kill_timeout: 30000,      // let an in-flight tick finish on SIGTERM
      max_memory_restart: "300M",
      env: {
        PYTHONUNBUFFERED: "1",  // without this pm2 sees nothing until the buffer flushes
        MEMET_DSN: DSN,
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
        DATABASE_URL: DB_URL,
        BIND_ADDR: process.env.BIND_ADDR || "127.0.0.1:8080",
        RUST_LOG: process.env.RUST_LOG || "memet_web=info,tower_http=warn",
      },
    },
  ],
};

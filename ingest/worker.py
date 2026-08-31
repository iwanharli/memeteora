"""Long-running scheduler. One process, logs to stdout, no cron and no launchd.

Built for a process manager (pm2, systemd, docker): it never daemonises, never
writes its own log files, and exits non-zero when it is genuinely broken so the
supervisor restarts it. Transient API failures are logged and retried on the
next tick instead of killing the process.
"""
import signal
import sys
import time
import traceback

from timeutil import WIB, stamp

LEVELS = {"info": "INFO", "warn": "WARN", "error": "ERROR"}


def log(level, task, msg):
    """Single-line, timestamped, unbuffered - pm2 captures stdout verbatim.
    Displayed in WIB; what goes into the database is still UTC."""
    ts = stamp(fmt="%Y-%m-%d %H:%M:%S") + " WIB"
    stream = sys.stderr if level == "error" else sys.stdout
    print(f"{ts} {LEVELS[level]:<5} {task:<10} {msg}", file=stream, flush=True)


class Task:
    """A job on a fixed wall-clock cadence.

    Aligned to the epoch rather than to start time, so restarting the worker
    does not shift the sampling grid - snapshots stay comparable across
    restarts and across machines.
    """

    def __init__(self, name, fn, interval, max_failures=10):
        self.name, self.fn, self.interval = name, fn, interval
        self.max_failures = max_failures
        self.failures = 0
        self.runs = 0
        self.next_due = self._align(time.time())

    def _align(self, now):
        return (int(now) // self.interval + 1) * self.interval

    def due(self, now):
        return now >= self.next_due

    def run(self):
        started = time.time()
        try:
            out = self.fn()
            self.failures = 0
            self.runs += 1
            log("info", self.name, f"{out or 'ok'} ({time.time() - started:.1f}s)")
        except Exception as e:
            self.failures += 1
            log("error", self.name,
                f"{type(e).__name__}: {e} (failure {self.failures}/{self.max_failures})")
            if self.failures >= self.max_failures:
                raise SystemExit(f"{self.name} failed {self.failures} times in a row")
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
        finally:
            # skip missed slots after a long stall rather than replaying them
            self.next_due = self._align(time.time())


class Worker:
    def __init__(self, tasks):
        self.tasks = tasks
        self.stopping = False
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

    def _stop(self, signum, _frame):
        log("info", "worker", f"signal {signum}, finishing current tick then exiting")
        self.stopping = True

    def run(self):
        plan = ", ".join(f"{t.name} every {t.interval}s" for t in self.tasks)
        log("info", "worker", f"started ({plan})")
        for t in self.tasks:
            log("info", "worker",
                f"{t.name} first run in {t.next_due - time.time():.0f}s")

        while not self.stopping:
            now = time.time()
            due = [t for t in self.tasks if t.due(now)]
            for t in due:
                if self.stopping:
                    break
                t.run()
            if not due:
                # wake a little before the nearest deadline; 1s keeps shutdown snappy
                nearest = min(t.next_due for t in self.tasks)
                time.sleep(max(0.2, min(1.0, nearest - time.time())))

        total = sum(t.runs for t in self.tasks)
        log("info", "worker", f"stopped cleanly after {total} runs")
        return 0

DB ?= db_memet

.PHONY: setup ingest top web build clean tunnel tunnel-down web-remote fees

setup:
	createdb $(DB) || true
	psql -v ON_ERROR_STOP=1 -f db/schema.sql $(DB)
	pip install -r ingest/requirements.txt

ingest:
	python3 ingest/main.py ingest

top:
	python3 ingest/main.py top --limit 25

# one pass of the on-chain fee sync; the daemon form runs under pm2
fees:
	cd exec && npm run fees-once

build:
	cd web && cargo build --release

web:
	cd web && cargo run --release

# Read the VPS database instead of the local one. The worker stays on the VPS -
# a second scheduler would double-write every snapshot - so this is the web app
# only, pointed at the tunnel from scripts/tunnel.sh.
tunnel:
	scripts/tunnel.sh up

tunnel-down:
	scripts/tunnel.sh down

web-remote: tunnel
	cd web && DATABASE_URL="$$(sed -n 's/^DATABASE_URL_REMOTE=//p' ../.env | tail -1 | sed 's/^["'"'"']//;s/["'"'"']$$//')" cargo run --release

clean:
	cd web && cargo clean
	find . -name __pycache__ -type d -exec rm -rf {} +

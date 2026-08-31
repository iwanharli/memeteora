DB ?= db_memet

.PHONY: setup ingest top web build clean

setup:
	createdb $(DB) || true
	psql -v ON_ERROR_STOP=1 -f db/schema.sql $(DB)
	pip install -r ingest/requirements.txt

ingest:
	python3 ingest/main.py ingest

top:
	python3 ingest/main.py top --limit 25

build:
	cd web && cargo build --release

web:
	cd web && cargo run --release

clean:
	cd web && cargo clean
	find . -name __pycache__ -type d -exec rm -rf {} +

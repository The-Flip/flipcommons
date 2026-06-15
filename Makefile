.PHONY: bootstrap dev test lint quality agent-docs codegen ingest-all ingest-patches pull-ingest pull-patches mypy mypy-warm mypy-restart mypy-status

bootstrap:
	./scripts/bootstrap

dev:
	./scripts/dev

test:
	./scripts/test

lint:
	./scripts/lint

quality: lint codegen
	cd frontend && pnpm check
	@echo "All quality checks passed!"

agent-docs:
	python3 scripts/build_agent_docs.py

codegen:
	cd backend && uv run python manage.py export_openapi_schema
	cd backend && uv run python manage.py export_entity_meta
	cd frontend && pnpm exec prettier --write src/lib/entities/entity-meta.ts
	cd frontend && pnpm api:gen

# Fresh-DB bootstrap ONLY: ingest the full seed data, then replay all data-patches.
# This gives a brand-new database something approaching the production state.
# Do NOT run this on an already-seeded system — prod and the dev DB are seeded once
# and from then on ONLY run `make ingest-patches`, never a re-ingest.
# Run `make pull-ingest && make pull-patches` first to fetch the files to ingest.
ingest-all:
	cd backend && uv run python manage.py ingest_all --write && uv run python manage.py ingest_patches

# Apply just the pending data patches — the everyday correction path once DB is seeded.
# Run `make pull-patches` first to fetch new patch files.
# Idempotent: already-applied patches are skipped.
# For a preview, run `manage.py ingest_patches --dry-run` directly.
ingest-patches:
	cd backend && uv run python manage.py ingest_patches

# Pull seed catalog + external ingest sources (pindata, IPDB, OPDB) from R2 to
# local data/ingest_sources/. Does NOT fetch data patches — see pull-patches.
pull-ingest:
	./scripts/pull_ingest_sources.sh

# Pull data patches (the flippatch/ R2 prefix) to local
# data/ingest_sources/flippatch/patches/ — the dir ingest-patches reads.
pull-patches:
	./scripts/pull_patches.sh

mypy:
	uv run --directory backend mypy --config-file pyproject.toml .

# dmypy ergonomics. dmypy holds the project type graph in memory across runs;
# `mypy-warm` pays the cold-start cost up front, `mypy-restart` is the recovery
# lever when the daemon gets out of sync (after branch switches / rebases —
# symptom: local mypy result disagrees with CI).
mypy-warm:
	uv run --directory backend dmypy start -- --config-file pyproject.toml

mypy-restart:
	uv run --directory backend dmypy restart -- --config-file pyproject.toml

mypy-status:
	uv run --directory backend dmypy status

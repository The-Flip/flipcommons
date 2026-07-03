.PHONY: bootstrap dev test lint quality agent-docs codegen ingest-patches pull-patches mypy mypy-warm mypy-restart mypy-status

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
	cd backend && uv run python manage.py export_citation_type_meta
	cd frontend && pnpm exec prettier --write src/lib/entities/entity-meta.ts src/lib/citation-types/citation-type-meta.ts
	cd frontend && pnpm api:gen

# Apply pending data patches — the bulk write path for catalog data.
# Run `make pull-patches` first to fetch new patch files.
# Idempotent: already-applied patches are skipped.
# For a preview, run `manage.py ingest_patches --dry-run` directly.
ingest-patches:
	cd backend && uv run python manage.py ingest_patches

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

.PHONY: bootstrap dev test lint quality agent-docs api-gen ingest pull-ingest mypy mypy-warm mypy-restart mypy-status

bootstrap:
	./scripts/bootstrap

dev:
	./scripts/dev

test:
	./scripts/test

lint:
	./scripts/lint

quality: lint api-gen
	cd frontend && pnpm check
	@echo "All quality checks passed!"

agent-docs:
	python3 scripts/build_agent_docs.py

api-gen:
	cd backend && uv run python manage.py export_openapi_schema
	cd backend && uv run python manage.py export_catalog_meta
	cd frontend && pnpm exec prettier --write src/lib/api/catalog-meta.ts
	cd frontend && pnpm api:gen

ingest:
	cd backend && uv run python manage.py ingest_all --write

pull-ingest:
	./scripts/pull_ingest_sources.sh

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

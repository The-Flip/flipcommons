#!/bin/bash
# Backend SessionStart chain — sandbox Python repair + venv build + migrations.
#
# Claude Code's hook runtime executes the entries in a SessionStart matcher
# **in parallel** (see https://code.claude.com/docs/en/hooks.md), so steps
# that depend on each other must live inside one script.  Without this
# bundling, ``uv sync`` races the sandbox Python repair: the sandbox ships
# uv 0.8.17 whose download catalog tops out at 3.14.0rc2, and pydantic
# 2.12 calls ``typing._eval_type(..., prefer_fwd_module=True)`` — a kwarg
# rc2 doesn't accept — so any import that touches django-ninja blows up
# with an ``AssertionError``.  Bundling the upgrade + install + sync into
# this one script guarantees the venv is built against a real 3.14.
#
# Localhost Claude Code sessions skip the ``uv self update`` + Python
# install — those mutate global tooling we don't own.
#
# The remote branch's two upgrade steps each carry a fallback for locked-down
# web sandboxes: if ``uv self update`` can't rewrite its own binary we pip
# install a newer uv into ``--user`` site, and if the default
# python-build-standalone download is blocked we retry ``uv python install``
# against an alternate mirror (``UV_PYTHON_INSTALL_MIRROR``).
#
# Emits one ``[step] elapsed=Ns`` line per stage plus a final total so
# SessionStart banner output makes failures (timeout, nonzero exit) visible
# instead of silent.  An ERR trap reports which step failed on the way out.
# The per-hook timeout in .claude/settings.json (600s) has to stay
# comfortably above the worst cold-start total — bump both together if
# cold-start totals creep toward it.
set -eEuo pipefail

script_start=$SECONDS
current_step="startup"
trap 'echo "[session-start-backend] FAILED step=${current_step} elapsed=$((SECONDS - script_start))s exit=$?"' ERR

run_step() {
  local name=$1
  shift
  current_step=$name
  local t0=$SECONDS
  "$@"
  echo "[session-start-backend] ${name} elapsed=$((SECONDS - t0))s"
}

if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  run_step "uv-self-update" bash -c \
    'uv self update || python3 -m pip install --user --quiet --upgrade uv'
  run_step "uv-python-install" bash -c \
    'uv python install 3.14 || UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-https://registry.npmmirror.com/-/binary/python-build-standalone}" uv python install 3.14'
fi

run_step "uv-sync" bash -c 'cd backend && uv sync'

# Migrations aren't a hard dependency for session startup — a migration
# error shouldn't wedge the whole hook — so run without the ERR trap.
current_step="migrate"
migrate_start=$SECONDS
( cd backend && uv run python manage.py migrate --no-input ) || \
  echo "[session-start-backend] migrate FAILED (non-fatal) elapsed=$((SECONDS - migrate_start))s"
echo "[session-start-backend] migrate elapsed=$((SECONDS - migrate_start))s"

echo "[session-start-backend] done total=$((SECONDS - script_start))s"

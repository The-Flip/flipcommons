#!/usr/bin/env bash
#
# prod-to-sqlite.sh — Load Railway production Postgres into the local SQLite dev DB.
#
# Streams prod down with pg_dump (bandwidth-bound, no ORM N+1), restores into a
# throwaway Docker Postgres, runs Django dumpdata against it locally (natural-key
# lookups are free over localhost), then loaddata's into a fresh db.sqlite3.
#
# An existing db.sqlite3 is backed up first and restored if the run fails; the
# Docker container is always torn down on exit.
#
# Requires: railway CLI (linked to flip-commons/prod), docker, jq, uv.
# Run from anywhere; paths resolve relative to the repo.

set -euo pipefail

# --- config ------------------------------------------------------------------
PG_IMAGE="postgres:17"                # pg_dump/pg_restore client + throwaway server
PG_SERVICE="Postgres"                 # Railway service to dump from
PG_ENV="prod"                         # Railway environment to dump from
CONTAINER="fc-prod-load-$$"           # throwaway container name, scoped to this PID
HOST_PORT="5433"                      # loopback host port → container's 5432
LOCAL_URL="postgresql://postgres:dev@127.0.0.1:${HOST_PORT}/postgres"   # host → container  # pragma: allowlist secret
CONTAINER_URL="postgresql://postgres:dev@localhost:5432/postgres"       # inside the container  # pragma: allowlist secret

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
WORK_DIR="$(mktemp -d)"
DUMP_FILE="${WORK_DIR}/prod.dump"
DATA_FILE="${WORK_DIR}/data.json"

# The local dev DB is the ONLY database this script writes to, pinned explicitly so
# migrate/loaddata can never resolve to an inherited DATABASE_URL (e.g. prod).
SQLITE_DB="${BACKEND_DIR}/db.sqlite3"
SQLITE_URL="sqlite:///${SQLITE_DB}"

# Rollback bookkeeping, consumed by cleanup().
BACKUP=""                             # path the old DB is moved to; set before the move, cleanup gates on the file existing
REBUILD_STARTED=0                     # 1 once db.sqlite3 is ours to (re)create
REBUILD_DONE=0                        # 1 only after loaddata succeeds

# --- helpers -----------------------------------------------------------------
log()    { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()    { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
manage() { DATABASE_URL="$1" uv run --project "$BACKEND_DIR" python "$BACKEND_DIR/manage.py" "${@:2}"; }

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"

  # Roll back an unfinished rebuild. BACKUP names a fresh path the original is moved
  # to, so the backup FILE existing proves this run safely stashed it there — restore
  # it whenever the file exists. With no such file, delete db.sqlite3 only once
  # REBUILD_STARTED, since until then it's the user's untouched original.
  [ "$REBUILD_DONE" -eq 1 ] && return
  if [ -n "$BACKUP" ] && [ -f "$BACKUP" ]; then
    log "Rebuild did not finish — restoring previous SQLite DB"
    rm -f "$SQLITE_DB"
    mv "$BACKUP" "$SQLITE_DB"
  elif [ "$REBUILD_STARTED" -eq 1 ]; then
    log "Rebuild did not finish — discarding partial SQLite DB"
    rm -f "$SQLITE_DB"
  fi
}
trap cleanup EXIT

# --- preflight ---------------------------------------------------------------
for cmd in railway docker jq uv; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing required command: $cmd"
done
docker info >/dev/null 2>&1 || die "Docker daemon isn't running — start Docker Desktop and retry"

# Guard the "dev only, never prod" contract: if the shell exports a non-SQLite
# DATABASE_URL (e.g. running under `railway run`, which injects prod's), refuse
# rather than risk migrate/loaddata writing there.
if [ -n "${DATABASE_URL:-}" ] && [ "${DATABASE_URL#sqlite}" = "${DATABASE_URL}" ]; then
  die "DATABASE_URL points at a non-SQLite database — refusing to run. Unset it (and don't run this under 'railway run') so the rebuild targets local SQLite only."
fi

# --- 1. read prod connection string (never printed) --------------------------
log "Reading prod connection string from Railway"
PROD_URL="$(railway variables -s "$PG_SERVICE" -e "$PG_ENV" --json | jq -r .DATABASE_PUBLIC_URL)"
[ -n "$PROD_URL" ] && [ "$PROD_URL" != "null" ] || die "could not read DATABASE_PUBLIC_URL from Railway service '$PG_SERVICE'"

# --- 2. stream prod down -----------------------------------------------------
log "Dumping prod Postgres"
docker run --rm "$PG_IMAGE" pg_dump -Fc -O -x "$PROD_URL" > "$DUMP_FILE"
log "Dump size: $(du -h "$DUMP_FILE" | cut -f1)"

# --- 3. restore into a throwaway local Postgres ------------------------------
log "Starting throwaway Postgres container"
docker run -d --rm --name "$CONTAINER" \
  -e POSTGRES_PASSWORD=dev -p "127.0.0.1:${HOST_PORT}:5432" "$PG_IMAGE" >/dev/null

log "Waiting for Postgres to accept connections"
ready=""
for _ in $(seq 30); do
  if docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ -n "$ready" ] || die "Postgres did not become ready in time"

log "Restoring dump into throwaway Postgres"
docker exec -i "$CONTAINER" pg_restore -O -x -d "$CONTAINER_URL" < "$DUMP_FILE"

# --- 4. dumpdata locally against the throwaway Postgres ----------------------
log "Running dumpdata against throwaway Postgres"
manage "$LOCAL_URL" dumpdata --natural-foreign --natural-primary \
  -e contenttypes -e auth.permission --indent 2 > "$DATA_FILE"

# --- 5. rebuild the local SQLite dev DB --------------------------------------
if [ -f "$SQLITE_DB" ]; then
  # Pick a path that doesn't already exist (backups persist across runs and PIDs
  # get reused), then assign BACKUP *before* the move. cleanup gates on the backup
  # file existing and mv is atomic, so an interrupt or a failed move can never lose
  # the original — it stays at either db.sqlite3 or the backup, and cleanup restores it.
  BACKUP="${BACKEND_DIR}/db.bak.$$.sqlite3"
  n=1
  while [ -e "$BACKUP" ]; do
    BACKUP="${BACKEND_DIR}/db.bak.$$-$n.sqlite3"
    n=$((n + 1))
  done
  log "Backing up existing SQLite DB to $(basename "$BACKUP")"
  mv "$SQLITE_DB" "$BACKUP"
fi

# Backup done (or none needed): db.sqlite3 is now ours to create, so any failure
# past here leaves an untrustworthy partial that cleanup() must roll back.
REBUILD_STARTED=1
log "Migrating fresh SQLite DB"
manage "$SQLITE_URL" migrate

log "Loading prod data into SQLite"
manage "$SQLITE_URL" loaddata "$DATA_FILE"

REBUILD_DONE=1
log "Done. Local db.sqlite3 now holds prod data."

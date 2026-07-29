#!/usr/bin/env bash
#
# prod-to-sqlite.sh — Load Railway production Postgres into the local SQLite dev DB.
#
# Pipes prod down with pg_dump (bandwidth-bound, no ORM N+1) into a throwaway Docker
# Postgres, scrubs user PII there, runs Django dumpdata against it locally
# (natural-key lookups are free over localhost), then loaddata's into a fresh
# db.sqlite3. The existing db.sqlite3 is backed up first and restored if the run fails.
#
# PRIVACY. Everything that outlives the run is de-identified: emails, names, password
# hashes and WorkOS links blanked, sessions deleted, before any of it is copied
# anywhere. Usernames are kept (public identity, not PII), as is the PII of the two
# developers who consented. Unscrubbed rows never reach the host filesystem either —
# every transfer is a pipe, and the one host file ($DATA_FILE) is written after the
# scrub. See backend/apps/accounts/management/commands/scrub_prod_dump.py, which also
# covers the WorkOS id carry-forward that keeps developer logins working.
#
# TWO CONTAINERS, because scrubbing a database does not scrub its storage: UPDATE and
# DELETE leave the original rows in dead MVCC tuples, and pg_restore's COPY puts them
# in WAL. So whatever receives the raw dump can never be what we keep. The snapshot is
# a separate container seeded from a dump taken after the scrub, and therefore never
# receives an unscrubbed byte — which is what makes it safe to pass to someone else.
#
# THE ARCHIVE COPY. The rebuilt dev DB is also written out as
# db.prod.patch-NNNN.YYYY-MM-DD.sqlite3 next to it — the same bytes db.sqlite3 has, under
# a name that records which data patch the catalog had reached and when prod was sampled.
# db.sqlite3 gets overwritten by the next run; these accumulate, and are what you keep or
# hand to someone.
#
# THE SNAPSHOT survives as 'flipcommons-postgres' on 127.0.0.1:5433: scrubbed and
# prod-shaped, for testing migrations and other SQL that SQLite can't stand in for.
# The previous one keeps serving until the download, scrub and dumpdata have all
# succeeded; it is then dropped to free the port, so a failure while its replacement
# is being built leaves no snapshot until the next run.
#
# Requires: railway CLI (linked to flip-commons/prod), docker, jq, uv.
# Run from anywhere; paths resolve relative to the repo.

set -euo pipefail

# --- config ------------------------------------------------------------------
PG_IMAGE="postgres:17"                      # pg_dump/pg_restore client + both servers
PG_SERVICE="Postgres"                       # Railway service to dump from
PG_ENV="prod"                               # Railway environment to dump from

# Fixed names, so debris from a run killed without its EXIT trap is findable by the
# next run. The cost is that concurrent runs would collide, which they already do
# over the ports and over db.sqlite3.
LOAD_CONTAINER="flipcommons-postgres-load"  # throwaway — receives the RAW prod dump
CAND_CONTAINER="flipcommons-postgres-new"   # throwaway — the snapshot under construction
KEEP_CONTAINER="flipcommons-postgres"       # kept — a COMPLETE snapshot, or absent

# Separate ports so both can be up at once: that is what lets the hand-off be a pipe
# rather than a file, and keeps the previous snapshot serving through the long part
# of the run.
LOAD_PORT="5434"
KEEP_PORT="5433"
LOAD_URL="postgresql://postgres:dev@127.0.0.1:${LOAD_PORT}/postgres"  # host → load  # pragma: allowlist secret
KEEP_URL="postgresql://postgres:dev@127.0.0.1:${KEEP_PORT}/postgres"  # host → keep  # pragma: allowlist secret
CONTAINER_URL="postgresql://postgres:dev@localhost:5432/postgres"     # inside either  # pragma: allowlist secret

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
WORK_DIR="$(mktemp -d)"
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

# start_postgres NAME HOST_PORT [extra docker run flags...]
start_postgres() {
  log "Starting Postgres container '$1' on 127.0.0.1:${2}"
  docker run -d --name "$1" -p "127.0.0.1:${2}:5432" \
    -e POSTGRES_PASSWORD=dev "${@:3}" "$PG_IMAGE" >/dev/null
  for _ in $(seq 30); do
    docker exec "$1" pg_isready -U postgres >/dev/null 2>&1 && return 0
    sleep 1
  done
  die "Postgres in '$1' did not become ready in time"
}

# -v is load-bearing: postgres:17 declares a VOLUME for its data directory, so a
# container started without one gets an anonymous volume. A plain `docker rm` detaches
# it and orphans a full copy of the database, invisibly. Every removal goes through
# here so that can't be forgotten at one call site.
drop_container()   { docker rm -f -v "$@" >/dev/null 2>&1 || true; }
drop_disposables() { drop_container "$LOAD_CONTAINER" "$CAND_CONTAINER"; }

# port_taken PORT — is anything on the host already listening there? bash's own /dev/tcp,
# so this adds nothing to the required-command list. The subshell confines the fd.
port_taken() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# require_port PORT [CONTAINER-ALLOWED-TO-HOLD-IT]
# A stray Postgres of your own on either port would otherwise surface as a failure from
# start_postgres — and on KEEP_PORT that lands *after* the previous snapshot has been
# dropped, so someone else's container costs you the snapshot you already had. Cheap to
# catch here instead.
require_port() {
  port_taken "$1" || return 0
  # The kept container legitimately holds KEEP_PORT between runs: it's the previous
  # snapshot, and it gets dropped before its replacement is started.
  if [ -n "${2:-}" ] && [ -n "$(docker ps -q -f "name=^${2}$" -f "publish=${1}")" ]; then
    return 0
  fi
  die "127.0.0.1:$1 is already in use by something other than this script — free that port and retry. This script needs $LOAD_PORT for the throwaway loader and $KEEP_PORT for the kept snapshot."
}

# sqlite_patch_high_water DB — highest applied data-patch number, zero-padded, or empty
# if none has been applied. The applied-ledger is IngestRun rows that succeeded with a
# patch_id, and patch_id is the NNNN-slug stem, so the leading four digits are the
# number. Read with stdlib sqlite3 rather than manage.py, whose startup chatter would
# have to be filtered back out of the captured value. 'success' is bound rather than
# quoted because this whole program is inside a single-quoted shell string.
sqlite_patch_high_water() {
  uv run --project "$BACKEND_DIR" python -c '
import sqlite3, sys

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
n = con.execute(
    "select max(cast(substr(patch_id, 1, 4) as integer)) from provenance_ingestrun"
    " where status = ? and patch_id is not null",
    ("success",),
).fetchone()[0]
print("" if n is None else f"{n:04d}")
' "$1"
}

# sqlite_archive SRC DST — consistent copy of a possibly-live SQLite DB. VACUUM INTO
# rather than cp because the dev server may hold db.sqlite3 open, and copying a
# rollback-journal database mid-write can produce a torn file; it also compacts. VACUUM
# INTO refuses to overwrite, which is what the rm is for.
sqlite_archive() {
  rm -f "$2"
  uv run --project "$BACKEND_DIR" python -c '
import sqlite3, sys

sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).execute(
    "vacuum into ?", (sys.argv[2],)
)
' "$1" "$2"
}

cleanup() {
  # Both disposables go on every exit path: the loader holds a raw copy of prod, and a
  # half-restored candidate is worse than no snapshot. After a successful promote the
  # candidate name no longer resolves, so this is a no-op — which is why no "did it
  # finish?" flag is needed. $KEEP_CONTAINER is never touched here: on an early
  # failure the container under that name is the previous run's good snapshot.
  drop_disposables
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

# Debris from a run that died without its EXIT trap (SIGKILL, a Docker crash, power
# loss) still holds production data and squats the ports. Clear it before the checks
# below, which can themselves abort and leave it sitting there another day.
drop_disposables

# Guard the "dev only, never prod" contract: if the shell exports a non-SQLite
# DATABASE_URL (e.g. running under `railway run`, which injects prod's), refuse
# rather than risk migrate/loaddata writing there.
if [ -n "${DATABASE_URL:-}" ] && [ "${DATABASE_URL#sqlite}" = "${DATABASE_URL}" ]; then
  die "DATABASE_URL points at a non-SQLite database — refusing to run. Unset it (and don't run this under 'railway run') so the rebuild targets local SQLite only."
fi

# Checked after the sweep above, which is what releases LOAD_PORT if a dead run was
# still squatting it.
require_port "$LOAD_PORT"
require_port "$KEEP_PORT" "$KEEP_CONTAINER"

# The remaining checks all turn a post-download failure into an instant one. The
# `manage` call is the first of the run, so it also resolves the uv environment
# (syncing deps if needed) and catches a checkout predating scrub_prod_dump; `help`
# loads Django and the command registry but opens no database connection.
[ -w "$BACKEND_DIR" ] || die "$BACKEND_DIR isn't writable — the rebuild can't create db.sqlite3 there"
log "Checking the backend toolchain"
if ! preflight_err="$(manage "$SQLITE_URL" help scrub_prod_dump 2>&1 >/dev/null)"; then
  printf '%s\n' "$preflight_err" >&2
  die "backend management commands aren't runnable, or scrub_prod_dump is missing from this checkout — try 'make bootstrap'"
fi

# --- 1. read prod connection string (never printed) --------------------------
log "Reading prod connection string from Railway"
PROD_URL="$(railway variables -s "$PG_SERVICE" -e "$PG_ENV" --json | jq -r .DATABASE_PUBLIC_URL)"
[ -n "$PROD_URL" ] && [ "$PROD_URL" != "null" ] || die "could not read DATABASE_PUBLIC_URL from Railway service '$PG_SERVICE'"

# --- 2. start the throwaway load container -----------------------------------
# `--rm` makes it disposable at the daemon level: whenever it stops, Docker removes
# the container and its volume, so quitting Docker or rebooting takes the raw prod
# copy with it. It does not cover a SIGKILLed run on a machine that stays up —
# nothing stopped the container — which is what preflight's sweep is for.
start_postgres "$LOAD_CONTAINER" "$LOAD_PORT" --rm

# --- 3. stream prod into the load container ----------------------------------
# A pipe rather than a staged file, so an unscrubbed dump can't outlive a SIGKILLed
# run on disk. pg_restore reads a -Fc archive from a non-seekable stream fine, and
# pipefail is what makes a failing pg_dump abort the script rather than quietly
# restoring a truncated archive.
log "Streaming prod Postgres into the load container"
docker run --rm "$PG_IMAGE" pg_dump -Fc -O -x "$PROD_URL" \
  | docker exec -i "$LOAD_CONTAINER" pg_restore -O -x -d "$CONTAINER_URL"
log "Restored size: $(docker exec "$LOAD_CONTAINER" psql -U postgres -tAc \
  "SELECT pg_size_pretty(pg_database_size('postgres'))")"

# --- 4. scrub PII, inside the load container ---------------------------------
# Before dumpdata, so PII reaches neither $DATA_FILE nor db.sqlite3 and the
# --natural-foreign references (User.natural_key() is (email,)) are generated from
# the scrubbed addresses. db.sqlite3 is still the outgoing DB at this point, which is
# what makes it readable as the carry-forward source for the developers' WorkOS ids.
log "Scrubbing user PII"
manage "$LOAD_URL" scrub_prod_dump --carry-forward-from "$SQLITE_DB"

# --- 5. dumpdata against the load container ----------------------------------
# The session exclusion is belt-and-braces — scrub_prod_dump deletes those rows — so
# two independent things must fail before a session payload reaches db.sqlite3.
log "Running dumpdata against the load container"
manage "$LOAD_URL" dumpdata --natural-foreign --natural-primary \
  -e contenttypes -e auth.permission -e sessions.session --indent 2 > "$DATA_FILE"

# --- 6. hand the scrubbed data to a fresh container --------------------------
# The previous snapshot is dropped only now, once the long, failure-prone work is
# behind us. It has to go before the candidate starts, because a published port is
# fixed at creation and the candidate must be born on the port it will serve — so a
# failure between here and the promote below does leave you with no snapshot.
log "Replacing the previous snapshot container"
drop_container "$KEEP_CONTAINER"

# Built under the candidate name with no restart policy, so a run killed during the
# restore leaves something inert for preflight to clear, and nothing answering to the
# canonical name is ever incomplete. `--rm` would be wrong here despite looking tidy:
# AutoRemove is fixed at creation and survives the rename, so it would follow the
# container into its kept life and destroy the snapshot on the next Docker shutdown.
start_postgres "$CAND_CONTAINER" "$KEEP_PORT"

log "Copying the scrubbed database into it"
docker exec "$LOAD_CONTAINER" pg_dump -Fc -O -x "$CONTAINER_URL" \
  | docker exec -i "$CAND_CONTAINER" pg_restore -O -x -d "$CONTAINER_URL"

# The rename publishes it. The restart policy goes on last — `docker update` is the
# only way to set it after creation — so a container that never got here cannot
# resurrect itself.
log "Promoting to '$KEEP_CONTAINER'"
docker rename "$CAND_CONTAINER" "$KEEP_CONTAINER"
docker update --restart unless-stopped "$KEEP_CONTAINER" >/dev/null

# Explicitly, rather than leaving it to cleanup(), so the raw prod copy is gone before
# the SQLite rebuild rather than after it.
log "Destroying the load container and its volume"
drop_container "$LOAD_CONTAINER"

# --- 7. rebuild the local SQLite dev DB --------------------------------------
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

# --- 8. archive the same build under a self-describing name -------------------
# db.sqlite3 has to keep its name for Django to find it, so the build is written a second
# time as db.prod.patch-NNNN.YYYY-MM-DD.sqlite3: the patch high-water mark says how
# current the catalog is, the date says when prod was sampled. Identical names therefore
# mean identical prod state, so a re-run on a day that brought no new patches overwrites
# instead of accumulating near-duplicates.
#
# After REBUILD_DONE, deliberately: db.sqlite3 is complete and correct by this point, and
# a failure to write the archive must not roll it back. It does still abort the run, so
# the archive can't be silently missing.
PATCH="$(sqlite_patch_high_water "$SQLITE_DB")"
ARCHIVE="${BACKEND_DIR}/db.prod.patch-${PATCH:-none}.$(date +%Y-%m-%d).sqlite3"
log "Archiving the build as $(basename "$ARCHIVE")"
sqlite_archive "$SQLITE_DB" "$ARCHIVE"

log "Done. Local db.sqlite3 now holds prod data, with user PII scrubbed."
log "Archived alongside it as $(basename "$ARCHIVE")"
log "Scrubbed Postgres kept as '${KEEP_CONTAINER}' — docker exec -it ${KEEP_CONTAINER} psql -U postgres"
log "  (that needs no host psql; clients that have one can use ${KEEP_URL})"

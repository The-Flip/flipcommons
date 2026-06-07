"""Pull ingest sources from R2 and run a full fresh-DB bootstrap.

Convenience command for Railway: one command to download data, run the full
``ingest_all`` seed pipeline, then replay the data-patch log (``ingest_patches``)
so the database reaches the same state as production.

**Fresh / reset databases only.** Do NOT run this against an already-seeded
production DB — re-running the seed re-asserts the original source claims and
would clobber same-source patch corrections (and the patch ledger would then
skip re-applying them). To apply new corrections to a live DB, run
``pull_ingest_sources`` + ``ingest_patches`` instead (see docs/Ingest.md).

Usage (Railway SSH):
    .venv/bin/python manage.py pull_and_ingest

Usage (local):
    uv run python manage.py pull_and_ingest --dest ../data/ingest_sources
"""

from __future__ import annotations

import argparse
import os
import tempfile
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

_DEFAULT_DEST = os.path.join(tempfile.gettempdir(), "ingest_sources")


class Command(BaseCommand):
    help = (
        "Fresh-DB bootstrap: pull ingest sources from R2, run ingest_all, then "
        "apply the data-patch log. Do not run on an already-seeded database."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dest",
            default=_DEFAULT_DEST,
            help=f"Local directory to download into (default: {_DEFAULT_DEST}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run ingest_all without --write (rolls back changes).",
        )

    def handle(
        self,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        dest = options["dest"]
        write = not options["dry_run"]

        self.stdout.write(
            self.style.MIGRATE_HEADING("Pulling ingest sources from R2...")
        )
        call_command(
            "pull_ingest_sources",
            dest=dest,
            stdout=self.stdout,
            stderr=self.stderr,
        )

        self.stdout.write(self.style.MIGRATE_HEADING("Running ingest pipeline..."))
        kwargs: dict[str, str | bool] = {
            "ipdb": f"{dest}/ipdb_xantari.json",
            "opdb": f"{dest}/opdb_export_machines.json",
            "export_dir": f"{dest}/pindata/",
        }
        if write:
            kwargs["write"] = True

        call_command(
            "ingest_all",
            stdout=self.stdout,
            stderr=self.stderr,
            **kwargs,
        )

        # Replay the patch log on top of the fresh seed so the DB matches prod.
        # Only in write mode: a dry-run ingest_all rolls back the seed, leaving
        # nothing for the patches to resolve against. The command no-ops if no
        # patch files were pulled.
        if write:
            self.stdout.write(self.style.MIGRATE_HEADING("Applying data patches..."))
            call_command(
                "ingest_patches",
                patches_dir=f"{dest}/pindata/patches",
                stdout=self.stdout,
                stderr=self.stderr,
            )
        else:
            self.stdout.write(
                "[dry-run] Skipping data patches — they need a committed seed."
            )

        self.stdout.write(self.style.SUCCESS("Done."))

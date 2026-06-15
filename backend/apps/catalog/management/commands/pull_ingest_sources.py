"""Download seed ingest source files from Cloudflare R2.

The R2 bucket has several manifests:
  - manifest.json            — root-level ingest sources (IPDB, OPDB, etc.),
                               published by pinexplore.
  - pindata/manifest.json    — catalog seed export files, published by pindata.

This command fetches both and downloads the files the seed ingest needs. Data
patches are published separately by flippatch and pulled by `pull_patches`.

The shared R2 download/checksum logic lives in
``apps.catalog.ingestion.r2_pull``.

Usage (local):
    uv run python manage.py pull_ingest_sources --dest ../data/ingest_sources

Usage (Railway):
    .venv/bin/python manage.py pull_ingest_sources --dest /tmp/ingest_sources
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from django.core.management.base import BaseCommand

from apps.catalog.ingestion.r2_pull import DEFAULT_DEST, download_manifest

# Only download these root-level files from the ingest-sources manifest.
_NEEDED_FILES = {
    "ipdb_xantari.json",
    "opdb_export_machines.json",
    "opdb_changelog.json",
}

# Manifests to fetch: (manifest path, local prefix, needed-files filter).
# - Root manifest: store entries as-is under dest, but only _NEEDED_FILES.
# - pindata/ manifest: store under pindata/ locally, download everything.
_MANIFESTS = [
    ("manifest.json", "", _NEEDED_FILES),
    ("pindata/manifest.json", "pindata/", None),
]


class Command(BaseCommand):
    help = "Download seed ingest source files from Cloudflare R2."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--url",
            default=os.environ.get(
                "R2_PUBLIC_URL", "https://pub-8a5220445534421c879b6ff9ede350f1.r2.dev"
            ),
            help="Base URL of the R2 public bucket (default: R2_PUBLIC_URL env var).",
        )
        parser.add_argument(
            "--dest",
            default=DEFAULT_DEST,
            help=f"Local directory to download into (default: {DEFAULT_DEST}).",
        )

    def handle(
        self,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        base_url = options["url"].rstrip("/")
        dest = options["dest"]

        downloaded = up_to_date = ignored = 0
        for manifest_path, local_prefix, needed in _MANIFESTS:
            counts = download_manifest(
                base_url=base_url,
                manifest_path=manifest_path,
                local_prefix=local_prefix,
                dest=dest,
                needed_files=needed,
                log=self.stdout.write,
                warn=lambda msg: self.stdout.write(self.style.WARNING(msg)),
            )
            downloaded += counts.downloaded
            up_to_date += counts.up_to_date
            ignored += counts.ignored

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {downloaded} downloaded, {up_to_date} up-to-date, {ignored} skipped."
            )
        )

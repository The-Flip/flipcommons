"""Download data patches from Cloudflare R2.

Data patches are authored and published by the **flippatch** repo. flippatch's
`make push` ships them under the ``flippatch/`` prefix of the bucket, with
``flippatch/manifest.json`` listing the patch files at
``flippatch/patches/NNNN-slug.yaml``.

This command fetches that manifest and downloads the patches into
``<dest>/flippatch/patches/`` — the default dir `ingest_patches` reads from.

The R2 download/checksum logic lives in ``apps.claim_ingest.r2_pull``.

Usage (local):
    uv run python manage.py pull_patches --dest ../data/ingest_sources

Usage (Railway):
    .venv/bin/python manage.py pull_patches --dest /tmp/ingest_sources
"""

from __future__ import annotations

import argparse
import os
from typing import Any
from urllib.error import HTTPError

from django.core.management.base import BaseCommand, CommandError

from apps.claim_ingest.r2_pull import DEFAULT_DEST, download_manifest


class Command(BaseCommand):
    help = "Download data patches from Cloudflare R2 (the flippatch/ prefix)."

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

        # flippatch/manifest.json lists files relative to flippatch/ (e.g.
        # "patches/0001-foo.yaml"); store them under flippatch/ locally.
        # required=True: this manifest is the sole source of patches, so a 404
        # is a real failure — fail loudly rather than report "0 downloaded".
        try:
            counts = download_manifest(
                base_url=base_url,
                manifest_path="flippatch/manifest.json",
                local_prefix="flippatch/",
                dest=dest,
                needed_files=None,
                required=True,
                log=self.stdout.write,
                warn=lambda msg: self.stdout.write(self.style.WARNING(msg)),
            )
        except HTTPError as e:
            raise CommandError(
                f"Could not fetch flippatch/manifest.json from {base_url} "
                f"(HTTP {e.code}). The patches were not pulled."
            ) from e

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {counts.downloaded} downloaded, {counts.up_to_date} up-to-date."
            )
        )

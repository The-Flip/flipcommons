"""Backfill recognition hosts from existing root homepage links.

Paired with the ``CitationSourceRootDomain`` table: derive one recognition host
per root from the hosts already declared as ``homepage`` links, so they keep
driving recognition under the new model.

Self-contained by design (matches ``provenance/0004``): host normalization is
inlined rather than importing ``apps.citation.hosts``, so the frozen migration
never drifts with that module.

The empty duplicate ``This Week in Pinball (TWiP)`` root (root 49 in prod),
whose ``twip.kineticist.com`` homepage collides with the populated ``This Week
in Pinball`` root, is deleted by hand before this runs — a one-off prod cleanup,
not migration logic. If it is still present the collision audit below fails loud
rather than mis-assigning the host.

The table is empty before this migration, so the reverse simply empties it again
— restoring the pre-migration state and keeping reverse-then-reapply clean.
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from django.db import migrations


def _normalize_host(url: str) -> str | None:
    """Recognition host for a URL, or ``None``. Mirrors ``hosts.normalize_host``."""
    hostname = urlparse(url).hostname
    if not hostname:
        return None
    return hostname.strip().lower().rstrip(".").removeprefix("www.")


def backfill_root_domains(apps, schema_editor) -> None:
    CitationSourceLink = apps.get_model("citation", "CitationSourceLink")
    CitationSourceRootDomain = apps.get_model("citation", "CitationSourceRootDomain")

    # Map every root homepage host to the root(s) that declare it. The same root
    # declaring a host twice (http + https) is fine; two *different* roots is not.
    # No source_type filter — any root with a homepage host gets a recognition
    # row, matching current recognition (the any-root decision).
    host_to_roots: dict[str, set[int]] = defaultdict(set)
    homepage_links = CitationSourceLink.objects.filter(
        link_type="homepage", citation_source__parent__isnull=True
    ).values_list("citation_source_id", "url")
    for source_id, url in homepage_links:
        host = _normalize_host(url)
        if host is not None:
            host_to_roots[host].add(source_id)

    # Audit before any insert: a host owned by >1 root would trip the `host`
    # unique mid-loop and surface as an opaque IntegrityError. Fail loud here.
    # (The empty TWiP duplicate must be deleted by hand first — see module docs.)
    collisions = {
        host: sorted(roots) for host, roots in host_to_roots.items() if len(roots) > 1
    }
    if collisions:
        raise RuntimeError(
            "Cannot backfill CitationSourceRootDomain: these hosts are claimed by "
            f"more than one root (resolve the duplicates first): {collisions}"
        )

    CitationSourceRootDomain.objects.bulk_create(
        CitationSourceRootDomain(source_id=next(iter(roots)), host=host)
        for host, roots in host_to_roots.items()
    )


def remove_root_domains(apps, schema_editor) -> None:
    # The table was empty before this migration — restore that. Reapply-safe:
    # nothing left to collide with the host unique on a forward re-run.
    CitationSourceRootDomain = apps.get_model("citation", "CitationSourceRootDomain")
    CitationSourceRootDomain.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("citation", "0004_citationsourcerootdomain"),
    ]

    operations = [
        migrations.RunPython(backfill_root_domains, remove_root_domains),
    ]

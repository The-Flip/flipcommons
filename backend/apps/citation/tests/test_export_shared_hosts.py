"""The analytics shared-host codegen channel and its drift guard.

The parity test is the point of the channel. `make codegen` is a local step CI
doesn't run, so without it, adding a host to ``SHARED_HOSTS`` and forgetting to
regenerate leaves the analytics layer calling that host ordinary — which keeps
its bare recognition rows eligible there and nowhere else, so
``citation_root_for_url()`` attributes a tenant's URL to whoever registered the
host while the app resolves it to nothing. Byte parity, because nothing
reformats this file after the generator writes it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.citation.hosts import Host, normalize_host
from apps.citation.management.commands.export_shared_hosts import OUTPUT_PATH
from apps.citation.shared_hosts import SHARED_HOSTS, shared_host_for

COMMITTED_SQL = Path(settings.BASE_DIR).parent / OUTPUT_PATH


@pytest.fixture
def output(tmp_path: Path, settings) -> str:
    """Run the command into a temp tree and return the generated SQL."""
    settings.BASE_DIR = tmp_path / "backend"
    call_command("export_shared_hosts")
    return (tmp_path / OUTPUT_PATH).read_text()


def test_every_declared_host_gets_a_row(output: str) -> None:
    """A missing host is invisible until a URL on it is misattributed."""
    for spec in SHARED_HOSTS:
        for host in spec.hosts:
            assert f"('{host}'" in output, host


def test_no_host_is_emitted_that_is_not_declared(output: str) -> None:
    """The other direction: a row here that the app would call ordinary."""
    block = output.split("SELECT * FROM (VALUES", 1)[1].split(") AS t(", 1)[0]
    emitted = [line.split("'")[1] for line in block.splitlines() if "'" in line]
    assert emitted
    for host in emitted:
        assert shared_host_for(Host(host)) is not None, host


def test_emitted_hosts_are_normalized(output: str) -> None:
    """The SQL side compares against ``host_norm(h)``, which normalizes its input.

    A stored host that isn't already normalized would simply never match. The
    table's own import-time validation asserts this too; asserting it against
    the generated text keeps the guarantee attached to what SQL actually reads.
    """
    block = output.split("SELECT * FROM (VALUES", 1)[1].split(") AS t(", 1)[0]
    for line in block.splitlines():
        if "'" in line:
            host = line.split("'")[1]
            assert normalize_host(host) == host, host


def test_committed_file_matches_the_declaration(output: str) -> None:
    """`make codegen` was run after the last SHARED_HOSTS change."""
    assert output == COMMITTED_SQL.read_text(), (
        f"{OUTPUT_PATH} is stale — run `make codegen`."
    )

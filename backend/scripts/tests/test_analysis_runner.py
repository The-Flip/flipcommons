from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

DUCKDB = shutil.which("duckdb")
RUNNER = Path(__file__).parents[3] / "scripts" / "analysis" / "analysis"


def query(database: Path, sql: str) -> str:
    assert DUCKDB is not None
    result = subprocess.run(
        [DUCKDB, "-noheader", "-list", database, sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(DUCKDB is None, reason="DuckDB CLI is not installed")
def test_browse_materializes_public_relations_and_replaces_previous_output(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "example.sql"
    output = tmp_path / "example.browse.duckdb"
    analysis.write_text(
        """
        CREATE VIEW visible AS SELECT 1 AS value;
        COMMENT ON VIEW visible IS 'One row, for the counter to find.';
        CREATE TABLE materialized AS SELECT 2 AS value;
        CREATE VIEW _private AS SELECT 2 AS value;
        """,
    )

    first = subprocess.run(
        [RUNNER, "browse", analysis],
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.exists()
    assert first.stdout.strip() == f"wrote {output} (2 public relations, 1 documented)"
    assert (
        query(output, "SELECT table_name FROM duckdb_tables() ORDER BY table_name;")
        == "materialized\nvisible"
    )
    assert query(output, "SELECT value FROM visible;") == "1"

    analysis.write_text(
        """
        CREATE VIEW visible AS SELECT 3 AS value;
        CREATE VIEW added AS SELECT 4 AS value;
        """,
    )
    second = subprocess.run(
        [RUNNER, "browse", analysis],
        check=True,
        capture_output=True,
        text=True,
    )

    assert second.stdout.strip() == f"wrote {output} (2 public relations, 0 documented)"
    assert (
        query(output, "SELECT table_name FROM duckdb_tables() ORDER BY table_name;")
        == "added\nvisible"
    )
    assert query(output, "SELECT value FROM visible;") == "3"

    analysis.write_text(
        "CREATE VIEW visible AS SELECT error('refresh failed') AS value;",
    )
    failed = subprocess.run(
        [RUNNER, "browse", analysis],
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode != 0
    assert query(output, "SELECT value FROM visible;") == "3"
    assert list(tmp_path.glob("*.tmp.*")) == []

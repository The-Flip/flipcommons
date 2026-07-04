"""OPDB scheme tests: its declared example table plus the canonical form.

OPDB keys machine records by a slug id. ``EXAMPLES`` covers the host/scheme
variants; the generic invariants live in ``test_conformance``. Pure — no
database.
"""

from apps.citation.citation_types import SCHEME_SPECS

from .example_data import SchemeExamples

MID = "GRhX5"

opdb = SCHEME_SPECS["opdb"]

EXAMPLES = SchemeExamples(
    example_identifier=MID,
    valid_urls=(
        f"https://www.opdb.org/machines/{MID}",  # www
        f"http://opdb.org/machines/{MID}",
        f"https://opdb.org/machines/{MID}?ref=share",  # trailing query
    ),
    invalid_urls=(
        f"https://notopdb.org/machines/{MID}",  # look-alike host
        f"https://opdb.org.evil.com/machines/{MID}",  # host as a prefix label
        "https://opdb.org/machines/",  # no id
        "https://www.ipdb.org/machine.cgi?id=4443",  # wrong site
        f"https://example.com/{MID}",  # bare id buried in a foreign URL
    ),
)


def test_canonical_url_is_the_machines_page() -> None:
    assert opdb.canonical_url(MID) == f"https://opdb.org/machines/{MID}"

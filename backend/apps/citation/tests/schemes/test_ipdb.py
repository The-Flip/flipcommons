"""IPDB scheme tests: its declared example table plus the canonical form.

IPDB is the minimal scheme — one numeric-id URL shape. ``EXAMPLES`` covers the
host/scheme variants; the generic invariants live in ``test_conformance``. Pure
— no database.
"""

from apps.citation.citation_types import SCHEME_SPECS

from .example_data import SchemeExamples

MID = "4443"

ipdb = SCHEME_SPECS["ipdb"]

EXAMPLES = SchemeExamples(
    example_identifier=MID,
    valid_urls=(
        f"https://ipdb.org/machine.cgi?id={MID}",  # no www
        f"http://www.ipdb.org/machine.cgi?id={MID}",
        f"https://www.ipdb.org/machine.cgi?id={MID}&more=1",  # trailing param
    ),
    invalid_urls=(
        f"https://notipdb.org/machine.cgi?id={MID}",  # look-alike host
        f"https://ipdb.org.evil.com/machine.cgi?id={MID}",  # host as a prefix label
        "https://www.ipdb.org/machine.cgi?id=",  # no id
        f"https://opdb.org/machines/{MID}",  # wrong site
        f"https://example.com/{MID}",  # bare id buried in a foreign URL
    ),
)


def test_canonical_url_is_the_machine_cgi_page() -> None:
    assert ipdb.canonical_url(MID) == f"https://www.ipdb.org/machine.cgi?id={MID}"

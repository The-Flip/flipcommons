"""OPDB scheme examples: machine records keyed by a slug id.

Pure data; the shared harnesses (``test_examples``, ``test_conformance``,
``test_db_roundtrip``) do all the driving.
"""

from .example_data import SchemeExamples

MID = "GRhX5"

EXAMPLES = SchemeExamples(
    example_identifier=MID,
    canonical_url=f"https://opdb.org/machines/{MID}",
    valid_urls=(
        f"https://www.opdb.org/machines/{MID}",  # www
        f"http://opdb.org/machines/{MID}",
        f"https://opdb.org/machines/{MID}?ref=share",  # trailing query
        f"https://opdb.org/machines/{MID}/",  # single trailing slash tolerated
    ),
    invalid_urls=(
        f"https://notopdb.org/machines/{MID}",  # look-alike host
        f"https://opdb.org.evil.com/machines/{MID}",  # host as a prefix label
        "https://opdb.org/machines/",  # no id
        f"https://opdb.org/machines/{MID}/extra",  # extra path segment after the id
        f"https://opdb.org/machines/{MID}.html",  # foreign tail must not truncate
        "https://www.ipdb.org/machine.cgi?id=4443",  # wrong site
        f"https://example.com/{MID}",  # bare id buried in a foreign URL
    ),
)

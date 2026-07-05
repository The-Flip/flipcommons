"""IPDB scheme examples: the minimal scheme — one numeric-id URL shape.

Pure data; the shared harnesses (``test_examples``, ``test_conformance``,
``test_db_roundtrip``) do all the driving.
"""

from .example_data import SchemeExamples

MID = "4443"

EXAMPLES = SchemeExamples(
    example_identifier=MID,
    canonical_url=f"https://www.ipdb.org/machine.cgi?id={MID}",
    valid_urls=(
        f"https://ipdb.org/machine.cgi?id={MID}",  # no www
        f"http://www.ipdb.org/machine.cgi?id={MID}",
        f"https://www.ipdb.org/machine.cgi?id={MID}&more=1",  # trailing param
        f"https://www.ipdb.org/machine.cgi?more=1&id={MID}",  # id after another param
    ),
    invalid_urls=(
        f"https://notipdb.org/machine.cgi?id={MID}",  # look-alike host
        f"https://ipdb.org.evil.com/machine.cgi?id={MID}",  # host as a prefix label
        "https://www.ipdb.org/machine.cgi?id=",  # no id
        f"https://www.ipdb.org/machine.cgi?id={MID}abc",  # id must not truncate
        f"https://www.ipdb.org/machine.cgi?id={MID}-",  # ditto, id-like tail char
        f"https://opdb.org/machines/{MID}",  # wrong site
        f"https://example.com/{MID}",  # bare id buried in a foreign URL
    ),
)

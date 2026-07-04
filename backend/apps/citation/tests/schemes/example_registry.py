"""The scheme example registry: every scheme's ``SchemeExamples``, by key.

Shared by both harnesses — ``test_examples`` drives the URL tables, and
``test_conformance`` reads each scheme's ``example_identifier`` as its
round-trip seed. Lives in its own (non-test) module so neither harness has to
import the other, and mirrors the production ``_SCHEMES`` registration: one
line per scheme, greppable, held to the registered scheme set by the assert
below (every scheme has a table; no table names an unregistered scheme).
"""

from apps.citation.citation_types import SCHEME_SPECS

from . import test_ipdb, test_opdb, test_tiktok, test_vimeo, test_x, test_youtube
from .example_data import SchemeExamples

SCHEME_EXAMPLES: dict[str, SchemeExamples] = {
    "ipdb": test_ipdb.EXAMPLES,
    "opdb": test_opdb.EXAMPLES,
    "youtube": test_youtube.EXAMPLES,
    "vimeo": test_vimeo.EXAMPLES,
    "tiktok": test_tiktok.EXAMPLES,
    "x": test_x.EXAMPLES,
}

assert SCHEME_EXAMPLES.keys() == set(SCHEME_SPECS), (
    "SCHEME_EXAMPLES must cover exactly the registered schemes; "
    f"missing={sorted(set(SCHEME_SPECS) - SCHEME_EXAMPLES.keys())}, "
    f"unregistered={sorted(SCHEME_EXAMPLES.keys() - set(SCHEME_SPECS))}"
)

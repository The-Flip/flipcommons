"""YouTube scheme tests: its declared example table plus bespoke assertions.

YouTube's video id is reachable through many URL shapes (``watch?v=``,
``youtu.be``, ``/shorts/``, ``/embed/``, ``/live/``, mobile), all collapsing to
one canonical 11-char id — the regex doing that collapse is the risky part, so
``EXAMPLES`` pins the shapes as data. Start times ride in the ``t=``/``start=``
query params. The generic invariants live in ``test_conformance``; the exact
canonical and deep-link strings a URL table can't express stay here. Pure — no
database.
"""

from apps.citation.citation_types import SCHEME_SPECS

from .example_data import SchemeExamples, StartTimeCase

VID = "dQw4w9WgXcQ"

youtube = SCHEME_SPECS["youtube"]

EXAMPLES = SchemeExamples(
    valid_urls=(
        f"https://youtube.com/watch?v={VID}",  # no www
        f"http://www.youtube.com/watch?v={VID}",
        f"https://m.youtube.com/watch?v={VID}",  # mobile
        f"https://youtu.be/{VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube.com/live/{VID}",
        # Trailing/extra params are ignored; the id still collapses.
        f"https://youtu.be/{VID}?si=AbCdEf",
        f"https://www.youtube.com/watch?v={VID}&t=42s",
        f"https://www.youtube.com/watch?list=PL123&v={VID}",
        f"https://www.youtube.com/shorts/{VID}?feature=share",
        f"https://youtu.be/{VID}/",  # single trailing slash tolerated
        f"https://www.youtube.com/watch?v={VID}#t=30",  # fragment after the id
    ),
    invalid_urls=(
        "dQw4w9WgXc",  # 10 chars — too short for a bare id
        "dQw4w9WgXcQX",  # 12 chars — too long
        f"https://youtu.be/{VID}X",  # 12-char URL id must not truncate to 11
        f"https://www.youtube.com/watch?v={VID}X",  # ditto, watch shape
        f"https://notyoutube.com/watch?v={VID}",  # look-alike host
        f"https://www.notyoutube.com/watch?v={VID}",  # look-alike host + www
        f"https://youtube.com.evil.com/watch?v={VID}",  # host as a prefix label
        "https://www.ipdb.org/machine.cgi?id=4443",  # wrong site
        f"https://example.com/{VID}",  # bare id buried in a foreign URL
        f"https://www.youtube.com/watch?foo=bar#&v={VID}",  # v= only in the fragment
        f"https://youtu.be/{VID}/extra",  # extra path segment after the id
        f"https://www.youtube.com/embed/{VID}/extra",  # ditto, embed shape
        "not a url or id",
    ),
    start_time_cases=(
        StartTimeCase(f"https://www.youtube.com/watch?v={VID}&t=95", 95),
        StartTimeCase(f"https://www.youtube.com/watch?v={VID}&t=95s", 95),
        StartTimeCase(f"https://www.youtube.com/watch?v={VID}&t=1h2m3s", 3723),
        StartTimeCase(f"https://youtu.be/{VID}?t=95", 95),
        StartTimeCase(f"https://www.youtube.com/embed/{VID}?start=95", 95),  # embed
        StartTimeCase(f"https://www.youtube.com/shorts/{VID}?t=2m", 120),
        StartTimeCase(f"https://www.youtube.com/watch?v={VID}", None),  # no time
        StartTimeCase(f"https://www.youtube.com/watch?v={VID}&t=0", None),  # 0 = start
        StartTimeCase(f"https://www.youtube.com/watch?v={VID}#t=30", None),  # fragment
    ),
)


def test_canonical_url_is_the_watch_page() -> None:
    assert youtube.canonical_url(VID) == f"https://www.youtube.com/watch?v={VID}"


def test_deep_link_uses_the_t_query_param() -> None:
    assert youtube.deep_link is not None
    assert (
        youtube.deep_link(VID, 3723) == f"https://www.youtube.com/watch?v={VID}&t=3723s"
    )

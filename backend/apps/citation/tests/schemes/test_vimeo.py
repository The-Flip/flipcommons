"""Vimeo scheme examples: numeric ids, unlisted-hash tails, fragment seeks.

The unlisted-access hash is an access token, not identity, so it drops out
of the identifier; start times ride in the ``#t=`` fragment (not the query),
and the deep link seeks the same way. Pure data; the shared harnesses do all
the driving.
"""

from .example_data import DeepLinkCase, SchemeExamples, StartTimeCase

VID = "347119375"

EXAMPLES = SchemeExamples(
    example_identifier=VID,
    canonical_url=f"https://vimeo.com/{VID}",  # bare watch page, no www
    valid_urls=(
        f"https://www.vimeo.com/{VID}",
        f"http://vimeo.com/{VID}",
        f"https://vimeo.com/{VID}/",  # single trailing slash tolerated
        f"https://vimeo.com/{VID}?share=copy",
        f"https://vimeo.com/{VID}#t=90s",
        # Unlisted-access hash: an access token, not identity — dropped.
        f"https://vimeo.com/{VID}/d0e9b81c05",
        f"https://vimeo.com/{VID}/d0e9b81c05?share=copy",
        # Embed player on its own subdomain; the hash rides as ?h= there.
        f"https://player.vimeo.com/video/{VID}",
        f"https://player.vimeo.com/video/{VID}?h=d0e9b81c05",
    ),
    invalid_urls=(
        "abc123",  # not numeric
        f"https://notvimeo.com/{VID}",  # look-alike host
        f"https://vimeo.com.evil.com/{VID}",  # host as a prefix label
        f"https://vimeo.com/user{VID}",  # profile, not a video
        f"https://vimeo.com/{VID}/review",  # non-hex tail is not a hash
        f"https://vimeo.com/{VID}/d0e9b81c05/extra",  # extra path segment
        f"https://vimeo.com/channels/staffpicks/{VID}",  # legacy browse shape
        f"https://player.vimeo.com/{VID}",  # embed shape needs /video/
        f"https://example.com/{VID}",  # bare id buried in a foreign URL
    ),
    start_time_cases=(
        StartTimeCase(f"https://vimeo.com/{VID}#t=90s", 90),
        StartTimeCase(f"https://vimeo.com/{VID}#t=1m30s", 90),
        StartTimeCase(f"https://vimeo.com/{VID}#t=1h2m3s", 3723),
        StartTimeCase(f"https://vimeo.com/{VID}#t=95", 95),
        StartTimeCase(f"https://player.vimeo.com/video/{VID}?h=abc123#t=2m", 120),
        StartTimeCase(f"https://vimeo.com/{VID}", None),  # no fragment
        StartTimeCase(f"https://vimeo.com/{VID}#t=0s", None),  # 0 = beginning
        StartTimeCase(f"https://vimeo.com/{VID}#t=junk", None),  # malformed
        StartTimeCase(f"https://vimeo.com/{VID}?t=90s", None),  # query not Vimeo's
    ),
    # Seeks via the #t= fragment, not a query param.
    deep_link_case=DeepLinkCase(3723, f"https://vimeo.com/{VID}#t=3723s"),
)

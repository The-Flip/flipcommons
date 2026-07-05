"""X (Twitter) scheme examples: two host families collapsing to one status id.

X is the multi-host stress case: x.com and legacy twitter.com shapes all
normalize to one child per status id (the table proves the collapse — every
valid row must yield the same identifier). The canonical is the handle-free
``/i/status/`` form, so the stored link survives vanity-handle renames. It is
a **web** scheme — a ``/status/`` URL entails nothing about the post's media
(the type-homogeneity rule), so it declares no time capabilities. Pure data;
the shared harnesses do all the driving.
"""

from .example_data import SchemeExamples

SID = "1585341984679469056"

EXAMPLES = SchemeExamples(
    example_identifier=SID,
    # Rename-stable: no vanity handle baked into the stored link.
    canonical_url=f"https://x.com/i/status/{SID}",
    valid_urls=(
        f"https://x.com/PinballNews/status/{SID}",
        f"https://twitter.com/PinballNews/status/{SID}",
        f"https://www.x.com/PinballNews/status/{SID}",
        f"https://www.twitter.com/PinballNews/status/{SID}",
        f"https://mobile.twitter.com/PinballNews/status/{SID}",
        f"http://twitter.com/PinballNews/status/{SID}",
        f"https://x.com/i/web/status/{SID}",  # handle-free web shape
        f"https://twitter.com/statuses/{SID}",  # legacy path form
        # Media tails and params on pasted URLs are tolerated.
        f"https://x.com/PinballNews/status/{SID}/video/1",
        f"https://x.com/PinballNews/status/{SID}/photo/1",
        f"https://x.com/PinballNews/status/{SID}?s=20&t=abc",
        f"https://x.com/PinballNews/status/{SID}#m",
    ),
    invalid_urls=(
        f"https://notx.com/user/status/{SID}",  # look-alike host
        f"https://x.com.evil.com/user/status/{SID}",  # host as a prefix label
        f"https://x.com/user/status/{SID}abc",  # id must end at a boundary
        "https://x.com/PinballNews",  # profile, not a post
        f"https://x.com/i/lists/{SID}",  # a list, not a post
        f"https://x.com/a_way_too_long_username/status/{SID}",  # handle >15 chars
        f"https://example.com/status/{SID}",  # wrong site
    ),
)

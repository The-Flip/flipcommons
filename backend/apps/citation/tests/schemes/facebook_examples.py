"""Facebook Video scheme examples.

Only video-specific Facebook shapes are recognized. Generic posts and opaque
share links are excluded because the URL alone does not prove video evidence or
does not expose the numeric video id needed for a canonical watch URL.
"""

from .example_data import SchemeExamples

VID = "1234567890123456"
PAGE = "pinball.news"

EXAMPLES = SchemeExamples(
    example_identifier=VID,
    canonical_url=f"https://www.facebook.com/watch/?v={VID}",
    valid_urls=(
        f"https://facebook.com/watch/?v={VID}",  # no www
        f"http://www.facebook.com/watch/?v={VID}",
        f"https://m.facebook.com/watch/?v={VID}",  # mobile
        f"https://mobile.facebook.com/watch/?v={VID}",
        f"https://www.facebook.com/watch?ref=sharing&v={VID}",
        f"https://www.facebook.com/watch/live/?v={VID}",
        f"https://www.facebook.com/video.php?v={VID}",
        f"https://www.facebook.com/{PAGE}/videos/{VID}",
        f"https://www.facebook.com/{PAGE}/videos/{VID}/",  # trailing slash
        f"https://www.facebook.com/{PAGE}/videos/{VID}?locale=en_US",
    ),
    invalid_urls=(
        "abc123",  # not numeric
        f"https://notfacebook.com/watch/?v={VID}",  # look-alike host
        f"https://facebook.com.evil.com/watch/?v={VID}",  # host prefix label
        f"https://www.facebook.com/watch/?v={VID}abc",  # id boundary
        f"https://www.facebook.com/{PAGE}/posts/{VID}",  # mixed-media post
        f"https://www.facebook.com/{PAGE}/photos/{VID}",  # photo
        f"https://www.facebook.com/{PAGE}/videos/{VID}/comments",  # extra path
        "https://www.facebook.com/share/v/abcDEF123/",  # opaque redirect code
        "https://fb.watch/abcDEF123/",  # opaque short link
        f"https://example.com/watch/?v={VID}",  # wrong site
    ),
)

"""Instagram Reels scheme examples.

Only ``/reel/<shortcode>`` is video-typed enough for the video scheme. Regular
posts (``/p/``), stories and profiles are deliberately left to generic web
recognition because the URL shape alone does not promise a citable video.
Instagram URLs carry no seek parameter, so timestamp locators render beside the
plain canonical reel link. Pure data; the shared harnesses do all the driving.
"""

from .example_data import SchemeExamples

SHORTCODE = "C0XyZ_abc12"

EXAMPLES = SchemeExamples(
    example_identifier=SHORTCODE,
    canonical_url=f"https://www.instagram.com/reel/{SHORTCODE}/",
    valid_urls=(
        f"https://instagram.com/reel/{SHORTCODE}/",  # no www
        f"http://www.instagram.com/reel/{SHORTCODE}/",
        f"https://m.instagram.com/reel/{SHORTCODE}/",
        f"https://www.instagram.com/reel/{SHORTCODE}?igsh=abc123",
        f"https://www.instagram.com/reel/{SHORTCODE}/?utm_source=ig_web_copy_link",
        f"https://www.instagram.com/reel/{SHORTCODE}/#comments",
    ),
    invalid_urls=(
        f"https://www.instagram.com/p/{SHORTCODE}/",  # post, not guaranteed video
        f"https://www.instagram.com/stories/pinball/{SHORTCODE}/",
        "https://www.instagram.com/reels/audio/123456789/",
        "https://www.instagram.com/pinball/",
        f"https://www.instagram.com/reel/{SHORTCODE}/embed",  # extra path
        f"https://notinstagram.com/reel/{SHORTCODE}/",  # look-alike host
        f"https://instagram.com.evil.com/reel/{SHORTCODE}/",  # host prefix label
    ),
)

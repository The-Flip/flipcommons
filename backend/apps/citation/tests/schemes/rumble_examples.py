"""Rumble scheme examples.

Rumble watch pages carry the video identity as the slugged ``v...html`` path.
Embeds expose only the short internal id, not the watch-page slug this pure
scheme needs to rebuild a reader-facing canonical URL, so they intentionally
fall through to host recognition instead of minting a lossy duplicate child.
"""

from .example_data import SchemeExamples

VIDEO_PATH = "v6qiivm-chinas-tesla-killer-is-coming-for-elon-musks-crown.html"

EXAMPLES = SchemeExamples(
    example_identifier=VIDEO_PATH,
    canonical_url=f"https://rumble.com/{VIDEO_PATH}",
    valid_urls=(
        f"https://www.rumble.com/{VIDEO_PATH}",
        f"http://rumble.com/{VIDEO_PATH}",
        f"https://rumble.com/{VIDEO_PATH}/",  # trailing slash
        f"https://rumble.com/{VIDEO_PATH}?e9s=src_v1_ucp",
        f"https://rumble.com/{VIDEO_PATH}#comments",
    ),
    invalid_urls=(
        "https://rumble.com/embed/v6qiivm/?pub=4",  # no slug, cannot rebuild watch URL
        "https://rumble.com/c/Pinball",
        "https://rumble.com/user/Pinball",
        "https://rumble.com/v6qiivm",
        "https://rumble.com/v6qiivm-title.htm",  # watch pages use .html
        f"https://notrumble.com/{VIDEO_PATH}",  # look-alike host
        f"https://rumble.com.evil.com/{VIDEO_PATH}",  # prefix label
    ),
)

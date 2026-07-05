"""Snapchat Spotlight scheme examples.

Spotlight share URLs identify individual videos by an opaque token under
``/spotlight/``. Other public Snapchat paths (profiles, add links, stories) are
not video-homogeneous enough for a video scheme. The platform has no declared
seek URL support, so locators remain text beside the canonical link.
"""

from .example_data import SchemeExamples

SPOTLIGHT_ID = "W7_EDlXWTBiXAEEniNoMPwAAYbmx0eWJ3dWJpAYzSAZhV"

EXAMPLES = SchemeExamples(
    example_identifier=SPOTLIGHT_ID,
    canonical_url=f"https://www.snapchat.com/spotlight/{SPOTLIGHT_ID}",
    valid_urls=(
        f"https://snapchat.com/spotlight/{SPOTLIGHT_ID}",  # no www
        f"http://www.snapchat.com/spotlight/{SPOTLIGHT_ID}",
        f"https://www.snapchat.com/spotlight/{SPOTLIGHT_ID}/",  # trailing slash
        f"https://www.snapchat.com/spotlight/{SPOTLIGHT_ID}?share_id=abc123",
        f"https://www.snapchat.com/spotlight/{SPOTLIGHT_ID}#clip",
    ),
    invalid_urls=(
        "https://www.snapchat.com/add/pinballnews",
        "https://www.snapchat.com/@pinballnews",
        f"https://www.snapchat.com/spotlight/{SPOTLIGHT_ID}/replies",  # extra path
        f"https://www.snapchat.com/story/{SPOTLIGHT_ID}",
        f"https://notsnapchat.com/spotlight/{SPOTLIGHT_ID}",  # look-alike host
        f"https://snapchat.com.evil.com/spotlight/{SPOTLIGHT_ID}",  # prefix label
    ),
)

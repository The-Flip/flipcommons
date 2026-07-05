"""Dailymotion scheme examples.

The watch page, embed player and ``dai.ly`` short host all carry the same
``x...`` video id and collapse to the watch-page canonical URL. Slugged watch
URLs are deliberately excluded until the scheme framework has a per-platform
way to strip display slugs without weakening identifier boundaries globally.
"""

from .example_data import SchemeExamples

VID = "x8abc12"

EXAMPLES = SchemeExamples(
    example_identifier=VID,
    canonical_url=f"https://www.dailymotion.com/video/{VID}",
    valid_urls=(
        f"https://dailymotion.com/video/{VID}",  # no www
        f"http://www.dailymotion.com/video/{VID}",
        f"https://www.dailymotion.com/video/{VID}/",  # trailing slash
        f"https://www.dailymotion.com/video/{VID}?playlist=x123",
        f"https://www.dailymotion.com/video/{VID}#comments",
        f"https://www.dailymotion.com/embed/video/{VID}",
        f"https://www.dailymotion.com/embed/video/{VID}?autoplay=1",
        f"https://dai.ly/{VID}",
        f"https://www.dai.ly/{VID}?playlist=x123",
    ),
    invalid_urls=(
        "x",  # too short to be a useful Dailymotion id
        "X8ABC12",  # uppercase would create case-variant duplicates
        f"https://notdailymotion.com/video/{VID}",  # look-alike host
        f"https://dailymotion.com.evil.com/video/{VID}",  # host prefix label
        f"https://www.dailymotion.com/{VID}",  # missing /video/
        f"https://www.dailymotion.com/video/{VID}_display-slug",  # slug not stripped
        f"https://www.dailymotion.com/video/{VID}/extra",  # extra path
        f"https://www.dailymotion.com/playlist/{VID}",  # playlist, not a video
        f"https://example.com/video/{VID}",  # wrong site
    ),
)

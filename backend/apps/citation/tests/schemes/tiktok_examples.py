"""TikTok scheme examples: the composite-identity stress case.

The identifier is ``<user>/video/<id>`` because the numeric id alone cannot
rebuild a watch URL; opaque short links (``vm.``/``vt.``/``/t/``) are
deliberately unrecognized — they are redirects, not identity. TikTok URLs
carry no seek parameter, so the scheme declares neither time capability and a
cited timestamp renders beside the plain canonical link (the shared DB
round-trip harness covers that fallback). Pure data; the shared harnesses do
all the driving.
"""

from .example_data import SchemeExamples

USER = "scottdanesi"
POST = "7106594312292453675"
IDENTIFIER = f"{USER}/video/{POST}"

EXAMPLES = SchemeExamples(
    example_identifier=IDENTIFIER,
    canonical_url=f"https://www.tiktok.com/@{USER}/video/{POST}",
    valid_urls=(
        f"https://tiktok.com/@{USER}/video/{POST}",  # no www
        f"http://www.tiktok.com/@{USER}/video/{POST}",
        f"https://www.tiktok.com/@{USER}/video/{POST}/",  # trailing slash
        f"https://www.tiktok.com/@{USER}/video/{POST}?is_from_webapp=1&lang=en",
        f"https://www.tiktok.com/@{USER}/video/{POST}#comment",
    ),
    invalid_urls=(
        POST,  # the numeric id alone cannot rebuild a watch URL
        f"{USER}/{POST}",  # missing the /video/ separator
        f"https://www.tiktok.com/{USER}/video/{POST}",  # missing the @
        f"https://www.tiktok.com/@{USER}/photo/{POST}",  # photo post
        f"https://www.tiktok.com/@{USER}",  # profile, not a video
        f"https://www.tiktok.com/@{USER}/video/{POST}/duet",  # extra path
        f"https://www.tiktok.com/@Scott{USER}/video/{POST}",  # uppercase user
        "https://vm.tiktok.com/ZMabc123/",  # opaque short link (redirect)
        "https://vt.tiktok.com/ZSabc123/",  # ditto
        "https://www.tiktok.com/t/ZTabc123/",  # ditto, path form
        f"https://m.tiktok.com/v/{POST}.html",  # legacy shape has no username
        f"https://nottiktok.com/@{USER}/video/{POST}",  # look-alike host
    ),
)

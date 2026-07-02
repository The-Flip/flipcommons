"""The quote recognizer: pull a verbatim source quote out of a legacy note.

Legacy ``ChangeSet.note``s carry evidence as ``<source> says "<quote>"``
scaffolding; the quote now belongs on the citation (``CitationInstance.quote``).
This module is the pure transform both migration consumers share: flippatch's
patch-rewrite script (``scripts/quote_rewrite/extract_quote.py`` there — a
byte-identical twin below the module docstring; the repos share no runtime
dependency) and the provenance data migrations here. Change one, change both —
the ``rewrite-then-ingest ≡ ingest-then-migrate`` property test catches
divergence.

Deliberately conservative: only the confidently-shaped notes match; anything
with substantive prose outside the quoted spans returns ``None`` and is fixed
by hand. Every proposed rewrite gets human review via a before/after diff, so
the recognizer optimizes for "never mangles" over "always matches".

Imported by migrations ``provenance/0023`` and ``provenance/0024``: do NOT
delete this module or change its semantics — migration replays on fresh
databases depend on it behaving exactly as it did when they shipped.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class ExtractedQuote(NamedTuple):
    """A recognized quote-note, decomposed.

    ``quote`` is the verbatim excerpt (multi-span joined by ``[...]``);
    ``residual`` is what remains for the note (always ``""`` today — a note
    with substantive leftover prose fails recognition instead); ``source``
    is the note's source phrase (``IPDB``, ``The eremeka catalog``), returned
    so consumers can flag a note whose named source disagrees with the unit's
    ``cite:`` — moving such a quote would mis-attribute it.
    """

    quote: str
    residual: str
    source: str


# Typography the authoring convention already mandates straightening: smart
# quotes become straight ones and a real ellipsis character becomes the
# explicit-omission marker. Applied before parsing so grandfathered pre-0039
# notes (exempt from the note-typography lint) parse identically.
_TYPOGRAPHY = {
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "…": "[...]",
}

# The verb phrases that introduce a quote without adding meaning of their own
# ("this" refers to the entity the claim is about). Anything else between the
# source name and the first quote — a subject, a dative object, a clause — is
# substantive prose and fails recognition.
_VERBS = ("says", "lists", "states", "reports", "reported", "dates this")

# ``<source> <verb> ["that"] "`` or ``<source>: "`` — the source phrase is
# short and quote-free. 60 chars accommodates the longest real prefix ("The
# Canadian Trademarks Database lists") without inviting whole-sentence
# prefixes.
_PREFIX_RE = re.compile(
    rf"^(?P<source>[^\"]{{1,60}}?)(?:\s+(?:{'|'.join(_VERBS)})\s+(?:that\s+)?|:\s+)(?=\")"
)

# Connectives allowed between two quoted spans: pure glue that ``[...]``
# preserves. Anything longer is paraphrase, which fails recognition.
_CONNECTIVE_RE = re.compile(r"(?:,?\s+and\s+|,\s+|;\s+|\s+)")

# What may trail the final span: nothing, or a lone terminal period.
_TERMINATOR_RE = re.compile(r"^\.?$")

# A trailing residual after the final span: editorial rationale set off by a
# comma, semicolon or dash ("..., identifying this as an aftermarket
# re-theme..."). It stays behind as the note. Must itself be quote-free —
# a quoted residual means the span split is ambiguous, so recognition fails.
_RESIDUAL_RE = re.compile(r"^(?:,|;|\s+--|\s+—)\s+(?P<residual>[^\"]{4,})$", re.DOTALL)


def _normalize(text: str) -> str:
    for smart, straight in _TYPOGRAPHY.items():
        text = text.replace(smart, straight)
    return text


class _ParsedTail(NamedTuple):
    """The tail of a quote-note: its quoted spans and any trailing residual."""

    spans: list[str]
    residual: str


def _parse_spans(tail: str) -> _ParsedTail | None:
    """Parse *tail* as quoted spans joined by pure connectives, or ``None``.

    Non-greedy span matching: an inner unescaped quote makes this parse fail
    (the text after the early closing quote isn't a connective), which is what
    lets the greedy fallback in :func:`extract_quote` read it as one outer
    span instead. A trailing ``_RESIDUAL_RE`` fragment after the final span is
    allowed and returned.
    """
    spans: list[str] = []
    pos = 0
    while True:
        if pos >= len(tail) or tail[pos] != '"':
            return None
        end = tail.find('"', pos + 1)
        if end == -1:
            return None
        spans.append(tail[pos + 1 : end])
        pos = end + 1
        rest = tail[pos:]
        if _TERMINATOR_RE.match(rest):
            return _ParsedTail(spans, "")
        residual = _RESIDUAL_RE.match(rest)
        if residual is not None:
            return _ParsedTail(spans, residual.group("residual").strip())
        connective = _CONNECTIVE_RE.match(rest)
        if connective is None:
            return None
        pos += connective.end()


# The greedy single-span reading: everything between the first quote and the
# LAST quote in the tail is the span (inner unescaped quotes belong to the
# source text), followed by a terminator or a trailing residual.
_GREEDY_SPAN_RE = re.compile(r'^"(?P<span>.+)"(?P<after>[^\"]*)$', re.DOTALL)

# Sentence punctuation immediately before an inner quote char is the tell-tale
# of a disguised span boundary ("A," and that "B.") — a genuinely nested phrase
# closes on a word character (a "flasher type" slot machine). Refusing these
# keeps the greedy reading from splicing connective prose into a "verbatim"
# quote; the rare source text that really quotes dialogue this way falls to
# hand review instead.
_DISGUISED_BOUNDARY_RE = re.compile(r'[.,;!?]"')


def extract_quote(note: str) -> ExtractedQuote | None:
    """Recognize a ``<source> says "<quote>"`` note; ``None`` on any doubt.

    On a match the quote is the verbatim span text — multiple spans joined by
    ``[...]`` in source order — with the convention's typography normalization
    applied (straight quotes, ``…`` → ``[...]``). The scaffolding (``<source>
    says``) is dropped: the citation already names the source. Trailing
    editorial rationale set off from the final span survives as ``residual``.
    A note whose prose doesn't otherwise reduce to scaffolding + spans + glue
    is not recognized.
    """
    text = _normalize(note.strip())
    prefix = _PREFIX_RE.match(text)
    if prefix is None:
        return None
    tail = text[prefix.end() :]

    # Prefer the multi-span reading; fall back to one greedy outer span so a
    # nested unescaped quote ("Also called a "flasher type" slot machine.")
    # matches to the outermost closing quote.
    parsed = _parse_spans(tail)
    if parsed is None:
        greedy = _GREEDY_SPAN_RE.match(tail)
        if greedy is None or _DISGUISED_BOUNDARY_RE.search(greedy.group("span")):
            return None
        after = greedy.group("after")
        if _TERMINATOR_RE.match(after):
            residual = ""
        else:
            residual_match = _RESIDUAL_RE.match(after)
            if residual_match is None:
                return None
            residual = residual_match.group("residual").strip()
        parsed = _ParsedTail([greedy.group("span")], residual)
    if not all(span.strip() for span in parsed.spans):
        return None

    return ExtractedQuote(
        quote=" [...] ".join(span.strip() for span in parsed.spans),
        residual=parsed.residual,
        source=prefix.group("source"),
    )

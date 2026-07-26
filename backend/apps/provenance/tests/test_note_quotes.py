"""Unit tests for the quote recognizer twin (apps.provenance.note_quotes).

A mirror of flippatch's tests/test_extract_quote.py against the twin copy —
each case is drawn from the real note corpus the recognizer was honed on.
Keep the two suites in sync like the recognizers themselves; the equivalence
test in apps/catalog/tests/test_note_quote_equivalence.py is what catches a
behavioral divergence between the repos.
"""

from __future__ import annotations

from apps.provenance.note_quotes import extract_quote

# --- The canonical shapes -----------------------------------------------


def test_simple_says_note():
    result = extract_quote('IPDB says "This is Not A Pinball."')
    assert result is not None
    assert result.quote == "This is Not A Pinball."
    assert result.residual == ""
    assert result.source == "IPDB"


def test_trailing_period_outside_quote_dropped():
    result = extract_quote('IPDB says "Never went into production".')
    assert result is not None
    assert result.quote == "Never went into production"
    assert result.residual == ""


def test_lists_verb():
    result = extract_quote('The eremeka catalog lists "1976 Advantage by Sankyo".')
    assert result is not None
    assert result.quote == "1976 Advantage by Sankyo"
    assert result.source == "The eremeka catalog"


def test_says_that():
    result = extract_quote('Wikipedia says that "the company was renamed".')
    assert result is not None
    assert result.quote == "the company was renamed"


def test_colon_form():
    result = extract_quote(
        'This Week in Pinball: "I stumbled upon a trademark filing."'
    )
    assert result is not None
    assert result.quote == "I stumbled upon a trademark filing."
    assert result.source == "This Week in Pinball"


def test_dates_this_verb():
    result = extract_quote(
        'Early Arcades Japan dates this "1973 つり天狗 (Fishing Tengu) by 三共 (Sankyo)".'
    )
    assert result is not None
    assert result.quote == "1973 つり天狗 (Fishing Tengu) by 三共 (Sankyo)"


# --- Nested unescaped quotes match to the outermost closing quote --------


def test_nested_unescaped_quotes_greedy():
    result = extract_quote('IPDB says "Also called a "flasher type" slot machine."')
    assert result is not None
    assert result.quote == 'Also called a "flasher type" slot machine.'
    assert result.residual == ""


def test_nested_quotes_inside_long_span():
    result = extract_quote(
        'IPDB says "Although Bally also referred to this game as "an upright '
        'pin-game", a disc is used instead of a ball and therefore we classify '
        'it as Not A Pinball."'
    )
    assert result is not None
    assert result.quote.startswith("Although Bally also referred")
    assert '"an upright pin-game"' in result.quote


# --- Multi-span notes join with [...] ------------------------------------


def test_two_spans_joined():
    result = extract_quote('IPDB says "never produced" and "prototype only".')
    assert result is not None
    assert result.quote == "never produced [...] prototype only"


# --- Typography normalization ---------------------------------------------


def test_smart_quotes_straightened():
    result = extract_quote("IPDB says “This game was never produced.”")
    assert result is not None
    assert result.quote == "This game was never produced."


def test_ellipsis_character_becomes_marker():
    result = extract_quote('IPDB says "was selected… but never made".')
    assert result is not None
    assert result.quote == "was selected[...] but never made"


def test_smart_apostrophe_straightened():
    result = extract_quote("IPDB says “It used to be Williams’ 1948 ‘Rainbow’.”")
    assert result is not None
    assert result.quote == "It used to be Williams' 1948 'Rainbow'."


# --- Trailing residuals ----------------------------------------------------


def test_comma_residual_survives_as_note():
    result = extract_quote(
        'IPDB says "This is a re-themed game.", identifying this as an '
        "aftermarket re-theme of an existing machine."
    )
    assert result is not None
    assert result.quote == "This is a re-themed game."
    assert result.residual == (
        "identifying this as an aftermarket re-theme of an existing machine."
    )


def test_semicolon_residual():
    result = extract_quote(
        "IPDB says \"'Goin' Nuts' was never placed into production\"; "
        "IPDB records 10 units."
    )
    assert result is not None
    assert result.quote == "'Goin' Nuts' was never placed into production"
    assert result.residual == "IPDB records 10 units."


def test_dash_residual():
    result = extract_quote(
        'The Museum of the Game lists "Williams Electronics, Inc. (1967-1985)" '
        "-- the span the name was active."
    )
    assert result is not None
    assert result.quote == "Williams Electronics, Inc. (1967-1985)"
    assert result.residual == "the span the name was active."


def test_quoted_residual_refused():
    # A residual containing a quote means the span split is ambiguous.
    assert (
        extract_quote(
            'The eremeka catalog lists "1970 Jumbo Kick"; flipcommons held it '
            'with no manufacturer (IPDB: "Unknown Manufacturer").'
        )
        is None
    )


# --- Refusals: substantive prose outside the spans ------------------------


def test_own_data_note_refused():
    assert (
        extract_quote(
            'The name includes "Prototype", which indicates that this is a '
            "prototype that never reached commercial production."
        )
        is None
    )


def test_subject_between_verb_and_quote_refused():
    # The quote alone would lose its subject ("Midway").
    assert (
        extract_quote(
            'Wikipedia says Midway "moved its headquarters from Franklin Park, '
            "Illinois, to Williams's then-headquarters in Chicago.\""
        )
        is None
    )


def test_meaning_bearing_trailing_text_refused():
    # " in 1988" isn't set off by punctuation — it belongs to the claim.
    assert (
        extract_quote('Wikipedia says "moved its headquarters to Chicago" in 1988.')
        is None
    )


def test_translation_gloss_inline_refused():
    # The gloss between subject and quote is interpretation, not scaffolding.
    assert (
        extract_quote(
            'Weblio says サンワイズ (Sunwise) "1998年3月6日に倒産した" '
            "(went bankrupt on 6 March 1998); it was based in Mitaka, Tokyo."
        )
        is None
    )


def test_multi_span_with_substantive_connective_refused():
    assert (
        extract_quote(
            'Wikipedia says the company "manufactured other machines," was '
            '"founded by Ode D. Jennings," and that "Jennings & Company was '
            'incorporated in Illinois."'
        )
        is None
    )


def test_plain_rationale_note_refused():
    assert extract_quote("Corrected the year per the flyer.") is None


def test_empty_and_quoteless_refused():
    assert extract_quote("") is None
    assert extract_quote("On The Flip museum's list of unreleased prototypes") is None


def test_empty_span_refused():
    assert extract_quote('IPDB says ""') is None

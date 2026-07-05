"""Tests for the video citation type's timestamp locator grammar.

Pure — no database. The grammar is the authoritative validator for video
locators on every write path (API mint, patch apply); the frontend only
mirrors it for inline UX.
"""

import pytest

from apps.citation.citation_types.video import (
    MAX_START_TIME_SECONDS,
    format_start_time,
    normalize_start_time,
    parse_start_time,
)


class TestParseStartTime:
    @pytest.mark.parametrize(
        ("raw", "seconds"),
        [
            # Bare seconds.
            ("0", 0),
            ("57", 57),
            ("95", 95),
            ("3723", 3723),
            # Colon forms: M:SS and H:MM:SS, leading unit unbounded.
            ("0:57", 57),
            ("1:35", 95),
            ("12:05", 725),
            ("90:00", 5400),
            ("1:02:03", 3723),
            ("10:00:00", 36000),
            # Sloppy inner digits normalize rather than reject.
            ("1:2:3", 3723),
            ("1:5", 65),
            # Unit form, any subset of h/m/s, case-insensitive.
            ("1h2m3s", 3723),
            ("95s", 95),
            ("2m", 120),
            ("1h", 3600),
            ("90m", 5400),
            ("1H2M3S", 3723),
            ("2m5s", 125),
            # Surrounding whitespace is tolerated.
            (" 1:35 ", 95),
        ],
    )
    def test_accepted_forms(self, raw, seconds):
        assert parse_start_time(raw) == seconds

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "abc",
            "p. 42",  # a book locator is not a timestamp
            "1:75",  # seconds component ≥ 60
            "1:75:00",  # minutes component ≥ 60
            "1:02:03:04",  # too many segments
            ":35",  # empty leading segment
            "1:",  # empty trailing segment
            "-95",  # negative
            "1.5",  # fractional
            "1m2h",  # units out of order
            "2x",  # unknown unit
            "h",  # unit with no value
            "1h 2m",  # inner whitespace
            "1:35s",  # mixed colon and unit forms
        ],
    )
    def test_rejected_forms(self, raw):
        assert parse_start_time(raw) is None

    def test_upper_bound(self):
        # 100 hours is the deliberate cap — beyond it a bare-seconds input is
        # far more likely a typo than a real start time. Relaxing is a
        # constant change; see MAX_START_TIME_SECONDS.
        assert parse_start_time(str(MAX_START_TIME_SECONDS)) == MAX_START_TIME_SECONDS
        assert parse_start_time(str(MAX_START_TIME_SECONDS + 1)) is None
        assert parse_start_time("100:00:00") == MAX_START_TIME_SECONDS
        assert parse_start_time("100:00:01") is None


class TestFormatStartTime:
    @pytest.mark.parametrize(
        ("seconds", "canonical"),
        [
            (0, "0:00"),
            (57, "0:57"),
            (95, "1:35"),
            (725, "12:05"),
            (3599, "59:59"),
        ],
    )
    def test_under_an_hour_is_m_ss(self, seconds, canonical):
        assert format_start_time(seconds) == canonical

    @pytest.mark.parametrize(
        ("seconds", "canonical"),
        [
            (3600, "1:00:00"),
            (3723, "1:02:03"),
            (5400, "1:30:00"),
            (36000, "10:00:00"),
        ],
    )
    def test_an_hour_and_up_is_h_mm_ss(self, seconds, canonical):
        assert format_start_time(seconds) == canonical


class TestNormalizeStartTime:
    @pytest.mark.parametrize(
        ("raw", "canonical"),
        [
            ("95", "1:35"),
            ("1:35", "1:35"),
            ("1:2:3", "1:02:03"),
            ("1h2m3s", "1:02:03"),
            ("90:00", "1:30:00"),  # parses as 90 minutes, formats canonically
            ("0", "0:00"),
        ],
    )
    def test_normalizes_to_canonical(self, raw, canonical):
        assert normalize_start_time(raw) == canonical

    def test_rejects_junk(self):
        assert normalize_start_time("p. 42") is None

    def test_canonical_forms_are_fixed_points(self):
        for canonical in ["0:00", "0:57", "1:35", "12:05", "1:02:03", "10:00:00"]:
            assert normalize_start_time(canonical) == canonical

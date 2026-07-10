"""Tests for EWD108 RMC parser utilities."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.ewd108.api import (
    Ewd108ClientParseError,
    _parse_nmea_coordinate,
    _parse_rmc_sentence,
)


def test_parse_rmc_sentence_manual_sample() -> None:
    """Parse manual sample and validate core decoded fields."""
    sentence = "$GNRMC,083429.00,A,3046.26769,N,10356.04948,E,000.00,089.80,190422*21"

    parsed = _parse_rmc_sentence(sentence)

    assert parsed.fix_valid is True
    assert parsed.timestamp_utc == datetime(2022, 4, 19, 8, 34, 29, tzinfo=timezone.utc)
    assert parsed.latitude == pytest.approx(30.7711281666)
    assert parsed.longitude == pytest.approx(103.934158)
    assert parsed.speed_knots == pytest.approx(0.0)
    assert parsed.speed_kmh == pytest.approx(0.0)
    assert parsed.course == pytest.approx(89.80)
    assert parsed.geohash is not None
    assert len(parsed.geohash) == 9
    assert parsed.position_text is not None


def test_parse_rmc_sentence_invalid_checksum() -> None:
    """Reject sentence when checksum does not match."""
    bad_sentence = "$GNRMC,083429.00,A,3046.26769,N,10356.04948,E,000.00,089.80,190422*22"

    with pytest.raises(Ewd108ClientParseError, match="Checksum mismatch"):
        _parse_rmc_sentence(bad_sentence)


def test_parse_nmea_coordinate_southern_western() -> None:
    """Parse S/W coordinates into negative decimal degrees."""
    latitude = _parse_nmea_coordinate("3046.26769", "S", is_latitude=True)
    longitude = _parse_nmea_coordinate("10356.04948", "W", is_latitude=False)

    assert latitude is not None
    assert longitude is not None
    assert latitude < 0
    assert longitude < 0

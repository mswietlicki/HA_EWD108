"""Regressions for corrupt frames, fix loss and impossible GPS routes."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection import ModbusTimeoutError

from custom_components.ewd108.api import (
    Ewd108ClientCommunicationError,
    Ewd108ClientParseError,
    Ewd108ModbusClient,
    _decode_registers_to_ascii,
    _parse_nmea_coordinate,
    _parse_rmc_sentence,
)
from custom_components.ewd108.validation import PositionValidator

NOW = datetime(2026, 10, 12, 7, 0, 0, tzinfo=UTC)


def sentence(body: str) -> str:
    """Build a checksum-correct frame so field validation is exercised."""
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def sample(lat: float = 52.4282, lon: float = 20.9774, seconds: int = 0) -> dict:
    """Return a complete fix near Warsaw at a known GNSS time."""
    return {
        "fix_valid": True,
        "latitude": lat,
        "longitude": lon,
        "timestamp_utc": NOW + timedelta(seconds=seconds),
        "raw_rmc": "diagnostic",
    }


@pytest.mark.parametrize(
    ("value", "is_latitude"),
    [
        ("9060.0", True),
        ("9100.0", True),
        ("18001.0", False),
        ("18100.0", False),
        ("1260.0", True),
        ("12nan", True),
        ("12inf", True),
        ("-100.0", True),
        ("12+0.0", True),
    ],
)
def test_bad_coordinates(value: str, *, is_latitude: bool) -> None:
    """Reject bounds, invalid minutes, nonfinite and non-NMEA numbers."""
    assert (
        _parse_nmea_coordinate(
            value, "N" if is_latitude else "E", is_latitude=is_latitude
        )
        is None
    )


def test_invalid_fix_does_not_publish_stale_coordinates() -> None:
    """The observed loss-of-fix sentinel must never become a position."""
    parsed = _parse_rmc_sentence(
        sentence("GNRMC,070000.00,V,0000.0,N,02058.644,E,0,0,121026")
    )
    assert not parsed.fix_valid
    assert parsed.latitude is None
    assert parsed.longitude is None
    assert parsed.speed_kmh is None


@pytest.mark.parametrize(
    "body",
    [
        "GNRMC,070000.00,A,9060.0,N,02058.644,E,0,0,121026",
        "GNRMC,250000.00,A,5225.692,N,02058.644,E,0,0,121026",
        "GNRMC,070000.00,X,5225.692,N,02058.644,E,0,0,121026",
    ],
)
def test_corrupt_valid_frame(body: str) -> None:
    """Checksum correctness alone cannot make malformed data usable."""
    with pytest.raises(Ewd108ClientParseError):
        _parse_rmc_sentence(sentence(body))


def test_non_ascii_is_not_silently_removed() -> None:
    """Reject corruption instead of changing the frame before checksumming."""
    with pytest.raises(Ewd108ClientParseError, match="Non-ASCII"):
        _decode_registers_to_ascii([0xFF24])


@pytest.mark.parametrize(("seconds", "reason"), [(-31, "stale_fix"), (6, "future_fix")])
def test_frame_freshness(seconds: int, reason: str) -> None:
    """A frozen or future device clock cannot provide a current position."""
    result = PositionValidator().validate(sample(seconds=seconds), NOW)
    assert result["rejection_reason"] == reason
    assert result["latitude"] is None
    assert result["raw_rmc"] == "diagnostic"


def test_africa_jump_and_recovery() -> None:
    """An outlier never replaces the baseline used for the next real fix."""
    validator = PositionValidator()
    assert validator.validate(sample(), NOW)["fix_valid"]
    bad = validator.validate(sample(lat=0, seconds=5), NOW + timedelta(seconds=5))
    assert bad["rejection_reason"] == "implausible_jump"
    assert bad["longitude"] is None
    assert validator.validate(
        sample(lat=52.4283, seconds=10), NOW + timedelta(seconds=10)
    )["fix_valid"]


def test_fix_loss_and_out_of_order_do_not_replace_baseline() -> None:
    """Recover on a new valid frame without accepting reversed GNSS time."""
    validator = PositionValidator()
    validator.validate(sample(), NOW)
    assert (
        validator.validate({**sample(seconds=5), "fix_valid": False}, NOW)[
            "rejection_reason"
        ]
        == "invalid_fix"
    )
    assert (
        validator.validate(sample(seconds=-1), NOW)["rejection_reason"]
        == "out_of_order_fix"
    )
    assert validator.validate(sample(seconds=10), NOW + timedelta(seconds=10))[
        "fix_valid"
    ]


@pytest.mark.parametrize(("lat", "lon"), [(0, 21), (52, 0), (-33.9, 18.4)])
def test_valid_global_coordinates(lat: float, lon: float) -> None:
    """Coherent frames can cross the equator and prime meridian."""
    assert PositionValidator().validate(sample(lat, lon), NOW)["fix_valid"]


@pytest.mark.asyncio
async def test_one_modbus_read_and_recovery() -> None:
    """Use the new unit API, propagate one timeout, and recover next poll."""
    frame = sentence("GNRMC,070000.00,A,5225.692,N,02058.644,E,0,0,121026")
    payload = frame.encode().ljust(70, b"\x00")
    registers = [int.from_bytes(payload[i : i + 2], "big") for i in range(0, 70, 2)]
    unit = AsyncMock()
    unit.read_holding_registers.side_effect = [ModbusTimeoutError("timeout"), registers]
    client = Ewd108ModbusClient(unit)
    with patch(
        "custom_components.ewd108.api.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        result = await client.async_get_data()
        sleep.assert_awaited_once_with(1)
    assert result["latitude"] == pytest.approx(52.4282)
    assert result["longitude"] == pytest.approx(20.9774)
    assert unit.read_holding_registers.await_count == 2
    unit.read_holding_registers.assert_awaited_with(5, 35)


@pytest.mark.asyncio
async def test_short_modbus_response() -> None:
    """Never decode a partial register response as a complete GPS frame."""
    unit = AsyncMock()
    unit.read_holding_registers.return_value = [0] * 34
    with (
        patch(
            "custom_components.ewd108.api.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
        pytest.raises(Ewd108ClientCommunicationError, match="Incomplete"),
    ):
        await Ewd108ModbusClient(unit).async_get_data()
    assert unit.read_holding_registers.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]


@pytest.mark.asyncio
async def test_corrupt_frame_is_retried() -> None:
    """Retry a torn frame before declaring GPS unavailable for 30 seconds."""
    valid = sentence("GNRMC,070000.00,A,5225.692,N,02058.644,E,0,0,121026")
    corrupt = valid[:-2] + "00"

    def registers(frame: str) -> list[int]:
        payload = frame.encode().ljust(70, b"\x00")
        return [int.from_bytes(payload[i : i + 2], "big") for i in range(0, 70, 2)]

    unit = AsyncMock()
    unit.read_holding_registers.side_effect = [registers(corrupt), registers(valid)]
    with patch("custom_components.ewd108.api.asyncio.sleep", new_callable=AsyncMock):
        result = await Ewd108ModbusClient(unit).async_get_data()
    assert result["fix_valid"]
    assert unit.read_holding_registers.await_count == 2


@pytest.mark.asyncio
async def test_cancel_does_not_retry() -> None:
    """Unloading during a read must promptly cancel polling and retries."""
    unit = AsyncMock()
    unit.read_holding_registers.side_effect = asyncio.CancelledError
    with (
        patch(
            "custom_components.ewd108.api.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
        pytest.raises(asyncio.CancelledError),
    ):
        await Ewd108ModbusClient(unit).async_get_data()
    sleep.assert_not_awaited()
    assert unit.read_holding_registers.await_count == 1

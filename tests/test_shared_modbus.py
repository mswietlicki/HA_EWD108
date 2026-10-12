"""Exercise shared connection ownership and coherent tracker availability."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.modbus import async_get_temporary_unit, async_get_unit
from homeassistant.components.modbus.connection import DATA_MODBUS_CONNECTIONS
from homeassistant.core import HomeAssistant
from modbus_connection import ModbusSerialParams

from custom_components.ewd108.coordinator import Ewd108DataUpdateCoordinator
from custom_components.ewd108.device_tracker import Ewd108Tracker
from custom_components.ewd108.transport import (
    LegacyHubConflictError,
    check_legacy_hubs,
    check_running_legacy_hubs,
    connection_params,
)


@pytest.mark.asyncio
async def test_units_and_probe_share_one_connection() -> None:
    """Use the real HA API; unloading one consumer preserves the other."""
    hass = SimpleNamespace(data={})
    releases = []
    first = SimpleNamespace(entry_id="first", async_on_unload=releases.append)
    second = SimpleNamespace(entry_id="second", async_on_unload=releases.append)
    params = ModbusSerialParams(device="socket://localhost:1502", baudrate=115200)
    async_get_unit(hass, first, params, 16)
    async_get_unit(hass, second, params, 17)
    assert len(hass.data[DATA_MODBUS_CONNECTIONS]) == 1
    shared = next(iter(hass.data[DATA_MODBUS_CONNECTIONS].values()))
    assert shared.units == {"first": {16}, "second": {17}}
    assert not shared.connection.connected
    async with async_get_temporary_unit(hass, params, 16):
        assert shared.transient == 1
    assert shared.transient == 0
    await releases[0]()
    assert len(hass.data[DATA_MODBUS_CONNECTIONS]) == 1
    await releases[1]()
    assert not hass.data[DATA_MODBUS_CONNECTIONS]


@pytest.mark.parametrize("transport", ["tcp", "rtuovertcp"])
def test_legacy_poller_is_blocked(transport: str) -> None:
    """Changing framing must not open a competing socket to a YAML hub."""
    config = {"connection_type": transport, "host": "GPS.EXAMPLE", "port": 502}
    with pytest.raises(LegacyHubConflictError, match="rs485_3"):
        check_legacy_hubs(
            config,
            [
                {
                    "name": "rs485_3",
                    "type": "rtuovertcp",
                    "host": "gps.example",
                    "port": 502,
                }
            ],
        )
    check_legacy_hubs(config, [{"type": "tcp", "host": "other.example", "port": 502}])
    assert isinstance(connection_params(config), ModbusSerialParams) == (
        transport == "rtuovertcp"
    )


@pytest.mark.asyncio
async def test_tracker_rejects_loss_and_recovers(tmp_path: Path) -> None:
    """A valid pair, loss of fix and recovery produce no mixed coordinates."""
    hass = HomeAssistant(str(tmp_path))
    client = SimpleNamespace(async_get_data=AsyncMock())
    entry = SimpleNamespace(
        data={
            "host": "gps.example",
            "port": 502,
            "slave_id": 16,
            "connection_type": "rtuovertcp",
        },
        entry_id="gps",
        async_on_unload=Mock(),
        runtime_data=SimpleNamespace(client=client),
    )
    coordinator = Ewd108DataUpdateCoordinator(
        hass,
        name="ewd108",
        logger=logging.getLogger(__name__),
        config_entry=entry,
    )
    tracker = Ewd108Tracker(coordinator)
    fix = {
        "fix_valid": True,
        "latitude": 52.4282,
        "longitude": 20.9774,
        "timestamp_utc": datetime.now(UTC),
    }
    client.async_get_data.return_value = fix
    coordinator.data = await coordinator._async_update_data()
    assert tracker.available

    assert (tracker.latitude, tracker.longitude) == (52.4282, 20.9774)
    client.async_get_data.return_value = {**fix, "fix_valid": False, "latitude": 0}
    coordinator.data = await coordinator._async_update_data()
    assert not tracker.available
    assert tracker.latitude is None
    assert tracker.longitude is None
    client.async_get_data.return_value = {**fix, "timestamp_utc": datetime.now(UTC)}
    coordinator.data = await coordinator._async_update_data()
    assert tracker.available


def test_removed_yaml_hub_must_also_be_unloaded() -> None:
    """Editing YAML alone does not stop an existing competing connection."""
    config = {"connection_type": "rtuovertcp", "host": "gps.example", "port": 502}
    check_legacy_hubs(config, [])
    with pytest.raises(LegacyHubConflictError, match="Reload Modbus"):
        check_running_legacy_hubs(
            config,
            {
                "rs485_3": SimpleNamespace(endpoint=("tcp", "gps.example", 502)),
            },
        )

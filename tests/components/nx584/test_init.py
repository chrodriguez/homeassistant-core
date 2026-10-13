"""Tests for the NX584 integration setup."""

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from homeassistant.components.alarm_control_panel import (
    DOMAIN as ALARM_CONTROL_PANEL_DOMAIN,
)
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.nx584.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component

from tests.common import MockConfigEntry


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test setting up and unloading the config entry."""
    assert init_integration.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_not_ready(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nx584_client: MagicMock,
) -> None:
    """Test the entry is retried when the daemon cannot be reached."""
    mock_nx584_client.list_zones.side_effect = requests.exceptions.ConnectionError
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retry_on_version_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nx584_client: MagicMock,
    mock_watcher: MagicMock,
) -> None:
    """Test a failing version request retries setup and recovers."""
    mock_nx584_client.get_version.side_effect = requests.exceptions.ConnectionError
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    mock_nx584_client.get_version.side_effect = None
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN)) == 3


async def test_device_and_unique_ids(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test all entities belong to one device and have stable unique IDs."""
    entry_id = init_integration.entry_id
    devices = dr.async_entries_for_config_entry(device_registry, entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, entry_id)}
    assert device.name == "NX584"

    entities = er.async_entries_for_config_entry(entity_registry, entry_id)
    assert {entity.entity_id: entity.unique_id for entity in entities} == {
        "alarm_control_panel.nx584": f"{entry_id}_alarm",
        "binary_sensor.nx584_front": f"{entry_id}_zone_1",
        "binary_sensor.nx584_back": f"{entry_id}_zone_2",
        "binary_sensor.nx584_inside": f"{entry_id}_zone_3",
    }
    assert all(entity.device_id == device.id for entity in entities)


@pytest.mark.parametrize(
    ("service", "bypass"), [("bypass_zone", True), ("unbypass_zone", False)]
)
@pytest.mark.usefixtures("init_integration")
async def test_bypass_services(
    hass: HomeAssistant, mock_nx584_client: MagicMock, service: str, bypass: bool
) -> None:
    """Test the bypass services call the client on the alarm entity."""
    await hass.services.async_call(
        DOMAIN,
        service,
        {ATTR_ENTITY_ID: "alarm_control_panel.nx584", "zone": 3},
        blocking=True,
    )

    mock_nx584_client.set_bypass.assert_called_once_with(3, bypass)


async def test_unload_with_blocked_watcher(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nx584_client: MagicMock,
) -> None:
    """Test unloading while the watcher is blocked waiting for events."""
    blocked = threading.Event()
    release = threading.Event()
    calls = 0

    def get_events() -> list[dict]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        blocked.set()
        release.wait(5)
        return [{"type": "zone_status", "zone": 1, "zone_state": True}]

    mock_nx584_client.get_events.side_effect = get_events
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(blocked.wait, 5)
    watcher = next(
        thread for thread in threading.enumerate() if thread.name == "nx584_watcher"
    )

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert watcher.is_alive()

    release.set()
    await hass.async_add_executor_job(watcher.join, 5)
    assert not watcher.is_alive()
    assert calls == 2


@pytest.mark.usefixtures("mock_nx584_client", "mock_watcher")
async def test_yaml_import(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test both YAML platforms are imported into one working entry."""
    config = {
        BINARY_SENSOR_DOMAIN: {
            "platform": DOMAIN,
            "exclude_zones": [3],
            "zone_types": {1: "door"},
        },
        ALARM_CONTROL_PANEL_DOMAIN: {"platform": DOMAIN, "name": "Home"},
    }
    # Set up both platforms together, as Home Assistant does on startup.
    assert all(
        await asyncio.gather(
            async_setup_component(hass, BINARY_SENSOR_DOMAIN, config),
            async_setup_component(hass, ALARM_CONTROL_PANEL_DOMAIN, config),
        )
    )
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.title == "Home"
    assert entry.data == {"host": "localhost", "port": 5007}
    assert entry.options == {"exclude_zones": [3], "zone_types": {"1": "door"}}

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert [device.name for device in devices] == ["Home"]
    assert sorted(
        hass.states.async_entity_ids((ALARM_CONTROL_PANEL_DOMAIN, BINARY_SENSOR_DOMAIN))
    ) == [
        "alarm_control_panel.home",
        "binary_sensor.home_back",
        "binary_sensor.home_front",
    ]
    assert (
        hass.states.get("binary_sensor.home_front").attributes["device_class"] == "door"
    )
    assert issue_registry.async_get_issue(
        HOMEASSISTANT_DOMAIN, f"deprecated_yaml_{DOMAIN}"
    )


@pytest.mark.usefixtures("mock_nx584_client", "mock_watcher")
async def test_yaml_import_two_daemons(hass: HomeAssistant) -> None:
    """Test platforms pointing at different daemons create two entries."""
    config = {
        BINARY_SENSOR_DOMAIN: {"platform": DOMAIN, "host": "panel-a"},
        ALARM_CONTROL_PANEL_DOMAIN: {"platform": DOMAIN, "host": "panel-b"},
    }
    assert await async_setup_component(hass, BINARY_SENSOR_DOMAIN, config)
    await hass.async_block_till_done()

    assert sorted(
        entry.data["host"] for entry in hass.config_entries.async_entries(DOMAIN)
    ) == ["panel-a", "panel-b"]


async def test_yaml_import_cannot_connect(
    hass: HomeAssistant,
    mock_nx584_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test a failed YAML import raises the integration repair issue."""
    mock_nx584_client.list_zones.side_effect = requests.exceptions.ConnectionError
    assert await async_setup_component(
        hass,
        ALARM_CONTROL_PANEL_DOMAIN,
        {ALARM_CONTROL_PANEL_DOMAIN: {"platform": DOMAIN}},
    )
    await hass.async_block_till_done()

    assert not hass.config_entries.async_entries(DOMAIN)
    assert issue_registry.async_get_issue(
        DOMAIN, "deprecated_yaml_import_issue_cannot_connect"
    )
    assert not issue_registry.async_get_issue(
        HOMEASSISTANT_DOMAIN, f"deprecated_yaml_{DOMAIN}"
    )


@pytest.mark.usefixtures("mock_nx584_client", "mock_watcher")
@pytest.mark.parametrize(
    "config",
    [
        {"exclude_zones": ["a"]},
        {"zone_types": {"a": "b"}},
        {"zone_types": {1: "notatype"}},
        {"zone_types": {"notazone": "motion"}},
    ],
)
async def test_yaml_bad_config(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Test invalid YAML is skipped and the valid platform is still imported."""
    assert await async_setup_component(
        hass,
        ALARM_CONTROL_PANEL_DOMAIN,
        {
            ALARM_CONTROL_PANEL_DOMAIN: {"platform": DOMAIN, "name": "Home"},
            BINARY_SENSOR_DOMAIN: [
                {"platform": DOMAIN, **config},
                {"name": "not an nx584 platform"},
            ],
        },
    )
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].title == "Home"
    assert entries[0].options == {}

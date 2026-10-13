"""The tests for the nx584 sensor platform."""

from unittest import mock

import pytest
import requests

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.nx584 import binary_sensor as nx584
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


class StopMe(Exception):
    """Stop helper."""


@pytest.fixture
def entry() -> MockConfigEntry:
    """Return a config entry for building entities directly."""
    return MockConfigEntry(domain="nx584", entry_id="test_entry", title="NX584")


async def test_nx584_sensor_setup(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_nx584_client: mock.MagicMock,
    mock_watcher: mock.MagicMock,
) -> None:
    """Test zone sensors are created from the config entry."""
    assert sorted(hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN)) == [
        "binary_sensor.nx584_back",
        "binary_sensor.nx584_front",
        "binary_sensor.nx584_inside",
    ]
    state = hass.states.get("binary_sensor.nx584_front")
    assert state.state == STATE_OFF
    assert state.attributes["device_class"] == "opening"
    assert state.attributes["zone_number"] == 1
    assert not state.attributes["bypassed"]

    mock_watcher.assert_called_once()
    assert mock_watcher.call_args.args[0] is mock_nx584_client
    assert sorted(mock_watcher.call_args.args[1]) == [1, 2, 3]
    mock_watcher.return_value.start.assert_called_once()

    await hass.config_entries.async_unload(init_integration.entry_id)
    mock_watcher.return_value.stop.assert_called_once()


async def test_nx584_sensor_setup_version_too_old(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nx584_client: mock.MagicMock,
    mock_watcher: mock.MagicMock,
) -> None:
    """Test no zone sensors are created if the server is too old."""
    mock_nx584_client.get_version.return_value = "1.0"
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN) == []
    mock_watcher.assert_not_called()


async def test_nx584_sensor_setup_no_zones(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nx584_client: mock.MagicMock,
    mock_watcher: mock.MagicMock,
) -> None:
    """Test the setup with no zones."""
    mock_nx584_client.list_zones.return_value = []
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN) == []
    mock_watcher.assert_not_called()


@pytest.mark.usefixtures("mock_nx584_client", "mock_watcher")
async def test_zone_types_from_stored_options(hass: HomeAssistant) -> None:
    """Test stored options exclude zones, ignore unknown ones and set types."""
    entry = MockConfigEntry(
        domain="nx584",
        data={"host": "localhost", "port": 5007},
        title="NX584",
        options={"exclude_zones": [1, 9], "zone_types": {"2": "motion"}},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.nx584_front") is None
    assert (
        hass.states.get("binary_sensor.nx584_back").attributes["device_class"]
        == "motion"
    )
    assert (
        hass.states.get("binary_sensor.nx584_inside").attributes["device_class"]
        == "opening"
    )


def test_nx584_zone_sensor_normal(entry: MockConfigEntry) -> None:
    """Test for the NX584 zone sensor."""
    zone = {"number": 1, "name": "foo", "state": True}
    sensor = nx584.NX584ZoneSensor(entry, zone, "motion")
    assert sensor.name == "foo"
    assert sensor.unique_id == "test_entry_zone_1"
    assert not sensor.should_poll
    assert sensor.is_on
    assert sensor.extra_state_attributes["zone_number"] == 1
    assert not sensor.extra_state_attributes["bypassed"]

    zone["state"] = False
    assert not sensor.is_on


def test_nx584_zone_sensor_bypassed(entry: MockConfigEntry) -> None:
    """Test for the NX584 zone sensor."""
    zone = {"number": 1, "name": "foo", "state": True, "bypassed": True}
    sensor = nx584.NX584ZoneSensor(entry, zone, "motion")
    assert sensor.name == "foo"
    assert not sensor.should_poll
    assert sensor.is_on
    assert sensor.extra_state_attributes["zone_number"] == 1
    assert sensor.extra_state_attributes["bypassed"]

    zone["state"] = False
    zone["bypassed"] = False
    assert not sensor.is_on
    assert not sensor.extra_state_attributes["bypassed"]


@mock.patch.object(nx584.NX584ZoneSensor, "schedule_update_ha_state")
def test_nx584_watcher_process_zone_event(mock_update, entry: MockConfigEntry) -> None:
    """Test the processing of zone events."""
    zone1 = {"number": 1, "name": "foo", "state": True}
    zone2 = {"number": 2, "name": "bar", "state": True}
    zones = {
        1: nx584.NX584ZoneSensor(entry, zone1, "motion"),
        2: nx584.NX584ZoneSensor(entry, zone2, "motion"),
    }
    watcher = nx584.NX584Watcher(None, zones)
    watcher._process_zone_event({"zone": 1, "zone_state": False})
    assert not zone1["state"]
    assert mock_update.call_count == 1


@mock.patch.object(nx584.NX584ZoneSensor, "schedule_update_ha_state")
def test_nx584_watcher_process_zone_event_updates_bypass(
    mock_update, entry: MockConfigEntry
) -> None:
    """Test the processing of zone events updates bypass state."""
    zone = {"number": 1, "name": "foo", "state": True, "bypassed": False}
    zones = {1: nx584.NX584ZoneSensor(entry, zone, "motion")}
    watcher = nx584.NX584Watcher(None, zones)

    watcher._process_zone_event(
        {"zone": 1, "zone_state": False, "zone_flags": ["Bypass"]}
    )

    assert zone["bypassed"]
    assert not zone["state"]

    watcher._process_zone_event({"zone": 1, "zone_state": True, "zone_flags": []})

    assert not zone["bypassed"]
    assert zone["state"]
    assert mock_update.call_count == 2


@mock.patch.object(nx584.NX584ZoneSensor, "schedule_update_ha_state")
def test_nx584_watcher_process_zone_event_missing_zone(mock_update) -> None:
    """Test the processing of zone events with missing zones."""
    watcher = nx584.NX584Watcher(None, {})
    watcher._process_zone_event({"zone": 1, "zone_state": False})
    assert not mock_update.called


def test_nx584_watcher_run_with_zone_events() -> None:
    """Test the zone events."""
    empty_me = [1, 2]

    def fake_get_events():
        """Return nothing twice, then some events."""
        if empty_me:
            empty_me.pop()
            return None
        return fake_events

    client = mock.MagicMock()
    fake_events = [
        {"zone": 1, "zone_state": True, "type": "zone_status"},
        {"zone": 2, "foo": False},
    ]
    client.get_events.side_effect = fake_get_events
    watcher = nx584.NX584Watcher(client, {})

    @mock.patch.object(watcher, "_process_zone_event")
    def run(fake_process):
        """Run a fake process."""
        fake_process.side_effect = StopMe
        with pytest.raises(StopMe):
            watcher._run()
        assert fake_process.call_count == 1
        assert fake_process.call_args == mock.call(fake_events[0])

    run()
    assert client.get_events.call_count == 3


def test_nx584_watcher_run_retries_failures() -> None:
    """Test the retries with failures."""
    empty_me = [1, 2]

    def fake_run():
        """Fake runner."""
        if empty_me:
            empty_me.pop()
            raise requests.exceptions.ConnectionError
        raise StopMe

    watcher = nx584.NX584Watcher(None, {})
    with (
        mock.patch.object(watcher, "_run") as mock_inner,
        mock.patch.object(watcher._stop_event, "wait") as mock_wait,
    ):
        mock_inner.side_effect = fake_run
        with pytest.raises(StopMe):
            watcher.run()
        assert mock_inner.call_count == 3
    mock_wait.assert_has_calls([mock.call(10), mock.call(10)])


def test_nx584_watcher_stop() -> None:
    """Test events that arrive after stop are not processed."""
    watcher = nx584.NX584Watcher(mock.MagicMock(), {})

    def fake_get_events():
        watcher.stop()
        return [{"zone": 1, "zone_state": True, "type": "zone_status"}]

    watcher._client.get_events.side_effect = fake_get_events
    with mock.patch.object(watcher, "_process_events") as mock_process:
        watcher.run()

    mock_process.assert_not_called()

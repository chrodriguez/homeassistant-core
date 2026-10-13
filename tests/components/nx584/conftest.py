"""Common fixtures for the NX584 tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.nx584.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.nx584.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_nx584_client() -> Generator[MagicMock]:
    """Mock the NX584 client."""
    with patch("nx584.client.Client", autospec=True) as mock_client_class:
        client = mock_client_class.return_value
        client.list_zones.return_value = [
            {"name": "front", "number": 1, "state": False, "bypassed": False},
            {"name": "back", "number": 2, "state": False, "bypassed": False},
            {"name": "inside", "number": 3, "state": False, "bypassed": False},
        ]
        client.list_partitions.return_value = [{"armed": False, "condition_flags": []}]
        client.get_version.return_value = "1.1"
        client.get_events.return_value = []
        yield client


@pytest.fixture
def mock_watcher() -> Generator[MagicMock]:
    """Mock the zone event watcher thread."""
    with patch(
        "homeassistant.components.nx584.binary_sensor.NX584Watcher", autospec=True
    ) as mock_watcher_class:
        yield mock_watcher_class


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "localhost", CONF_PORT: 5007},
        title="NX584",
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nx584_client: MagicMock,
    mock_watcher: MagicMock,
) -> MockConfigEntry:
    """Set up the NX584 integration for testing."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry

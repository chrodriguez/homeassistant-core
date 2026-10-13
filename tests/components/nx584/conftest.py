"""Common fixtures for the NX584 tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.nx584.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT

from tests.common import MockConfigEntry


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
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "localhost", CONF_PORT: 5007},
        title="NX584",
    )

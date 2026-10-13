"""Tests for the NX584 config flow."""

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from homeassistant.components.nx584.const import DOMAIN
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    SOURCE_USER,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry

USER_INPUT = {CONF_HOST: "localhost", CONF_PORT: 5007}


@pytest.mark.usefixtures("mock_nx584_client", "mock_setup_entry")
async def test_user_flow(hass: HomeAssistant) -> None:
    """Test the user flow creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "NX584"
    assert result["data"] == USER_INPUT


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (requests.exceptions.ConnectionError, "cannot_connect"),
        (Exception, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_nx584_client: MagicMock,
    side_effect: type[Exception],
    error: str,
) -> None:
    """Test the user flow shows errors and recovers."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_nx584_client.list_zones.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_nx584_client.list_zones.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_nx584_client")
async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the user flow aborts when the daemon is already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_nx584_client", "mock_setup_entry")
async def test_import(hass: HomeAssistant) -> None:
    """Test importing the alarm YAML creates an entry named after it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={**USER_INPUT, CONF_NAME: "Home"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == USER_INPUT
    assert result["options"] == {}


@pytest.mark.usefixtures("mock_nx584_client", "mock_setup_entry")
async def test_import_both_platforms_one_entry(hass: HomeAssistant) -> None:
    """Test the merged YAML of both platforms creates one complete entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={
            **USER_INPUT,
            CONF_NAME: "Home",
            "exclude_zones": [3],
            "zone_types": {1: "door"},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == USER_INPUT
    assert result["options"] == {"exclude_zones": [3], "zone_types": {"1": "door"}}


@pytest.mark.usefixtures("mock_nx584_client", "mock_setup_entry")
async def test_import_fills_unset_values(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test an import fills the title and options of a UI entry left unset."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={**USER_INPUT, CONF_NAME: "Home", "exclude_zones": [3]},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.title == "Home"
    assert mock_config_entry.options == {"exclude_zones": [3]}


@pytest.mark.usefixtures("mock_nx584_client", "mock_setup_entry")
async def test_import_does_not_overwrite(hass: HomeAssistant) -> None:
    """Test a later import keeps the title and options already set."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        title="Custom",
        options={"exclude_zones": [2], "zone_types": {"3": "motion"}},
    )
    entry.add_to_hass(hass)

    for import_data in (
        {**USER_INPUT, CONF_NAME: "Home"},
        {**USER_INPUT, "exclude_zones": [3], "zone_types": {1: "door"}},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    assert entry.title == "Custom"
    assert entry.options == {"exclude_zones": [2], "zone_types": {"3": "motion"}}


@pytest.mark.usefixtures("mock_nx584_client", "mock_setup_entry")
async def test_import_different_hosts(hass: HomeAssistant) -> None:
    """Test platforms pointing at different daemons create two entries."""
    for host in ("panel-a", "panel-b"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={CONF_HOST: host, CONF_PORT: 5007},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    assert sorted(
        entry.data[CONF_HOST] for entry in hass.config_entries.async_entries(DOMAIN)
    ) == ["panel-a", "panel-b"]


async def test_import_cannot_connect(
    hass: HomeAssistant, mock_nx584_client: MagicMock
) -> None:
    """Test the import aborts when the daemon cannot be reached."""
    mock_nx584_client.list_zones.side_effect = requests.exceptions.ConnectionError
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert not hass.config_entries.async_entries(DOMAIN)


def _schema_defaults(result: ConfigFlowResult) -> dict[str, Any]:
    """Return the default or suggested value of each form field."""
    values: dict[str, Any] = {}
    for key in result["data_schema"].schema:
        if (suggested := (key.description or {}).get("suggested_value")) is not None:
            values[str(key)] = suggested
        elif callable(key.default):
            values[str(key)] = key.default()
    return values


@pytest.mark.usefixtures("mock_watcher")
async def test_options_flow(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test excluding a zone and changing a zone type."""
    assert entity_registry.async_get("binary_sensor.nx584_inside")

    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"exclude_zones": ["3"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_types"
    assert _schema_defaults(result) == {"1 – front": "opening", "2 – back": "opening"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"1 – front": "door", "2 – back": "opening"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {
        "exclude_zones": [3],
        "zone_types": {"1": "door", "2": "opening"},
    }
    assert init_integration.state is ConfigEntryState.LOADED
    assert entity_registry.async_get("binary_sensor.nx584_inside") is None
    assert hass.states.get("binary_sensor.nx584_inside") is None
    assert (
        hass.states.get("binary_sensor.nx584_front").attributes["device_class"]
        == "door"
    )


@pytest.mark.usefixtures("mock_watcher")
async def test_options_flow_cannot_connect(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_nx584_client: MagicMock,
) -> None:
    """Test the options flow aborts when the daemon cannot be reached."""
    mock_nx584_client.list_zones.side_effect = requests.exceptions.ConnectionError

    result = await hass.config_entries.options.async_init(init_integration.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("mock_nx584_client", "mock_watcher")
async def test_options_prefilled_from_import(hass: HomeAssistant) -> None:
    """Test the form starts from the stored options, ignoring unknown zones."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        title="NX584",
        options={"exclude_zones": [3, 9], "zone_types": {"1": "door"}},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _schema_defaults(result) == {"exclude_zones": ["3"]}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"exclude_zones": ["3"]}
    )
    assert _schema_defaults(result) == {"1 – front": "door", "2 – back": "opening"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"1 – front": "door", "2 – back": "opening"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "exclude_zones": [3],
        "zone_types": {"1": "door", "2": "opening"},
    }

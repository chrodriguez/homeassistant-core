"""Tests for the NX584 config flow."""

from unittest.mock import MagicMock

import pytest
import requests

from homeassistant.components.nx584.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry

USER_INPUT = {CONF_HOST: "localhost", CONF_PORT: 5007}


@pytest.mark.usefixtures("mock_nx584_client")
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

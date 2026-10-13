"""Config flow for the NX584 integration."""

import logging
from typing import Any, override

from nx584 import client as nx584_client
import probatio
import requests

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DEFAULT_HOST, DEFAULT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST, default=DEFAULT_HOST): str,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): probatio.Port(),
    }
)


class NX584ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NX584."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host: str = user_input[CONF_HOST]
            port: int = user_input[CONF_PORT]
            self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})

            client = nx584_client.Client(f"http://{host}:{port}")
            try:
                await self.hass.async_add_executor_job(client.list_zones)
            except requests.exceptions.ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

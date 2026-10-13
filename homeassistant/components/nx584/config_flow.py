"""Config flow for the NX584 integration."""

import logging
from typing import Any, override

from nx584 import client as nx584_client
import probatio
import requests

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import (
    CONF_EXCLUDE_ZONES,
    CONF_ZONE_TYPES,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST, default=DEFAULT_HOST): str,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): probatio.Port(),
    }
)


async def _async_can_connect(hass: HomeAssistant, host: str, port: int) -> None:
    """Check that the daemon answers; raise on failure."""
    client = nx584_client.Client(f"http://{host}:{port}")
    await hass.async_add_executor_job(client.list_zones)


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

            try:
                await _async_can_connect(self.hass, host, port)
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

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import the YAML configuration of one daemon."""
        host: str = import_data[CONF_HOST]
        port: int = import_data[CONF_PORT]
        name: str | None = import_data.get(CONF_NAME)
        options: dict[str, Any] = {}
        if CONF_EXCLUDE_ZONES in import_data:
            options[CONF_EXCLUDE_ZONES] = list(import_data[CONF_EXCLUDE_ZONES])
        if CONF_ZONE_TYPES in import_data:
            options[CONF_ZONE_TYPES] = {
                str(zone): zone_type
                for zone, zone_type in import_data[CONF_ZONE_TYPES].items()
            }

        for entry in self._async_current_entries(include_ignore=False):
            if entry.data[CONF_HOST] != host or entry.data[CONF_PORT] != port:
                continue
            # Never overwrite what the user already set, only fill what is unset.
            title = entry.title
            if title == DEFAULT_NAME and name and name != DEFAULT_NAME:
                title = name
            fill_options = bool(options) and not entry.options
            self.hass.config_entries.async_update_entry(
                entry, title=title, options=options if fill_options else entry.options
            )
            if fill_options:
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(reason="already_configured")

        try:
            await _async_can_connect(self.hass, host, port)
        except requests.exceptions.ConnectionError:
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(
            title=name or DEFAULT_NAME,
            data={CONF_HOST: host, CONF_PORT: port},
            options=options,
        )

"""Config flow for the NX584 integration."""

import logging
from typing import Any, override

from nx584 import client as nx584_client
import probatio
import requests

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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


async def _async_list_zones(
    hass: HomeAssistant, host: str, port: int
) -> list[dict[str, Any]]:
    """Return the zones the daemon reports; raise if it cannot be reached."""
    client = nx584_client.Client(f"http://{host}:{port}")
    return await hass.async_add_executor_job(client.list_zones)


class NX584ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NX584."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> NX584OptionsFlow:
        """Create the options flow."""
        return NX584OptionsFlow()

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
                await _async_list_zones(self.hass, host, port)
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
            await _async_list_zones(self.hass, host, port)
        except requests.exceptions.ConnectionError:
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(
            title=name or DEFAULT_NAME,
            data={CONF_HOST: host, CONF_PORT: port},
            options=options,
        )


class NX584OptionsFlow(OptionsFlowWithReload):
    """Handle the zone options of an NX584 entry."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._zones: dict[int, str] = {}
        self._exclude_zones: list[int] = []

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the zones to exclude."""
        if user_input is not None:
            self._exclude_zones = sorted(
                int(zone) for zone in user_input.get(CONF_EXCLUDE_ZONES, [])
            )
            return await self.async_step_zone_types()

        data = self.config_entry.data
        try:
            zones = await _async_list_zones(self.hass, data[CONF_HOST], data[CONF_PORT])
        except requests.exceptions.ConnectionError:
            return self.async_abort(reason="cannot_connect")
        self._zones = {zone["number"]: zone["name"] for zone in zones}

        schema = probatio.Schema(
            {
                probatio.Optional(CONF_EXCLUDE_ZONES): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=str(number), label=label)
                            for number, label in self._zone_labels().items()
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        # Zones the daemon no longer reports are dropped from the selection.
        excluded = [
            str(number)
            for number in self.config_entry.options.get(CONF_EXCLUDE_ZONES, [])
            if number in self._zones
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_EXCLUDE_ZONES: excluded}
            ),
        )

    async def async_step_zone_types(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the type of each zone that is not excluded."""
        # The zone label is the field key so the form shows which zone it is.
        labels = {
            number: label
            for number, label in self._zone_labels().items()
            if number not in self._exclude_zones
        }
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_EXCLUDE_ZONES: self._exclude_zones,
                    CONF_ZONE_TYPES: {
                        str(number): user_input[label]
                        for number, label in labels.items()
                    },
                }
            )

        zone_types: dict[str, str] = self.config_entry.options.get(CONF_ZONE_TYPES, {})
        device_class_selector = SelectSelector(
            SelectSelectorConfig(
                options=[
                    device_class.value for device_class in BinarySensorDeviceClass
                ],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="device_class",
                sort=True,
            )
        )
        return self.async_show_form(
            step_id="zone_types",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        label,
                        default=zone_types.get(
                            str(number), BinarySensorDeviceClass.OPENING.value
                        ),
                    ): device_class_selector
                    for number, label in labels.items()
                }
            ),
        )

    def _zone_labels(self) -> dict[int, str]:
        """Return a readable label for each zone, by zone number."""
        return {number: f"{number} – {name}" for number, name in self._zones.items()}

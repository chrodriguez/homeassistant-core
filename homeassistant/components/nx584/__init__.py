"""Support for NX584 alarm control panels."""

from dataclasses import dataclass
from typing import Any

from nx584 import client as nx584_client
import probatio
import requests

from homeassistant.components.alarm_control_panel import (
    DOMAIN as ALARM_CONTROL_PANEL_DOMAIN,
)
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.config import config_per_platform
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType

from .alarm_control_panel import PLATFORM_SCHEMA as ALARM_PLATFORM_SCHEMA
from .binary_sensor import PLATFORM_SCHEMA as BINARY_SENSOR_PLATFORM_SCHEMA
from .const import CONF_EXCLUDE_ZONES, CONF_ZONE_TYPES, DEFAULT_NAME, DOMAIN
from .services import async_setup_services

CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)

PLATFORMS = [Platform.ALARM_CONTROL_PANEL, Platform.BINARY_SENSOR]


@dataclass
class NX584Data:
    """Runtime data for an NX584 config entry."""

    client: nx584_client.Client
    zones: list[dict[str, Any]]
    version: str


type NX584ConfigEntry = ConfigEntry[NX584Data]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the NX584 component."""
    async_setup_services(hass)

    # The alarm and binary sensor YAML platforms of one daemon are merged into a
    # single import, so the entry is complete before any entity is created.
    imports: dict[tuple[str, int], dict[str, Any]] = {}
    for domain, schema, keys in (
        (ALARM_CONTROL_PANEL_DOMAIN, ALARM_PLATFORM_SCHEMA, (CONF_NAME,)),
        (
            BINARY_SENSOR_DOMAIN,
            BINARY_SENSOR_PLATFORM_SCHEMA,
            (CONF_EXCLUDE_ZONES, CONF_ZONE_TYPES),
        ),
    ):
        for platform, platform_config in config_per_platform(config, domain):
            if platform != DOMAIN:
                continue
            try:
                validated = schema(platform_config)
            except probatio.Invalid:
                # The platform setup reports the invalid configuration.
                continue
            host: str = validated[CONF_HOST]
            port: int = validated[CONF_PORT]
            import_data = imports.setdefault(
                (host, port), {CONF_HOST: host, CONF_PORT: port}
            )
            import_data.update({key: validated[key] for key in keys})

    for import_data in imports.values():
        hass.async_create_task(_async_import(hass, import_data))
    return True


async def _async_import(hass: HomeAssistant, import_data: dict[str, Any]) -> None:
    """Import one daemon's YAML configuration and raise the repair issue."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data
    )

    if (
        result["type"] is FlowResultType.ABORT
        and result["reason"] != "already_configured"
    ):
        async_create_issue(
            hass,
            DOMAIN,
            "deprecated_yaml_import_issue_cannot_connect",
            breaks_in_ha_version="2027.5.0",
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=IssueSeverity.WARNING,
            translation_key="deprecated_yaml_import_issue_cannot_connect",
            translation_placeholders={
                "domain": DOMAIN,
                "integration_title": DEFAULT_NAME,
            },
        )
        return

    async_create_issue(
        hass,
        HOMEASSISTANT_DOMAIN,
        f"deprecated_yaml_{DOMAIN}",
        breaks_in_ha_version="2027.5.0",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        translation_placeholders={
            "domain": DOMAIN,
            "integration_title": DEFAULT_NAME,
        },
    )


def _fetch_data(url: str) -> NX584Data:
    """Connect to the daemon and fetch the data needed for setup."""
    client = nx584_client.Client(url)
    return NX584Data(client, client.list_zones(), client.get_version())


async def async_setup_entry(hass: HomeAssistant, entry: NX584ConfigEntry) -> bool:
    """Set up NX584 from a config entry."""
    url = f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"
    try:
        entry.runtime_data = await hass.async_add_executor_job(_fetch_data, url)
    except requests.exceptions.ConnectionError as err:
        raise ConfigEntryNotReady(f"Unable to connect to {url}") from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NX584ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

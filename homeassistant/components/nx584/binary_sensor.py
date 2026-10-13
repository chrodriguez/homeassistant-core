"""Support for exposing NX584 elements as sensors."""

import logging
import threading
from typing import TYPE_CHECKING, Any, override

from nx584 import client as nx584_client
import probatio
import requests

from homeassistant.components.binary_sensor import (
    DEVICE_CLASSES_SCHEMA as BINARY_SENSOR_DEVICE_CLASSES_SCHEMA,
    PLATFORM_SCHEMA as BINARY_SENSOR_PLATFORM_SCHEMA,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_EXCLUDE_ZONES, CONF_ZONE_TYPES, DEFAULT_HOST, DEFAULT_PORT
from .entity import NX584Entity

if TYPE_CHECKING:
    from . import NX584ConfigEntry

_LOGGER = logging.getLogger(__name__)

BYPASS_ZONE_FLAGS = {"Bypass", "Inhibit"}

ZONE_TYPES_SCHEMA = probatio.Schema(
    {cv.positive_int: BINARY_SENSOR_DEVICE_CLASSES_SCHEMA}
)

PLATFORM_SCHEMA = BINARY_SENSOR_PLATFORM_SCHEMA.extend(
    {
        probatio.Optional(CONF_EXCLUDE_ZONES, default=[]): probatio.All(
            probatio.EnsureList(), [cv.positive_int]
        ),
        probatio.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
        probatio.Optional(CONF_PORT, default=DEFAULT_PORT): probatio.Port(),
        probatio.Optional(CONF_ZONE_TYPES, default={}): ZONE_TYPES_SCHEMA,
    }
)


def _zone_flags_indicate_bypass(zone_flags: list[str]) -> bool:
    """Return if NX584 zone condition flags indicate bypass."""
    return not BYPASS_ZONE_FLAGS.isdisjoint(zone_flags)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the YAML platform.

    The YAML configuration is imported into a config entry by the integration
    setup; the entities are created from that entry.
    """


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NX584ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the NX584 zone sensors from a config entry."""
    data = entry.runtime_data
    if [int(v) for v in data.version.split(".")] < [1, 1]:
        _LOGGER.error("NX584 is too old to use for sensors (>=0.2 required)")
        return

    exclude: list[int] = entry.options.get(CONF_EXCLUDE_ZONES, [])
    zone_types: dict[str, str] = entry.options.get(CONF_ZONE_TYPES, {})
    zone_sensors = {
        zone["number"]: NX584ZoneSensor(
            entry,
            zone,
            BinarySensorDeviceClass(
                zone_types.get(str(zone["number"]), BinarySensorDeviceClass.OPENING)
            ),
        )
        for zone in data.zones
        if zone["number"] not in exclude
    }
    if not zone_sensors:
        _LOGGER.warning("No zones found on NX584")
        return

    async_add_entities(zone_sensors.values())
    watcher = NX584Watcher(data.client, zone_sensors)
    entry.async_on_unload(watcher.stop)
    watcher.start()


class NX584ZoneSensor(NX584Entity, BinarySensorEntity):
    """Representation of a NX584 zone as a sensor."""

    _attr_should_poll = False

    def __init__(
        self,
        entry: NX584ConfigEntry,
        zone: dict[str, Any],
        zone_type: BinarySensorDeviceClass,
    ) -> None:
        """Initialize the nx584 binary sensor."""
        super().__init__(entry, f"zone_{zone['number']}")
        self._zone = zone
        self._attr_name = zone["name"]
        self._attr_device_class = zone_type

    @property
    @override
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        # True means "faulted" or "open" or "abnormal state"
        return self._zone["state"]

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "zone_number": self._zone["number"],
            "bypassed": self._zone.get("bypassed", False),
        }


class NX584Watcher(threading.Thread):
    """Event listener thread to process NX584 events."""

    def __init__(
        self,
        client: nx584_client.Client,
        zone_sensors: dict[int, NX584ZoneSensor],
    ) -> None:
        """Initialize NX584 watcher thread."""
        super().__init__(name="nx584_watcher", daemon=True)
        self._client = client
        self._zone_sensors = zone_sensors
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Ask the watcher to stop after the pending request returns."""
        self._stop_event.set()

    def _process_zone_event(self, event):
        zone = event["zone"]
        if not (zone_sensor := self._zone_sensors.get(zone)):
            return
        zone_sensor._zone["state"] = event["zone_state"]  # noqa: SLF001
        if "zone_flags" in event:
            zone_sensor._zone["bypassed"] = _zone_flags_indicate_bypass(  # noqa: SLF001
                event["zone_flags"]
            )
        zone_sensor.schedule_update_ha_state()

    def _process_events(self, events):
        for event in events:
            if event.get("type") == "zone_status":
                self._process_zone_event(event)

    def _run(self):
        """Throw away any existing events so we don't replay history."""
        self._client.get_events()
        while not self._stop_event.is_set():
            events = self._client.get_events()
            if events and not self._stop_event.is_set():
                self._process_events(events)

    @override
    def run(self):
        """Run the watcher."""
        while not self._stop_event.is_set():
            try:
                self._run()
            except requests.exceptions.ConnectionError:
                _LOGGER.error("Failed to reach NX584 server")
                self._stop_event.wait(10)

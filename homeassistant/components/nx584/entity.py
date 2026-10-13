"""Base entity for the NX584 integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class NX584Entity(Entity):
    """Base class for NX584 entities, attached to the panel device."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, unique_id: str) -> None:
        """Initialize the entity."""
        self._attr_unique_id = f"{entry.entry_id}_{unique_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

"""Shared helpers for Amber Express Trader configuration entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_SITE_ID, CONF_SITE_NAME, DOMAIN


class AmberConfigEntity(Entity):
    """Base entity for site-scoped configuration controls."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        option_key: str,
    ) -> None:
        """Initialize a configuration entity."""
        self._hass = hass
        self._entry = entry
        self._subentry = subentry
        self._option_key = option_key
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)
        self._attr_unique_id = f"{self._site_id}_{option_key}"
        self._attr_translation_key = option_key

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            name=f"Amber Express Trader - {self._site_name}",
            manufacturer="Amber Electric",
            configuration_url="https://app.amber.com.au",
        )

    def _current_data(self) -> dict:
        """Return fresh subentry data."""
        subentry = self._entry.subentries.get(self._subentry.subentry_id)
        if subentry is None:
            return {}
        return subentry.data

    def _option_value(self, default: object) -> object:
        """Return the current option value."""
        return self._current_data().get(self._option_key, default)

    async def _async_update_option(self, value: object) -> None:
        """Persist an updated subentry option."""
        subentry = self._entry.subentries.get(self._subentry.subentry_id)
        if subentry is None:
            return

        updated_data = dict(subentry.data)
        updated_data[self._option_key] = value
        self._hass.config_entries.async_update_subentry(
            self._entry,
            subentry,
            data=updated_data,
        )
        self.async_write_ha_state()

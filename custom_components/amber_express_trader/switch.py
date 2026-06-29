"""Switch platform for Amber Express Trader configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entities import AmberConfigEntity
from .const import (
    CONF_ALLOW_BATTERY_EXPORT,
    CONF_ALLOW_GRID_CHARGE,
    CONF_ENABLE_WEBSOCKET,
    CONF_WAIT_FOR_CONFIRMED,
    DEFAULT_ALLOW_BATTERY_EXPORT,
    DEFAULT_ALLOW_GRID_CHARGE,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_WAIT_FOR_CONFIRMED,
    SUBENTRY_TYPE_SITE,
)

if TYPE_CHECKING:
    from . import AmberConfigEntry


@dataclass(frozen=True, kw_only=True)
class AmberSwitchDescription:
    """Description for a site configuration switch."""

    key: str
    default: bool


SWITCH_DESCRIPTIONS: tuple[AmberSwitchDescription, ...] = (
    AmberSwitchDescription(key=CONF_ENABLE_WEBSOCKET, default=DEFAULT_ENABLE_WEBSOCKET),
    AmberSwitchDescription(key=CONF_WAIT_FOR_CONFIRMED, default=DEFAULT_WAIT_FOR_CONFIRMED),
    AmberSwitchDescription(key=CONF_ALLOW_GRID_CHARGE, default=DEFAULT_ALLOW_GRID_CHARGE),
    AmberSwitchDescription(key=CONF_ALLOW_BATTERY_EXPORT, default=DEFAULT_ALLOW_BATTERY_EXPORT),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express Trader switch entities for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[SwitchEntity] = [
            AmberConfigSwitch(hass, entry, subentry, description) for description in SWITCH_DESCRIPTIONS
        ]

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


class AmberConfigSwitch(AmberConfigEntity, SwitchEntity):
    """Switch entity for a boolean site configuration option."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: AmberSwitchDescription,
    ) -> None:
        """Initialize a configuration switch."""
        super().__init__(hass, entry, subentry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the current switch state."""
        value = self._option_value(self.entity_description.default)
        return bool(value)

    async def async_turn_on(self, **_: object) -> None:
        """Turn the option on."""
        await self._async_update_option(value=True)

    async def async_turn_off(self, **_: object) -> None:
        """Turn the option off."""
        await self._async_update_option(value=False)

"""Text platform for Amber Express Trader configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entities import AmberConfigEntity
from .const import (
    CONF_BATTERY_CHARGE_ENERGY_TODAY_ENTITY,
    CONF_BATTERY_DISCHARGE_ENERGY_TODAY_ENTITY,
    CONF_BATTERY_MIN_RESERVE_KWH,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_USABLE_KWH,
    CONF_FIXED_BOUNDARY_OFFSETS,
    CONF_GRID_POWER_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_INVERTER_MAX_CHARGE_KW,
    CONF_INVERTER_MAX_DISCHARGE_KW,
    CONF_NORMAL_EXPORT_LIMIT_KW,
    CONF_PV_ENERGY_TODAY_ENTITY,
    CONF_PV_FORECAST_REMAINING_TODAY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    DEFAULT_FIXED_BOUNDARY_OFFSETS,
    DEFAULT_SITE_CONTEXT_ENTITY,
    DEFAULT_SITE_CONTEXT_VALUE,
    SUBENTRY_TYPE_SITE,
)

if TYPE_CHECKING:
    from . import AmberConfigEntry


@dataclass(frozen=True, kw_only=True)
class AmberTextDescription:
    """Description for a site configuration text entity."""

    key: str
    default: str
    native_max: int = 255
    pattern: str | None = None


TEXT_DESCRIPTIONS: tuple[AmberTextDescription, ...] = (
    AmberTextDescription(
        key=CONF_FIXED_BOUNDARY_OFFSETS,
        default=DEFAULT_FIXED_BOUNDARY_OFFSETS,
        native_max=80,
        pattern=r"^\s*\d+(\s*,\s*\d+)*\s*$",
    ),
    AmberTextDescription(key=CONF_BATTERY_SOC_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_BATTERY_POWER_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_GRID_POWER_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_SOLAR_POWER_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_HOUSE_LOAD_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_PV_ENERGY_TODAY_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_PV_FORECAST_REMAINING_TODAY_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_BATTERY_CHARGE_ENERGY_TODAY_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_BATTERY_DISCHARGE_ENERGY_TODAY_ENTITY, default=DEFAULT_SITE_CONTEXT_ENTITY),
    AmberTextDescription(key=CONF_BATTERY_USABLE_KWH, default=DEFAULT_SITE_CONTEXT_VALUE),
    AmberTextDescription(key=CONF_BATTERY_MIN_RESERVE_KWH, default=DEFAULT_SITE_CONTEXT_VALUE),
    AmberTextDescription(key=CONF_INVERTER_MAX_CHARGE_KW, default=DEFAULT_SITE_CONTEXT_VALUE),
    AmberTextDescription(key=CONF_INVERTER_MAX_DISCHARGE_KW, default=DEFAULT_SITE_CONTEXT_VALUE),
    AmberTextDescription(key=CONF_NORMAL_EXPORT_LIMIT_KW, default=DEFAULT_SITE_CONTEXT_VALUE),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express Trader text entities for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[TextEntity] = [
            AmberConfigText(hass, entry, subentry, description) for description in TEXT_DESCRIPTIONS
        ]

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


class AmberConfigText(AmberConfigEntity, TextEntity):
    """Text entity for a string site configuration option."""

    _attr_mode = TextMode.TEXT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: AmberTextDescription,
    ) -> None:
        """Initialize a configuration text entity."""
        super().__init__(hass, entry, subentry, description.key)
        self.entity_description = description
        self._attr_native_max = description.native_max
        self._attr_pattern = description.pattern

    @property
    def native_value(self) -> str:
        """Return the current text option value."""
        value = self._option_value(self.entity_description.default)
        return value if isinstance(value, str) else self.entity_description.default

    async def async_set_value(self, value: str) -> None:
        """Update the text option."""
        await self._async_update_option(value.strip())

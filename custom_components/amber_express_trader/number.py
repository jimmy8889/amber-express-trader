"""Number platform for Amber Express Trader configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entities import AmberConfigEntity
from .const import (
    CONF_CHARGE_PRICE_CEILING,
    CONF_CONFIRMATION_TIMEOUT,
    CONF_DEMAND_WINDOW_PRICE,
    CONF_EXPORT_PRICE_FLOOR,
    CONF_FORECAST_INTERVALS,
    CONF_SPIKE_PRICE_THRESHOLD,
    CONF_TARGET_GRID_BUY_KWH,
    CONF_ZERO_PRICE_DEADBAND,
    DEFAULT_CHARGE_PRICE_CEILING,
    DEFAULT_CONFIRMATION_TIMEOUT,
    DEFAULT_DEMAND_WINDOW_PRICE,
    DEFAULT_EXPORT_PRICE_FLOOR,
    DEFAULT_FORECAST_INTERVALS,
    DEFAULT_SPIKE_PRICE_THRESHOLD,
    DEFAULT_TARGET_GRID_BUY_KWH,
    DEFAULT_ZERO_PRICE_DEADBAND,
    MAX_FORECAST_INTERVALS,
    SUBENTRY_TYPE_SITE,
)

if TYPE_CHECKING:
    from . import AmberConfigEntry


@dataclass(frozen=True, kw_only=True)
class AmberNumberDescription:
    """Description for a site configuration number."""

    key: str
    default: float
    native_min_value: float
    native_max_value: float
    native_step: float
    native_unit_of_measurement: str | None = None
    mode: NumberMode = NumberMode.BOX


NUMBER_DESCRIPTIONS: tuple[AmberNumberDescription, ...] = (
    AmberNumberDescription(
        key=CONF_CONFIRMATION_TIMEOUT,
        default=DEFAULT_CONFIRMATION_TIMEOUT,
        native_min_value=0,
        native_max_value=3600,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    AmberNumberDescription(
        key=CONF_FORECAST_INTERVALS,
        default=DEFAULT_FORECAST_INTERVALS,
        native_min_value=1,
        native_max_value=MAX_FORECAST_INTERVALS,
        native_step=1,
    ),
    AmberNumberDescription(
        key=CONF_DEMAND_WINDOW_PRICE,
        default=DEFAULT_DEMAND_WINDOW_PRICE,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        native_unit_of_measurement="$/kWh",
    ),
    AmberNumberDescription(
        key=CONF_ZERO_PRICE_DEADBAND,
        default=DEFAULT_ZERO_PRICE_DEADBAND,
        native_min_value=0,
        native_max_value=1,
        native_step=0.001,
        native_unit_of_measurement="$/kWh",
    ),
    AmberNumberDescription(
        key=CONF_EXPORT_PRICE_FLOOR,
        default=DEFAULT_EXPORT_PRICE_FLOOR,
        native_min_value=-10,
        native_max_value=10,
        native_step=0.001,
        native_unit_of_measurement="$/kWh",
    ),
    AmberNumberDescription(
        key=CONF_CHARGE_PRICE_CEILING,
        default=DEFAULT_CHARGE_PRICE_CEILING,
        native_min_value=-10,
        native_max_value=10,
        native_step=0.001,
        native_unit_of_measurement="$/kWh",
    ),
    AmberNumberDescription(
        key=CONF_SPIKE_PRICE_THRESHOLD,
        default=DEFAULT_SPIKE_PRICE_THRESHOLD,
        native_min_value=-10,
        native_max_value=10,
        native_step=0.001,
        native_unit_of_measurement="$/kWh",
    ),
    AmberNumberDescription(
        key=CONF_TARGET_GRID_BUY_KWH,
        default=DEFAULT_TARGET_GRID_BUY_KWH,
        native_min_value=0,
        native_max_value=200,
        native_step=0.1,
        native_unit_of_measurement="kWh",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express Trader number entities for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[NumberEntity] = [
            AmberConfigNumber(hass, entry, subentry, description) for description in NUMBER_DESCRIPTIONS
        ]

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


class AmberConfigNumber(AmberConfigEntity, NumberEntity):
    """Number entity for a numeric site configuration option."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: AmberNumberDescription,
    ) -> None:
        """Initialize a configuration number."""
        super().__init__(hass, entry, subentry, description.key)
        self.entity_description = description
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_mode = description.mode

    @property
    def native_value(self) -> float:
        """Return the current numeric option value."""
        value = self._option_value(self.entity_description.default)
        if isinstance(value, int | float):
            return float(value)
        return float(self.entity_description.default)

    async def async_set_native_value(self, value: float) -> None:
        """Update the numeric option."""
        if self._option_key in {CONF_CONFIRMATION_TIMEOUT, CONF_FORECAST_INTERVALS}:
            await self._async_update_option(int(value))
            return
        await self._async_update_option(float(value))

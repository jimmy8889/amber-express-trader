"""Sensor platform for Amber Express Trader integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DEMAND_WINDOW,
    ATTR_DESCRIPTOR,
    ATTR_DETAILED_FORECAST,
    ATTR_END_TIME,
    ATTR_ESTIMATE,
    ATTR_FORECAST,
    ATTR_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_CONTROLLED_LOAD,
    CHANNEL_FEED_IN,
    CHANNEL_GENERAL,
    CONF_CHARGE_PRICE_CEILING,
    CONF_DEMAND_WINDOW_PRICE,
    CONF_EXPORT_PRICE_FLOOR,
    CONF_PRICING_MODE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_SPIKE_PRICE_THRESHOLD,
    CONF_TARGET_GRID_BUY_KWH,
    CONF_ZERO_PRICE_DEADBAND,
    DEFAULT_CHARGE_PRICE_CEILING,
    DEFAULT_DEMAND_WINDOW_PRICE,
    DEFAULT_EXPORT_PRICE_FLOOR,
    DEFAULT_PRICING_MODE,
    DEFAULT_SPIKE_PRICE_THRESHOLD,
    DEFAULT_TARGET_GRID_BUY_KWH,
    DEFAULT_ZERO_PRICE_DEADBAND,
    DOMAIN,
    PRICING_MODE_APP,
    SUBENTRY_TYPE_SITE,
)
from .coordinator import AmberDataCoordinator
from .data import CHANNEL_TYPE_MAP
from .site_context import SiteContext
from .trading import (
    TradingRecommendation,
    apply_zero_price_deadband,
    assumed_grid_charge_energy_today,
    build_chart_forecast,
    build_grid_buy_plan,
    current_plan_rate,
    find_best_charge_window,
    find_best_export_window,
    find_next_threshold_interval,
    is_effectively_zero,
    is_export_profitable,
    is_grid_charge_profitable,
    is_spike,
    recommend_action,
    recommend_trading,
    summarise_window,
    target_battery_power_kw,
)
from .types import ChannelData
from .utils import AMBER_PRICE_DECIMAL_PLACES, get_http_status_label, to_local_iso_minute

if TYPE_CHECKING:
    from . import AmberConfigEntry

# Decimal places for displayed and recorded prices (state and statistics). The
# detailed forecast is exempt and keeps the full converted precision instead.
PRICE_DECIMAL_PLACES = 4
MAX_SENSOR_STATE_LENGTH = 255

CHANNEL_PRICE_TRANSLATION_KEY = {
    CHANNEL_GENERAL: "general_price",
    CHANNEL_FEED_IN: "feed_in_price",
    CHANNEL_CONTROLLED_LOAD: "controlled_load_price",
}


# ---------------------------------------------------------------------------
# Entity description for description-driven sensors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class AmberSensorDescription(SensorEntityDescription):
    """Describes an Amber Express Trader sensor entity."""

    value_fn: Callable[[AmberDataCoordinator], Any]
    attributes_fn: Callable[[AmberDataCoordinator], dict[str, Any]] | None = None


def _site_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return site info as attributes."""
    site = coordinator.get_site_info()
    return {
        "id": site.id,
        "nmi": site.nmi,
        "network": site.network,
        "status": site.status.value,
        "interval_length": site.interval_length,
        "channels": [{"identifier": ch.identifier, "type": ch.type.value, "tariff": ch.tariff} for ch in site.channels],
    }


def _api_status_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return API status details and rate limit info as attributes."""
    rate_limit = coordinator.get_rate_limit_info()
    return {
        "status_code": coordinator.get_api_status(),
        "rate_limit_quota": rate_limit.get("limit"),
        "rate_limit_remaining": rate_limit.get("remaining"),
        "rate_limit_reset_at": rate_limit.get("reset_at").isoformat() if rate_limit.get("reset_at") else None,
        "rate_limit_window_seconds": rate_limit.get("window_seconds"),
        "rate_limit_policy": rate_limit.get("policy"),
    }


def _next_poll_attributes(coordinator: AmberDataCoordinator) -> dict[str, Any]:
    """Return poll schedule as attributes."""
    stats = coordinator.get_cdf_polling_stats()
    return {
        "poll_schedule": [round(t, 1) for t in stats.scheduled_polls],
        "poll_count": stats.confirmatory_poll_count + 1,
    }


def _confirmation_delay_value(coordinator: AmberDataCoordinator) -> float | None:
    """Return the last time-to-confirmed value in seconds."""
    stats = coordinator.get_cdf_polling_stats()
    if stats.last_observation is not None:
        return stats.last_observation["end"]
    return None


def _confirmation_lag_value(coordinator: AmberDataCoordinator) -> float | None:
    """Return the time gap between estimate and confirmed polls."""
    stats = coordinator.get_cdf_polling_stats()
    if stats.last_observation is not None:
        return stats.last_observation["end"] - stats.last_observation["start"]
    return None


SENSOR_DESCRIPTIONS: tuple[AmberSensorDescription, ...] = (
    AmberSensorDescription(
        key="renewables",
        translation_key="renewables",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda c: c.get_renewables(),
    ),
    AmberSensorDescription(
        key="site",
        translation_key="site",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.get_site_info().network,
        attributes_fn=_site_attributes,
    ),
    AmberSensorDescription(
        key="confirmation_delay",
        translation_key="confirmation_delay",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="s",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_confirmation_delay_value,
    ),
    AmberSensorDescription(
        key="confirmation_lag",
        translation_key="confirmation_lag",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="s",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_confirmation_lag_value,
    ),
    AmberSensorDescription(
        key="api_status",
        translation_key="api_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: get_http_status_label(c.get_api_status()),
        attributes_fn=_api_status_attributes,
    ),
    AmberSensorDescription(
        key="rate_limit_remaining",
        translation_key="rate_limit_remaining",
        native_unit_of_measurement="requests",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.get_rate_limit_info().get("remaining"),
    ),
    AmberSensorDescription(
        key="rate_limit_reset",
        translation_key="rate_limit_reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.get_rate_limit_info().get("reset_at"),
    ),
    AmberSensorDescription(
        key="next_poll",
        translation_key="next_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.get_next_poll_time(),
        attributes_fn=_next_poll_attributes,
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: AmberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amber Express Trader sensors for all site subentries."""
    if not entry.runtime_data:
        return

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SITE:
            continue

        site_data = entry.runtime_data.sites.get(subentry.subentry_id)
        if not site_data:
            continue

        entities: list[SensorEntity] = []
        coordinator = site_data.coordinator
        _add_site_sensors(entities, coordinator, entry, subentry)

        async_add_entities(entities, config_subentry_id=subentry.subentry_id)  # type: ignore[call-arg]


def _add_site_sensors(
    entities: list[SensorEntity],
    coordinator: AmberDataCoordinator,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> None:
    """Add sensors for a single site."""
    site = coordinator.get_site_info()

    available_channels: set[str] = set()
    for ch in site.channels:
        api_type = ch.type.value
        if api_type in CHANNEL_TYPE_MAP:
            available_channels.add(CHANNEL_TYPE_MAP[api_type])

    entities.extend(
        AmberPriceSensor(
            coordinator=coordinator,
            entry=entry,
            subentry=subentry,
            channel=channel,
        )
        for channel in available_channels
    )

    if available_channels:
        entities.extend(
            AmberSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
                description=description,
            )
            for description in SENSOR_DESCRIPTIONS
        )

        entities.append(
            AmberForecastHorizonSensor(
                coordinator=coordinator,
                entry=entry,
                subentry=subentry,
            )
        )
        entities.extend(
            [
                AmberBestExportWindowSensor(coordinator=coordinator, entry=entry, subentry=subentry),
                AmberBestChargeWindowSensor(coordinator=coordinator, entry=entry, subentry=subentry),
                AmberNextSpikeSensor(coordinator=coordinator, entry=entry, subentry=subentry),
                AmberNextNegativePriceSensor(coordinator=coordinator, entry=entry, subentry=subentry),
                AmberTradingActionSensor(coordinator=coordinator, entry=entry, subentry=subentry),
                AmberBatteryPowerTargetSensor(coordinator=coordinator, entry=entry, subentry=subentry),
                AmberTradingExplanationSensor(coordinator=coordinator, entry=entry, subentry=subentry),
            ]
        )


# ---------------------------------------------------------------------------
# Base sensor
# ---------------------------------------------------------------------------


class AmberBaseSensor(CoordinatorEntity[AmberDataCoordinator], SensorEntity):
    """Base class for Amber Express Trader sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._subentry = subentry
        self._site_id = subentry.data[CONF_SITE_ID]
        self._site_name = subentry.data.get(CONF_SITE_NAME, subentry.title)

    def _get_subentry_option(self, key: str, default: Any) -> Any:
        """Get an option from subentry data (reads fresh from config entry)."""
        subentry = self._entry.subentries.get(self._subentry.subentry_id)
        if subentry is None:
            return default
        return subentry.data.get(key, default)

    def _get_site_context(self) -> SiteContext | None:
        """Get live site context when the coordinator supports it."""
        get_site_context = getattr(self.coordinator, "get_site_context", None)
        if not callable(get_site_context):
            return None
        context = get_site_context()
        return context if isinstance(context, SiteContext) else None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            name=f"Amber Express Trader - {self._site_name}",
            manufacturer="Amber Electric",
            configuration_url="https://app.amber.com.au",
        )


# ---------------------------------------------------------------------------
# Description-driven sensor (handles all simple sensors)
# ---------------------------------------------------------------------------


class AmberSensor(AmberBaseSensor):
    """Generic sensor driven by an AmberSensorDescription."""

    entity_description: AmberSensorDescription

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: AmberSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self.entity_description = description
        self._attr_unique_id = f"{self._site_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator)
        return None


# ---------------------------------------------------------------------------
# Price sensors (shared logic via base class)
# ---------------------------------------------------------------------------


class AmberPriceSensor(AmberBaseSensor):
    """Sensor for current electricity price."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset({ATTR_DETAILED_FORECAST})

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        channel: str,
    ) -> None:
        """Initialize the price sensor."""
        super().__init__(coordinator, entry, subentry)
        self._channel = channel
        self._attr_unique_id = f"{self._site_id}_{channel}_price"
        self._attr_translation_key = CHANNEL_PRICE_TRANSLATION_KEY.get(channel, "general_price")

    def _get_price_key(self) -> str:
        """Return the price key based on configured pricing mode."""
        pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
        if pricing_mode == PRICING_MODE_APP:
            return ATTR_ADVANCED_PRICE
        return ATTR_PER_KWH

    def _get_price(self, data: ChannelData, price_key: str) -> float | None:
        """Extract price from data, with fallback and feed-in negation."""
        price = data.get(price_key)

        if price_key == ATTR_ADVANCED_PRICE and isinstance(price, dict):
            price = price.get("predicted")

        if price is None and price_key == ATTR_ADVANCED_PRICE:
            price = data.get(ATTR_PER_KWH)

        if price is None:
            return None
        if not isinstance(price, int | float):
            return None

        if self._channel == CHANNEL_FEED_IN:
            return price * -1
        return price

    def _get_effective_price(self, price: float | None) -> float | None:
        """Apply the configured zero-price deadband to a price."""
        deadband = self._get_subentry_option(CONF_ZERO_PRICE_DEADBAND, DEFAULT_ZERO_PRICE_DEADBAND)
        return apply_zero_price_deadband(price, deadband)

    @property
    def native_value(self) -> float | None:
        """Return the current price."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return None
        price = self._get_price(channel_data, self._get_price_key())
        if price is None:
            return None
        if self._channel == CHANNEL_GENERAL and channel_data.get(ATTR_DEMAND_WINDOW):
            demand_window_price = self._get_subentry_option(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE)
            return round(price + demand_window_price, AMBER_PRICE_DECIMAL_PLACES)
        return price

    def _negate_prices(self, data: ChannelData) -> dict[str, Any]:
        """Negate price fields for the feed-in channel."""
        result: dict[str, Any] = dict(data)
        for key in (ATTR_PER_KWH, ATTR_ADVANCED_PRICE):
            if key not in result:
                continue
            value = result[key]
            if isinstance(value, int | float):
                result[key] = value * -1
            elif isinstance(value, dict):
                result[key] = {k: v * -1 for k, v in value.items()}
        return result

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        channel_data = self.coordinator.get_channel_data(self._channel)
        if not channel_data:
            return {}

        attrs: dict[str, Any] = {
            ATTR_START_TIME: to_local_iso_minute(channel_data.get(ATTR_START_TIME)),
            ATTR_END_TIME: to_local_iso_minute(channel_data.get(ATTR_END_TIME)),
            ATTR_ESTIMATE: channel_data.get(ATTR_ESTIMATE),
            ATTR_DESCRIPTOR: channel_data.get(ATTR_DESCRIPTOR),
            "data_source": self.coordinator.data_source,
        }

        forecasts = self.coordinator.get_forecasts(self._channel)
        forecast_list: list[dict[str, Any]] = []
        demand_window_price = self._get_subentry_option(CONF_DEMAND_WINDOW_PRICE, DEFAULT_DEMAND_WINDOW_PRICE)
        for f in forecasts:
            time_value = to_local_iso_minute(f.get(ATTR_START_TIME))
            value = self._get_price(f, self._get_price_key())
            if value is not None:
                if self._channel == CHANNEL_GENERAL and f.get(ATTR_DEMAND_WINDOW):
                    value += demand_window_price
                value = round(value, PRICE_DECIMAL_PLACES)
            forecast_list.append({"time": time_value, "value": value})
        attrs["interpolation_mode"] = "previous"
        attrs[ATTR_FORECAST] = forecast_list

        if self._channel == CHANNEL_FEED_IN:
            attrs[ATTR_DETAILED_FORECAST] = [self._negate_prices(f) for f in forecasts]
        else:
            attrs[ATTR_DETAILED_FORECAST] = list(forecasts)

        raw_price = self.native_value
        zero_deadband = self._get_subentry_option(CONF_ZERO_PRICE_DEADBAND, DEFAULT_ZERO_PRICE_DEADBAND)
        export_floor = self._get_subentry_option(CONF_EXPORT_PRICE_FLOOR, DEFAULT_EXPORT_PRICE_FLOOR)
        charge_ceiling = self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING)
        spike_threshold = self._get_subentry_option(CONF_SPIKE_PRICE_THRESHOLD, DEFAULT_SPIKE_PRICE_THRESHOLD)
        effective_price = self._get_effective_price(raw_price)
        export_price = effective_price if self._channel == CHANNEL_FEED_IN else None

        attrs.update(
            {
                "raw_price": raw_price,
                "effective_price": effective_price,
                "is_effectively_zero": is_effectively_zero(raw_price, zero_deadband),
                "is_export_profitable": is_export_profitable(export_price, export_floor),
                "is_grid_charge_profitable": is_grid_charge_profitable(effective_price, charge_ceiling),
                "is_spike": is_spike(effective_price, spike_threshold),
                "chartForecast": build_chart_forecast(
                    forecasts,
                    self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
                    channel=self._channel,
                    deadband=zero_deadband,
                ),
            }
        )

        if self._channel == CHANNEL_GENERAL:
            feed_in_data = self.coordinator.get_channel_data(CHANNEL_FEED_IN) or {}
            feed_in_price = self._get_price(feed_in_data, self._get_price_key())
            pricing_mode = self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)
            attrs["trading_action"] = recommend_action(
                import_price=raw_price,
                feed_in_price=feed_in_price,
                zero_deadband=zero_deadband,
                export_floor=export_floor,
                charge_ceiling=charge_ceiling,
                spike_threshold=spike_threshold,
                site_context=self._get_site_context(),
                feed_in_forecast=self.coordinator.get_forecasts(CHANNEL_FEED_IN),
                pricing_mode=pricing_mode,
            )

        return {k: v for k, v in attrs.items() if v is not None}


class AmberTradingBaseSensor(AmberBaseSensor):
    """Base class for trading helper sensors."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def _pricing_mode(self) -> str:
        return self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE)

    def _export_floor(self) -> float:
        return self._get_subentry_option(CONF_EXPORT_PRICE_FLOOR, DEFAULT_EXPORT_PRICE_FLOOR)

    def _charge_ceiling(self) -> float:
        return self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING)

    def _spike_threshold(self) -> float:
        return self._get_subentry_option(CONF_SPIKE_PRICE_THRESHOLD, DEFAULT_SPIKE_PRICE_THRESHOLD)

    def _window(self) -> dict[str, Any] | None:
        return None

    @property
    def native_value(self) -> StateType:
        """Return the window price value."""
        value, _attrs = summarise_window(self._window())
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return window attributes."""
        _value, attrs = summarise_window(self._window())
        return attrs


class AmberBestExportWindowSensor(AmberTradingBaseSensor):
    """Sensor for the best export window."""

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_best_export_window"
        self._attr_translation_key = "best_export_window"

    def _window(self) -> dict[str, Any] | None:
        return find_best_export_window(
            self.coordinator.get_forecasts(CHANNEL_FEED_IN),
            self._pricing_mode(),
            floor=self._export_floor(),
        )


class AmberBestChargeWindowSensor(AmberTradingBaseSensor):
    """Sensor for the best grid charge window."""

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_best_charge_window"
        self._attr_translation_key = "best_charge_window"

    def _window(self) -> dict[str, Any] | None:
        return find_best_charge_window(
            self.coordinator.get_forecasts(CHANNEL_GENERAL),
            self._pricing_mode(),
            ceiling=self._charge_ceiling(),
        )


class AmberNextSpikeSensor(AmberTradingBaseSensor):
    """Sensor for the next forecast spike."""

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_next_spike"
        self._attr_translation_key = "next_spike"

    def _window(self) -> dict[str, Any] | None:
        return find_next_threshold_interval(
            self.coordinator.get_forecasts(CHANNEL_GENERAL),
            self._pricing_mode(),
            threshold=self._spike_threshold(),
            comparison="above",
            reason="import_price_above_spike_threshold",
        )


class AmberNextNegativePriceSensor(AmberTradingBaseSensor):
    """Sensor for the next negative import price."""

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_next_negative_price"
        self._attr_translation_key = "next_negative_price"

    def _window(self) -> dict[str, Any] | None:
        return find_next_threshold_interval(
            self.coordinator.get_forecasts(CHANNEL_GENERAL),
            self._pricing_mode(),
            threshold=0.0,
            comparison="below",
            reason="negative_import_price",
        )


class AmberTradingActionSensor(AmberBaseSensor):
    """Sensor for the recommended trading action."""

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_trading_action"
        self._attr_translation_key = "trading_action"

    @property
    def native_value(self) -> StateType:
        """Return the recommended trading action."""
        return self._recommendation().action

    def _recommendation(self) -> TradingRecommendation:
        """Return the current trading recommendation."""
        general_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_GENERAL)
        feed_in_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_FEED_IN)
        return recommend_trading(
            import_price=general_sensor.native_value,
            feed_in_price=feed_in_sensor.native_value,
            zero_deadband=self._get_subentry_option(CONF_ZERO_PRICE_DEADBAND, DEFAULT_ZERO_PRICE_DEADBAND),
            export_floor=self._get_subentry_option(CONF_EXPORT_PRICE_FLOOR, DEFAULT_EXPORT_PRICE_FLOOR),
            charge_ceiling=self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING),
            spike_threshold=self._get_subentry_option(CONF_SPIKE_PRICE_THRESHOLD, DEFAULT_SPIKE_PRICE_THRESHOLD),
            site_context=self._get_site_context(),
            feed_in_forecast=self.coordinator.get_forecasts(CHANNEL_FEED_IN),
            pricing_mode=self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return action thresholds as attributes."""
        recommendation = self._recommendation()
        context = self._get_site_context()
        return {
            "zero_price_deadband": self._get_subentry_option(CONF_ZERO_PRICE_DEADBAND, DEFAULT_ZERO_PRICE_DEADBAND),
            "export_price_floor": self._get_subentry_option(CONF_EXPORT_PRICE_FLOOR, DEFAULT_EXPORT_PRICE_FLOOR),
            "charge_price_ceiling": self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING),
            "spike_price_threshold": self._get_subentry_option(
                CONF_SPIKE_PRICE_THRESHOLD,
                DEFAULT_SPIKE_PRICE_THRESHOLD,
            ),
            "reason": recommendation.reason,
            "confidence": recommendation.confidence,
            "usable_energy_now_kwh": recommendation.usable_energy_now_kwh,
            "usable_energy_above_reserve_kwh": recommendation.usable_energy_above_reserve_kwh,
            "constrained_by": list(recommendation.constrained_by),
            "site_context_status": context.status if context else "not_configured",
            "missing_context_inputs": list(context.missing_inputs) if context else [],
            "pv_energy_today_kwh": context.pv_energy_today_kwh if context else None,
            "pv_forecast_remaining_today_kwh": context.pv_forecast_remaining_today_kwh if context else None,
            "battery_charge_energy_today_kwh": context.battery_charge_energy_today_kwh if context else None,
            "battery_discharge_energy_today_kwh": context.battery_discharge_energy_today_kwh if context else None,
            "solar_surplus_kw": context.solar_surplus_kw if context else None,
        }


class AmberBatteryPowerTargetSensor(AmberBaseSensor):
    """Sensor for target battery charge/discharge power."""

    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_battery_power_target"
        self._attr_translation_key = "battery_power_target"

    def _recommendation_and_plan(self) -> tuple[Any, dict[str, Any] | None]:
        general_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_GENERAL)
        feed_in_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_FEED_IN)
        context = self._get_site_context()
        recommendation = recommend_trading(
            import_price=general_sensor.native_value,
            feed_in_price=feed_in_sensor.native_value,
            zero_deadband=self._get_subentry_option(CONF_ZERO_PRICE_DEADBAND, DEFAULT_ZERO_PRICE_DEADBAND),
            export_floor=self._get_subentry_option(CONF_EXPORT_PRICE_FLOOR, DEFAULT_EXPORT_PRICE_FLOOR),
            charge_ceiling=self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING),
            spike_threshold=self._get_subentry_option(CONF_SPIKE_PRICE_THRESHOLD, DEFAULT_SPIKE_PRICE_THRESHOLD),
            site_context=context,
            feed_in_forecast=self.coordinator.get_forecasts(CHANNEL_FEED_IN),
            pricing_mode=self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
        )
        plan = build_grid_buy_plan(
            self.coordinator.get_forecasts(CHANNEL_GENERAL),
            self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
            charge_ceiling=self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING),
            target_grid_buy_kwh=self._get_subentry_option(CONF_TARGET_GRID_BUY_KWH, DEFAULT_TARGET_GRID_BUY_KWH),
            max_charge_kw=context.inverter_max_charge_kw if context else None,
        )
        return recommendation, plan

    @property
    def native_value(self) -> StateType:
        """Return target battery power in kW. Positive charges; negative discharges."""
        recommendation, plan = self._recommendation_and_plan()
        context = self._get_site_context()
        current_data = self.coordinator.get_channel_data(CHANNEL_GENERAL) or {}
        rate, _attrs = target_battery_power_kw(
            recommendation,
            site_context=context,
            grid_buy_plan_rate_kw=current_plan_rate(plan, current_data.get(ATTR_START_TIME)),
        )
        return rate

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return target calculation details."""
        recommendation, plan = self._recommendation_and_plan()
        context = self._get_site_context()
        current_data = self.coordinator.get_channel_data(CHANNEL_GENERAL) or {}
        rate, attrs = target_battery_power_kw(
            recommendation,
            site_context=context,
            grid_buy_plan_rate_kw=current_plan_rate(plan, current_data.get(ATTR_START_TIME)),
        )
        assumed_grid_charge_today = assumed_grid_charge_energy_today(plan)
        attrs.update(
            {
                "target_power_kw": rate,
                "target_grid_buy_kwh": self._get_subentry_option(
                    CONF_TARGET_GRID_BUY_KWH,
                    DEFAULT_TARGET_GRID_BUY_KWH,
                ),
                "grid_buy_plan": plan,
                "site_context_status": context.status if context else "not_configured",
                "missing_context_inputs": list(context.missing_inputs) if context else [],
                "pv_energy_today_kwh": context.pv_energy_today_kwh if context else None,
                "pv_forecast_remaining_today_kwh": context.pv_forecast_remaining_today_kwh if context else None,
                "assumed_grid_charge_energy_today_kwh": assumed_grid_charge_today,
                "battery_charge_energy_today_kwh": context.battery_charge_energy_today_kwh if context else None,
                "battery_discharge_energy_today_kwh": context.battery_discharge_energy_today_kwh if context else None,
                "solar_surplus_kw": context.solar_surplus_kw if context else None,
            }
        )
        return attrs


class AmberTradingExplanationSensor(AmberBaseSensor):
    """Sensor explaining the trading decision in plain English."""

    def __init__(self, coordinator: AmberDataCoordinator, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_trading_explanation"
        self._attr_translation_key = "trading_explanation"

    def _recommendation_and_plan(self) -> tuple[TradingRecommendation, dict[str, Any] | None]:
        general_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_GENERAL)
        feed_in_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_FEED_IN)
        context = self._get_site_context()
        recommendation = recommend_trading(
            import_price=general_sensor.native_value,
            feed_in_price=feed_in_sensor.native_value,
            zero_deadband=self._get_subentry_option(CONF_ZERO_PRICE_DEADBAND, DEFAULT_ZERO_PRICE_DEADBAND),
            export_floor=self._get_subentry_option(CONF_EXPORT_PRICE_FLOOR, DEFAULT_EXPORT_PRICE_FLOOR),
            charge_ceiling=self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING),
            spike_threshold=self._get_subentry_option(CONF_SPIKE_PRICE_THRESHOLD, DEFAULT_SPIKE_PRICE_THRESHOLD),
            site_context=context,
            feed_in_forecast=self.coordinator.get_forecasts(CHANNEL_FEED_IN),
            pricing_mode=self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
        )
        plan = build_grid_buy_plan(
            self.coordinator.get_forecasts(CHANNEL_GENERAL),
            self._get_subentry_option(CONF_PRICING_MODE, DEFAULT_PRICING_MODE),
            charge_ceiling=self._get_subentry_option(CONF_CHARGE_PRICE_CEILING, DEFAULT_CHARGE_PRICE_CEILING),
            target_grid_buy_kwh=self._get_subentry_option(CONF_TARGET_GRID_BUY_KWH, DEFAULT_TARGET_GRID_BUY_KWH),
            max_charge_kw=context.inverter_max_charge_kw if context else None,
        )
        return recommendation, plan

    @property
    def native_value(self) -> StateType:
        """Return the plain-English explanation."""
        recommendation, plan = self._recommendation_and_plan()
        context = self._get_site_context()
        general_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_GENERAL)
        feed_in_sensor = AmberPriceSensor(self.coordinator, self._entry, self._subentry, CHANNEL_FEED_IN)
        import_price = general_sensor.native_value
        feed_in_price = feed_in_sensor.native_value
        target_grid_buy = self._get_subentry_option(CONF_TARGET_GRID_BUY_KWH, DEFAULT_TARGET_GRID_BUY_KWH)
        plan_count = plan.get("interval_count") if plan else 0
        plan_average = plan.get("average_price") if plan else None
        solar_surplus = context.solar_surplus_kw if context else None

        action = str(recommendation.action).replace("_", " ")
        reason = recommendation.reason.replace("_", " ")
        parts = [f"Action is {action} because {reason}."]
        if isinstance(import_price, int | float):
            parts.append(f"Import is ${import_price:.3f}/kWh.")
        if isinstance(feed_in_price, int | float):
            parts.append(f"Feed-in is ${abs(feed_in_price):.3f}/kWh.")
        if target_grid_buy > 0:
            if plan and isinstance(plan_average, int | float):
                parts.append(
                    f"It planned {plan.get('planned_energy_kwh', 0):.2f} kWh of grid charging across "
                    f"{plan_count} cheapest intervals at about ${plan_average:.3f}/kWh."
                )
            else:
                parts.append("It did not find a valid grid-charge window under the configured buy price.")
        if solar_surplus is not None:
            parts.append(f"Current solar surplus is {solar_surplus:.2f} kW.")
        if context and context.missing_inputs:
            parts.append(f"Missing inputs: {', '.join(context.missing_inputs)}.")
        explanation = " ".join(parts)
        if len(explanation) > MAX_SENSOR_STATE_LENGTH:
            return f"{explanation[: MAX_SENSOR_STATE_LENGTH - 3]}..."
        return explanation

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return explanation inputs and outputs."""
        recommendation, plan = self._recommendation_and_plan()
        context = self._get_site_context()
        return {
            "action": recommendation.action,
            "reason": recommendation.reason,
            "confidence": recommendation.confidence,
            "explanation": self.native_value,
            "grid_buy_plan": plan,
            "assumed_grid_charge_energy_today_kwh": assumed_grid_charge_energy_today(plan),
            "site_context_status": context.status if context else "not_configured",
            "missing_context_inputs": list(context.missing_inputs) if context else [],
        }


# ---------------------------------------------------------------------------
# Forecast horizon sensor
# ---------------------------------------------------------------------------


class AmberForecastHorizonSensor(AmberBaseSensor):
    """Sensor for how many hours of forecast data are available."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "h"
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _FORECAST_CHANNELS: tuple[str, ...] = (
        CHANNEL_GENERAL,
        CHANNEL_FEED_IN,
        CHANNEL_CONTROLLED_LOAD,
    )

    def __init__(
        self,
        coordinator: AmberDataCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the forecast horizon sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{self._site_id}_forecast_horizon"
        self._attr_translation_key = "forecast_horizon"

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        """Parse an ISO timestamp string into a datetime."""
        if not isinstance(value, str):
            return None
        return dt_util.parse_datetime(value)

    def _get_latest_forecast_end(self) -> datetime | None:
        """Return the latest forecast end_time across all channels."""
        latest_end: datetime | None = None
        for channel in self._FORECAST_CHANNELS:
            for forecast in self.coordinator.get_forecasts(channel):
                end_time = self._parse_datetime(forecast.get(ATTR_END_TIME))
                if end_time is None:
                    continue
                if latest_end is None or end_time > latest_end:
                    latest_end = end_time
        return latest_end

    @property
    def native_value(self) -> float | None:
        """Return the forecast horizon in hours."""
        baseline = self.coordinator.get_forecasts_timestamp()
        if baseline is None:
            return None

        latest_end = self._get_latest_forecast_end()
        if latest_end is None:
            return None

        return (latest_end - baseline).total_seconds() / 3600

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the raw forecast end timestamp as an attribute."""
        latest_end = self._get_latest_forecast_end()
        if latest_end is None:
            return {}
        return {"forecast_end": latest_end.isoformat()}

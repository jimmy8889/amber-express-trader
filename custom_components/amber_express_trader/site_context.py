"""Site context helpers for Amber Express Trader."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ALLOW_BATTERY_EXPORT,
    CONF_ALLOW_GRID_CHARGE,
    CONF_BATTERY_CHARGE_ENERGY_TODAY_ENTITY,
    CONF_BATTERY_DISCHARGE_ENERGY_TODAY_ENTITY,
    CONF_BATTERY_MIN_RESERVE_KWH,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_USABLE_KWH,
    CONF_GRID_POWER_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_INVERTER_MAX_CHARGE_KW,
    CONF_INVERTER_MAX_DISCHARGE_KW,
    CONF_NORMAL_EXPORT_LIMIT_KW,
    CONF_PV_ENERGY_TODAY_ENTITY,
    CONF_PV_FORECAST_REMAINING_TODAY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    DEFAULT_ALLOW_BATTERY_EXPORT,
    DEFAULT_ALLOW_GRID_CHARGE,
    SITE_CONTEXT_ENTITY_OPTIONS,
    SITE_CONTEXT_VALUE_OPTIONS,
)

_MISSING_STATES = {STATE_UNKNOWN, STATE_UNAVAILABLE, "none", ""}
_TRUE_STATES = {"on", "true", "yes", "1", "enabled"}
_FALSE_STATES = {"off", "false", "no", "0", "disabled"}


@dataclass(slots=True)
class SiteContext:
    """Live site context read from configured Home Assistant entities."""

    battery_soc_pct: float | None = None
    battery_power_kw: float | None = None
    grid_power_kw: float | None = None
    solar_power_kw: float | None = None
    house_load_kw: float | None = None
    pv_energy_today_kwh: float | None = None
    pv_forecast_remaining_today_kwh: float | None = None
    grid_charge_energy_today_kwh: float | None = None
    battery_charge_energy_today_kwh: float | None = None
    battery_discharge_energy_today_kwh: float | None = None
    battery_usable_kwh: float | None = None
    battery_min_reserve_kwh: float | None = None
    inverter_max_charge_kw: float | None = None
    inverter_max_discharge_kw: float | None = None
    normal_export_limit_kw: float | None = None
    allow_grid_charge: bool | None = None
    allow_battery_export: bool | None = None
    missing_inputs: tuple[str, ...] = ()
    configured_inputs: tuple[str, ...] = ()

    @property
    def configured_count(self) -> int:
        """Return the number of configured context inputs."""
        return len(self.configured_inputs)

    @property
    def status(self) -> str:
        """Return whether context is configured, partial, or absent."""
        if self.configured_count == 0:
            return "not_configured"
        if self.missing_inputs:
            return "partial"
        return "configured"

    @property
    def usable_energy_now_kwh(self) -> float | None:
        """Return current usable battery energy if capacity and SOC are known."""
        if self.battery_usable_kwh is None or self.battery_soc_pct is None:
            return None
        return self.battery_usable_kwh * self.battery_soc_pct / 100

    @property
    def usable_energy_above_reserve_kwh(self) -> float | None:
        """Return usable battery energy above reserve if all inputs are known."""
        usable_now = self.usable_energy_now_kwh
        if usable_now is None or self.battery_min_reserve_kwh is None:
            return None
        return max(0.0, usable_now - self.battery_min_reserve_kwh)

    @property
    def battery_room_kwh(self) -> float | None:
        """Return available room to charge if capacity and SOC are known."""
        usable_now = self.usable_energy_now_kwh
        if usable_now is None or self.battery_usable_kwh is None:
            return None
        return max(0.0, self.battery_usable_kwh - usable_now)

    @property
    def solar_surplus_kw(self) -> float | None:
        """Return current solar surplus after house load if both are known."""
        if self.solar_power_kw is None or self.house_load_kw is None:
            return None
        return max(0.0, self.solar_power_kw - self.house_load_kw)


def _configured_entity_id(options: dict[str, Any], key: str) -> str:
    value = options.get(key)
    return value.strip() if isinstance(value, str) else ""


def get_float_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """Read a numeric entity state, converting W/Wh units to kW/kWh."""
    if not entity_id:
        return None

    state = hass.states.get(entity_id)
    if state is None:
        return None

    raw_state = str(state.state).strip()
    if raw_state.lower() in _MISSING_STATES:
        return None

    try:
        value = float(raw_state)
    except (TypeError, ValueError):
        return None

    unit = str(state.attributes.get("unit_of_measurement", "")).strip()
    if unit in {"W", "Wh"}:
        return value / 1000
    return value


def get_bool_state(hass: HomeAssistant, entity_id: str | None) -> bool | None:
    """Read a boolean-like entity state."""
    if not entity_id:
        return None

    state = hass.states.get(entity_id)
    if state is None:
        return None

    raw_state = str(state.state).strip().lower()
    if raw_state in _MISSING_STATES:
        return None
    if raw_state in _TRUE_STATES:
        return True
    if raw_state in _FALSE_STATES:
        return False
    return None


def get_float_config(options: dict[str, Any], key: str) -> float | None:
    """Read an optional numeric config value."""
    value = options.get(key)
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    raw_value = str(value).strip()
    if raw_value.lower() in _MISSING_STATES:
        return None
    try:
        return float(raw_value)
    except ValueError:
        return None


def build_site_context(hass: HomeAssistant, options: dict[str, Any]) -> SiteContext:
    """Build live site context from configured entity IDs."""
    configured_inputs = tuple(
        key
        for key in (*SITE_CONTEXT_ENTITY_OPTIONS, *SITE_CONTEXT_VALUE_OPTIONS)
        if _configured_entity_id(options, key)
    )
    missing_inputs: list[str] = []

    float_fields = {
        CONF_BATTERY_SOC_ENTITY: "battery_soc_pct",
        CONF_BATTERY_POWER_ENTITY: "battery_power_kw",
        CONF_GRID_POWER_ENTITY: "grid_power_kw",
        CONF_SOLAR_POWER_ENTITY: "solar_power_kw",
        CONF_HOUSE_LOAD_ENTITY: "house_load_kw",
        CONF_PV_ENERGY_TODAY_ENTITY: "pv_energy_today_kwh",
        CONF_PV_FORECAST_REMAINING_TODAY_ENTITY: "pv_forecast_remaining_today_kwh",
        CONF_BATTERY_CHARGE_ENERGY_TODAY_ENTITY: "battery_charge_energy_today_kwh",
        CONF_BATTERY_DISCHARGE_ENERGY_TODAY_ENTITY: "battery_discharge_energy_today_kwh",
    }
    value_fields = {
        CONF_BATTERY_USABLE_KWH: "battery_usable_kwh",
        CONF_BATTERY_MIN_RESERVE_KWH: "battery_min_reserve_kwh",
        CONF_INVERTER_MAX_CHARGE_KW: "inverter_max_charge_kw",
        CONF_INVERTER_MAX_DISCHARGE_KW: "inverter_max_discharge_kw",
        CONF_NORMAL_EXPORT_LIMIT_KW: "normal_export_limit_kw",
    }

    values: dict[str, Any] = {}
    for key, field_name in float_fields.items():
        entity_id = _configured_entity_id(options, key)
        value = get_float_state(hass, entity_id)
        values[field_name] = value
        if entity_id and value is None:
            missing_inputs.append(key)

    for key, field_name in value_fields.items():
        value = get_float_config(options, key)
        values[field_name] = value
        if _configured_entity_id(options, key) and value is None:
            missing_inputs.append(key)

    values["allow_grid_charge"] = bool(options.get(CONF_ALLOW_GRID_CHARGE, DEFAULT_ALLOW_GRID_CHARGE))
    values["allow_battery_export"] = bool(options.get(CONF_ALLOW_BATTERY_EXPORT, DEFAULT_ALLOW_BATTERY_EXPORT))

    return SiteContext(
        **values,
        missing_inputs=tuple(missing_inputs),
        configured_inputs=configured_inputs,
    )

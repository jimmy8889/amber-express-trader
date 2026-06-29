"""Tests for site context helpers."""

from unittest.mock import MagicMock

from custom_components.amber_express_trader.const import (
    CONF_ALLOW_GRID_CHARGE,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_USABLE_KWH,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_INVERTER_MAX_CHARGE_KW,
    CONF_PV_ENERGY_TODAY_ENTITY,
    CONF_PV_FORECAST_REMAINING_TODAY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
)
from custom_components.amber_express_trader.site_context import (
    build_site_context,
    get_bool_state,
    get_float_config,
    get_float_state,
)


def _state(value: str, unit: str | None = None) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.attributes = {}
    if unit is not None:
        state.attributes["unit_of_measurement"] = unit
    return state


def test_get_float_state_converts_watts_to_kw() -> None:
    """W states are converted to kW."""
    hass = MagicMock()
    hass.states.get.return_value = _state("4200", "W")

    assert get_float_state(hass, "sensor.power") == 4.2


def test_get_float_state_returns_none_for_unavailable() -> None:
    """Unavailable states are ignored."""
    hass = MagicMock()
    hass.states.get.return_value = _state("unavailable")

    assert get_float_state(hass, "sensor.power") is None


def test_get_bool_state() -> None:
    """Boolean-like states are parsed safely."""
    hass = MagicMock()
    hass.states.get.return_value = _state("enabled")

    assert get_bool_state(hass, "input_boolean.allow") is True


def test_get_float_config() -> None:
    """Optional numeric config values are parsed safely."""
    assert get_float_config({CONF_BATTERY_USABLE_KWH: "13.5"}, CONF_BATTERY_USABLE_KWH) == 13.5
    assert get_float_config({CONF_BATTERY_USABLE_KWH: ""}, CONF_BATTERY_USABLE_KWH) is None


def test_build_site_context_tracks_configured_and_missing_inputs() -> None:
    """Configured and missing inputs are tracked by config key."""
    hass = MagicMock()

    def get_state(entity_id: str) -> MagicMock | None:
        states = {
            "sensor.soc": _state("50", "%"),
            "sensor.pv_today": _state("7400", "Wh"),
            "sensor.pv_remaining": _state("2.5", "kWh"),
            "sensor.solar": _state("4200", "W"),
            "sensor.house": _state("2100", "W"),
        }
        return states.get(entity_id)

    hass.states.get.side_effect = get_state

    context = build_site_context(
        hass,
        {
            CONF_BATTERY_SOC_ENTITY: "sensor.soc",
            CONF_BATTERY_USABLE_KWH: "10",
            CONF_PV_ENERGY_TODAY_ENTITY: "sensor.pv_today",
            CONF_PV_FORECAST_REMAINING_TODAY_ENTITY: "sensor.pv_remaining",
            CONF_SOLAR_POWER_ENTITY: "sensor.solar",
            CONF_HOUSE_LOAD_ENTITY: "sensor.house",
            CONF_INVERTER_MAX_CHARGE_KW: "not-a-number",
            CONF_ALLOW_GRID_CHARGE: True,
        },
    )

    assert context.battery_soc_pct == 50
    assert context.battery_usable_kwh == 10
    assert context.pv_energy_today_kwh == 7.4
    assert context.pv_forecast_remaining_today_kwh == 2.5
    assert context.solar_surplus_kw == 2.1
    assert context.allow_grid_charge is True
    assert context.configured_count == 7
    assert context.status == "partial"
    assert context.missing_inputs == (CONF_INVERTER_MAX_CHARGE_KW,)

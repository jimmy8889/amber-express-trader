"""Tests for trading helpers."""

from homeassistant.util import dt as dt_util

from custom_components.amber_express_trader.const import (
    ATTR_ADVANCED_PRICE,
    ATTR_DURATION,
    ATTR_END_TIME,
    ATTR_PER_KWH,
    ATTR_START_TIME,
    CHANNEL_FEED_IN,
    GRID_CHARGE_EFFICIENCY,
    PRICING_MODE_APP,
    PV_DISCHARGE_EFFICIENCY,
)
from custom_components.amber_express_trader.site_context import SiteContext
from custom_components.amber_express_trader.trading import (
    apply_zero_price_deadband,
    assumed_grid_charge_energy_today,
    build_chart_forecast,
    build_grid_buy_plan,
    current_plan_rate,
    find_best_charge_window,
    find_best_export_window,
    is_effectively_zero,
    recommend_action,
    recommend_trading,
    target_battery_power_kw,
)


def test_effective_price_deadband() -> None:
    """Prices within the deadband are treated as zero."""
    assert apply_zero_price_deadband(0.0005, 0.001) == 0.0
    assert apply_zero_price_deadband(-0.0005, 0.001) == 0.0
    assert apply_zero_price_deadband(0.002, 0.001) == 0.002
    assert is_effectively_zero(-0.001, 0.001) is True


def test_chart_forecast_uses_advanced_predicted() -> None:
    """Chart forecast uses the configured pricing mode."""
    forecast = [
        {
            ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            ATTR_PER_KWH: 0.20,
            ATTR_ADVANCED_PRICE: {"predicted": 0.03},
        }
    ]

    assert build_chart_forecast(forecast, PRICING_MODE_APP, deadband=0.001) == [
        {"x": "2024-01-01T10:00:00+00:00", "y": 0.03}
    ]


def test_best_export_window_uses_feed_in_sign_magnitude() -> None:
    """Best export window preserves feed-in sign input but ranks by export value."""
    forecast = [
        {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.10},
        {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_END_TIME: "2024-01-01T10:10:00+00:00", ATTR_PER_KWH: 0.15},
    ]

    window = find_best_export_window(forecast, "per_kwh", floor=0.11, channel=CHANNEL_FEED_IN)

    assert window is not None
    assert window["start_time"] == "2024-01-01T10:05:00+00:00"
    assert window["average_price"] == 0.15
    assert window["signed_price"] == -0.15
    assert window["reason"] == "export_price_above_floor"


def test_best_charge_window() -> None:
    """Best charge window is the lowest import price."""
    forecast = [
        {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_END_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.04},
        {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_END_TIME: "2024-01-01T10:10:00+00:00", ATTR_PER_KWH: -0.01},
    ]

    window = find_best_charge_window(forecast, "per_kwh", ceiling=0.03)

    assert window is not None
    assert window["start_time"] == "2024-01-01T10:05:00+00:00"
    assert window["average_price"] == -0.01
    assert window["reason"] == "import_price_below_ceiling"


def test_recommend_action() -> None:
    """Trading action follows current thresholds."""
    assert (
        recommend_action(
            import_price=0.02,
            feed_in_price=-0.05,
            zero_deadband=0.001,
            export_floor=0.11,
            charge_ceiling=0.03,
            spike_threshold=0.50,
        )
        == "charge_from_grid"
    )


def test_recommend_trading_respects_grid_charge_constraint() -> None:
    """Grid charging is constrained by site context."""
    recommendation = recommend_trading(
        import_price=0.01,
        feed_in_price=-0.02,
        zero_deadband=0.001,
        export_floor=0.11,
        charge_ceiling=0.03,
        spike_threshold=0.50,
        site_context=SiteContext(allow_grid_charge=False),
    )

    assert recommendation.action == "hold"
    assert "allow_grid_charge" in recommendation.constrained_by


def test_grid_buy_plan_selects_cheapest_intervals_to_target() -> None:
    """Grid buy plan chooses cheapest forecast slots up to max charge rate."""
    forecast = [
        {
            ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            ATTR_END_TIME: "2024-01-01T10:30:00+00:00",
            ATTR_DURATION: 30,
            ATTR_PER_KWH: 0.03,
        },
        {
            ATTR_START_TIME: "2024-01-01T10:30:00+00:00",
            ATTR_END_TIME: "2024-01-01T11:00:00+00:00",
            ATTR_DURATION: 30,
            ATTR_PER_KWH: 0.01,
        },
        {
            ATTR_START_TIME: "2024-01-01T11:00:00+00:00",
            ATTR_END_TIME: "2024-01-01T11:30:00+00:00",
            ATTR_DURATION: 30,
            ATTR_PER_KWH: 0.02,
        },
    ]

    plan = build_grid_buy_plan(
        forecast,
        "per_kwh",
        charge_ceiling=0.03,
        target_grid_buy_kwh=3.0,
        max_charge_kw=2.0,
    )

    assert plan is not None
    assert plan["planned_energy_kwh"] == 3.0
    assert plan["expected_battery_energy_kwh"] == 3.0 * GRID_CHARGE_EFFICIENCY
    assert plan["interval_count"] == 3
    assert plan["intervals"][0]["start_time"] == "2024-01-01T10:00:00+00:00"
    assert current_plan_rate(plan, "2024-01-01T10:30:00+00:00") == 2.0


def test_grid_buy_plan_subtracts_already_bought_today() -> None:
    """Daily grid buy target is reduced by energy already bought today."""
    forecast = [
        {
            ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
            ATTR_END_TIME: "2024-01-01T11:00:00+00:00",
            ATTR_DURATION: 60,
            ATTR_PER_KWH: 0.01,
        },
    ]

    plan = build_grid_buy_plan(
        forecast,
        "per_kwh",
        charge_ceiling=0.03,
        target_grid_buy_kwh=5.0,
        max_charge_kw=5.0,
        already_bought_kwh=2.0,
    )

    assert plan is not None
    assert plan["already_bought_kwh"] == 2.0
    assert plan["planned_energy_kwh"] == 3.0
    assert plan["expected_battery_energy_kwh"] == 3.0 * GRID_CHARGE_EFFICIENCY


def test_recommend_trading_holds_for_better_export_price_later() -> None:
    """Profitable export can hold when a better feed-in interval is forecast."""
    forecast = [
        {ATTR_START_TIME: "2024-01-01T10:00:00+00:00", ATTR_PER_KWH: 0.12},
        {ATTR_START_TIME: "2024-01-01T10:05:00+00:00", ATTR_PER_KWH: 0.40},
    ]

    recommendation = recommend_trading(
        import_price=0.20,
        feed_in_price=-0.12,
        zero_deadband=0.001,
        export_floor=0.11,
        charge_ceiling=0.03,
        spike_threshold=0.50,
        site_context=SiteContext(battery_soc_pct=80, battery_usable_kwh=10, battery_min_reserve_kwh=2),
        feed_in_forecast=forecast,
        pricing_mode="per_kwh",
    )

    assert recommendation.action == "hold"
    assert recommendation.reason == "better_export_price_forecast_later"


def test_target_battery_power_uses_grid_buy_plan_rate() -> None:
    """Charge target uses the cheapest-plan current interval rate."""
    recommendation = recommend_trading(
        import_price=0.01,
        feed_in_price=-0.02,
        zero_deadband=0.001,
        export_floor=0.11,
        charge_ceiling=0.03,
        spike_threshold=0.50,
        site_context=SiteContext(inverter_max_charge_kw=5.0),
    )

    rate, attrs = target_battery_power_kw(
        recommendation,
        site_context=SiteContext(inverter_max_charge_kw=5.0),
        grid_buy_plan_rate_kw=2.5,
    )

    assert rate == 2.5
    assert attrs["target_direction"] == "charge"
    assert attrs["grid_charge_efficiency"] == GRID_CHARGE_EFFICIENCY


def test_target_battery_power_charges_from_solar_surplus() -> None:
    """Solar charging target follows live surplus and inverter charge cap."""
    recommendation = recommend_trading(
        import_price=0.20,
        feed_in_price=0.0,
        zero_deadband=0.001,
        export_floor=0.11,
        charge_ceiling=0.03,
        spike_threshold=0.50,
        site_context=SiteContext(solar_power_kw=6.0, house_load_kw=2.5, inverter_max_charge_kw=3.0),
    )

    rate, attrs = target_battery_power_kw(
        recommendation,
        site_context=SiteContext(solar_power_kw=6.0, house_load_kw=2.5, inverter_max_charge_kw=3.0),
    )

    assert rate == 3.0
    assert attrs["source"] == "solar_surplus"
    assert attrs["pv_discharge_efficiency"] == PV_DISCHARGE_EFFICIENCY


def test_assumed_grid_charge_energy_today_uses_completed_plan_intervals() -> None:
    """Assumed grid charge is calculated from elapsed planned intervals."""
    plan = {
        "intervals": [
            {
                ATTR_START_TIME: "2024-01-01T10:00:00+00:00",
                ATTR_END_TIME: "2024-01-01T10:30:00+00:00",
                "energy_kwh": 1.0,
            },
            {
                ATTR_START_TIME: "2024-01-01T10:30:00+00:00",
                ATTR_END_TIME: "2024-01-01T11:00:00+00:00",
                "energy_kwh": 2.0,
            },
        ]
    }

    completed = assumed_grid_charge_energy_today(
        plan,
        now=dt_util.parse_datetime("2024-01-01T10:45:00+00:00"),
    )

    assert completed == 2.0

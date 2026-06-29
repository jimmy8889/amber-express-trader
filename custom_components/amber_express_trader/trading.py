"""Trading helper functions for Amber Express Trader."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean
from typing import Any, Literal

from homeassistant.util import dt as dt_util

from .const import (
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
from .site_context import SiteContext
from .types import ChannelData

TradingAction = Literal[
    "hold",
    "charge_from_grid",
    "charge_from_solar",
    "discharge_to_home",
    "export_to_grid",
    "avoid_import",
]


@dataclass(slots=True)
class TradingRecommendation:
    """A trading action with explainable context."""

    action: TradingAction
    reason: str
    confidence: str = "medium"
    usable_energy_now_kwh: float | None = None
    usable_energy_above_reserve_kwh: float | None = None
    constrained_by: tuple[str, ...] = ()


def extract_price(interval: ChannelData, pricing_mode: str, *, channel: str | None = None) -> float | None:
    """Extract the configured price from an interval."""
    price_key = ATTR_ADVANCED_PRICE if pricing_mode == PRICING_MODE_APP else ATTR_PER_KWH
    price = interval.get(price_key)

    if price_key == ATTR_ADVANCED_PRICE and isinstance(price, dict):
        price = price.get("predicted")

    if price is None and price_key == ATTR_ADVANCED_PRICE:
        price = interval.get(ATTR_PER_KWH)

    if not isinstance(price, int | float):
        return None

    if channel == CHANNEL_FEED_IN:
        return price * -1
    return price


def apply_zero_price_deadband(price: float | None, deadband: float) -> float | None:
    """Return zero for prices within the configured zero-price deadband."""
    if price is None:
        return None
    if abs(price) <= deadband:
        return 0.0
    return price


def is_effectively_zero(price: float | None, deadband: float) -> bool:
    """Return whether a price is effectively zero."""
    return price is not None and abs(price) <= deadband


def is_export_profitable(price: float | None, floor: float) -> bool:
    """Return whether exporting is profitable at this feed-in price."""
    return price is not None and abs(price) >= floor


def is_grid_charge_profitable(price: float | None, ceiling: float) -> bool:
    """Return whether grid charging is profitable at this import price."""
    return price is not None and price <= ceiling


def is_spike(price: float | None, threshold: float) -> bool:
    """Return whether the import price is above the configured spike threshold."""
    return price is not None and price >= threshold


def build_chart_forecast(
    forecast: Iterable[ChannelData],
    pricing_mode: str,
    *,
    channel: str | None = None,
    deadband: float = 0.0,
) -> list[dict[str, Any]]:
    """Build a chart-friendly forecast list."""
    result: list[dict[str, Any]] = []
    for interval in forecast:
        x_value = interval.get(ATTR_START_TIME)
        price = extract_price(interval, pricing_mode, channel=channel)
        result.append({"x": x_value, "y": apply_zero_price_deadband(price, deadband)})
    return result


def _window_from_interval(interval: ChannelData, price: float, reason: str) -> dict[str, Any]:
    return {
        "start_time": interval.get(ATTR_START_TIME),
        "end_time": interval.get(ATTR_END_TIME),
        "average_price": price,
        "max_price": price,
        "min_price": price,
        "interval_count": 1,
        "reason": reason,
    }


def find_best_export_window(
    forecast: Iterable[ChannelData],
    pricing_mode: str,
    *,
    floor: float,
    channel: str = CHANNEL_FEED_IN,
) -> dict[str, Any] | None:
    """Find the best export interval in the forecast horizon."""
    best: dict[str, Any] | None = None
    for interval in forecast:
        price = extract_price(interval, pricing_mode, channel=channel)
        if price is None:
            continue
        export_value = abs(price)
        candidate = _window_from_interval(interval, export_value, "highest_export_price")
        candidate["signed_price"] = price
        if best is None or export_value > best["average_price"]:
            best = candidate

    if best is None or best["average_price"] < floor:
        return best
    best["reason"] = "export_price_above_floor"
    return best


def find_best_charge_window(
    forecast: Iterable[ChannelData],
    pricing_mode: str,
    *,
    ceiling: float,
) -> dict[str, Any] | None:
    """Find the best grid-charge interval in the forecast horizon."""
    best: dict[str, Any] | None = None
    for interval in forecast:
        price = extract_price(interval, pricing_mode)
        if price is None:
            continue
        candidate = _window_from_interval(interval, price, "lowest_import_price")
        if best is None or price < best["average_price"]:
            best = candidate

    if best is None or best["average_price"] > ceiling:
        return best
    best["reason"] = "import_price_below_ceiling"
    return best


def find_next_threshold_interval(
    forecast: Iterable[ChannelData],
    pricing_mode: str,
    *,
    threshold: float,
    comparison: Literal["above", "below"],
    channel: str | None = None,
    reason: str,
) -> dict[str, Any] | None:
    """Find the next forecast interval matching a price threshold."""
    for interval in forecast:
        price = extract_price(interval, pricing_mode, channel=channel)
        if price is None:
            continue
        if (comparison == "above" and price >= threshold) or (comparison == "below" and price < threshold):
            return _window_from_interval(interval, price, reason)
    return None


def _best_future_export_price(forecast: Iterable[ChannelData], pricing_mode: str) -> float | None:
    prices = [
        abs(price)
        for interval in forecast
        if (price := extract_price(interval, pricing_mode, channel=CHANNEL_FEED_IN)) is not None
    ]
    return max(prices) if prices else None


def _interval_duration_hours(interval: ChannelData) -> float:
    duration = interval.get(ATTR_DURATION)
    if isinstance(duration, int | float) and duration > 0:
        return float(duration) / 60

    start = _parse_datetime(interval.get(ATTR_START_TIME))
    end = _parse_datetime(interval.get(ATTR_END_TIME))
    if start is None or end is None:
        return 5 / 60

    hours = (end - start).total_seconds() / 3600
    return hours if hours > 0 else 5 / 60


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return dt_util.parse_datetime(value)


def _energy_values(site_context: SiteContext | None) -> tuple[float | None, float | None, float | None]:
    if site_context is None:
        return None, None, None
    return (
        site_context.usable_energy_now_kwh,
        site_context.usable_energy_above_reserve_kwh,
        site_context.battery_room_kwh,
    )


def _battery_has_room(site_context: SiteContext | None) -> bool:
    if site_context is None or site_context.battery_room_kwh is None:
        return True
    return site_context.battery_room_kwh > 0


def _battery_has_energy_above_reserve(site_context: SiteContext | None) -> bool:
    if site_context is None or site_context.usable_energy_above_reserve_kwh is None:
        return True
    return site_context.usable_energy_above_reserve_kwh > 0


def recommend_action(
    *,
    import_price: float | None,
    feed_in_price: float | None,
    zero_deadband: float,
    export_floor: float,
    charge_ceiling: float,
    spike_threshold: float,
    site_context: SiteContext | None = None,
    feed_in_forecast: Iterable[ChannelData] | None = None,
    pricing_mode: str | None = None,
) -> TradingAction:
    """Recommend a trading action from current import and feed-in prices."""
    return recommend_trading(
        import_price=import_price,
        feed_in_price=feed_in_price,
        zero_deadband=zero_deadband,
        export_floor=export_floor,
        charge_ceiling=charge_ceiling,
        spike_threshold=spike_threshold,
        site_context=site_context,
        feed_in_forecast=feed_in_forecast,
        pricing_mode=pricing_mode,
    ).action


def recommend_trading(
    *,
    import_price: float | None,
    feed_in_price: float | None,
    zero_deadband: float,
    export_floor: float,
    charge_ceiling: float,
    spike_threshold: float,
    site_context: SiteContext | None = None,
    feed_in_forecast: Iterable[ChannelData] | None = None,
    pricing_mode: str | None = None,
) -> TradingRecommendation:
    """Recommend a trading action from current price and optional site context."""
    effective_import = apply_zero_price_deadband(import_price, zero_deadband)
    effective_feed_in = apply_zero_price_deadband(feed_in_price, zero_deadband)
    usable_now, usable_above_reserve, _battery_room = _energy_values(site_context)
    constrained_by: list[str] = []
    best_future_export = (
        _best_future_export_price(feed_in_forecast, pricing_mode)
        if feed_in_forecast is not None and pricing_mode is not None
        else None
    )

    grid_charge_allowed = site_context is None or site_context.allow_grid_charge is not False
    battery_export_allowed = site_context is None or site_context.allow_battery_export is not False
    if not grid_charge_allowed:
        constrained_by.append("allow_grid_charge")
    if not battery_export_allowed:
        constrained_by.append("allow_battery_export")

    if is_spike(effective_import, spike_threshold):
        if _battery_has_energy_above_reserve(site_context):
            return TradingRecommendation(
                "discharge_to_home",
                "import_price_above_spike_threshold_with_battery_reserve_available",
                confidence="high",
                usable_energy_now_kwh=usable_now,
                usable_energy_above_reserve_kwh=usable_above_reserve,
                constrained_by=tuple(constrained_by),
            )
        return TradingRecommendation(
            "avoid_import",
            "import_price_above_spike_threshold",
            confidence="high",
            usable_energy_now_kwh=usable_now,
            usable_energy_above_reserve_kwh=usable_above_reserve,
            constrained_by=tuple(constrained_by),
        )
    if is_export_profitable(effective_feed_in, export_floor) and battery_export_allowed:
        if _battery_has_energy_above_reserve(site_context):
            if (
                best_future_export is not None
                and effective_feed_in is not None
                and best_future_export > abs(effective_feed_in)
            ):
                return TradingRecommendation(
                    "hold",
                    "better_export_price_forecast_later",
                    confidence="high",
                    usable_energy_now_kwh=usable_now,
                    usable_energy_above_reserve_kwh=usable_above_reserve,
                    constrained_by=tuple(constrained_by),
                )
            return TradingRecommendation(
                "export_to_grid",
                "feed_in_price_above_export_floor_with_battery_reserve_available",
                confidence="high",
                usable_energy_now_kwh=usable_now,
                usable_energy_above_reserve_kwh=usable_above_reserve,
                constrained_by=tuple(constrained_by),
            )
        constrained_by.append("battery_reserve")
    if is_grid_charge_profitable(effective_import, charge_ceiling) and grid_charge_allowed:
        if _battery_has_room(site_context):
            return TradingRecommendation(
                "charge_from_grid",
                "import_price_below_charge_ceiling_with_battery_room_available",
                confidence="high",
                usable_energy_now_kwh=usable_now,
                usable_energy_above_reserve_kwh=usable_above_reserve,
                constrained_by=tuple(constrained_by),
            )
        constrained_by.append("battery_full")
    if is_effectively_zero(feed_in_price, zero_deadband):
        return TradingRecommendation(
            "charge_from_solar",
            "feed_in_price_effectively_zero",
            usable_energy_now_kwh=usable_now,
            usable_energy_above_reserve_kwh=usable_above_reserve,
            constrained_by=tuple(constrained_by),
        )
    if (
        effective_import is not None
        and effective_feed_in is not None
        and effective_import > abs(effective_feed_in)
        and _battery_has_energy_above_reserve(site_context)
    ):
        return TradingRecommendation(
            "discharge_to_home",
            "import_price_above_feed_in_value_with_battery_reserve_available",
            usable_energy_now_kwh=usable_now,
            usable_energy_above_reserve_kwh=usable_above_reserve,
            constrained_by=tuple(constrained_by),
        )
    return TradingRecommendation(
        "hold",
        "no_profitable_unconstrained_action",
        confidence="low" if site_context and site_context.missing_inputs else "medium",
        usable_energy_now_kwh=usable_now,
        usable_energy_above_reserve_kwh=usable_above_reserve,
        constrained_by=tuple(constrained_by),
    )


def build_grid_buy_plan(
    forecast: Iterable[ChannelData],
    pricing_mode: str,
    *,
    charge_ceiling: float,
    target_grid_buy_kwh: float,
    max_charge_kw: float | None,
    already_bought_kwh: float | None = None,
) -> dict[str, Any] | None:
    """Build a cheapest-first grid buy plan across the forecast horizon."""
    remaining_target_kwh = max(0.0, target_grid_buy_kwh - (already_bought_kwh or 0.0))
    if remaining_target_kwh <= 0 or max_charge_kw is None or max_charge_kw <= 0:
        return None

    candidates: list[dict[str, Any]] = []
    for interval in forecast:
        price = extract_price(interval, pricing_mode)
        if price is None or price > charge_ceiling:
            continue
        duration_hours = _interval_duration_hours(interval)
        candidates.append(
            {
                "start_time": interval.get(ATTR_START_TIME),
                "end_time": interval.get(ATTR_END_TIME),
                "price": price,
                "duration_hours": duration_hours,
                "max_energy_kwh": max_charge_kw * duration_hours,
            }
        )

    if not candidates:
        return None

    remaining = remaining_target_kwh
    selected: list[dict[str, Any]] = []
    total_cost = 0.0
    for candidate in sorted(candidates, key=lambda item: item["price"]):
        energy_kwh = min(remaining, candidate["max_energy_kwh"])
        if energy_kwh <= 0:
            continue
        rate_kw = min(max_charge_kw, energy_kwh / candidate["duration_hours"])
        selected_item = {
            **candidate,
            "energy_kwh": energy_kwh,
            "rate_kw": rate_kw,
        }
        selected.append(selected_item)
        total_cost += energy_kwh * candidate["price"]
        remaining -= energy_kwh
        if remaining <= 0:
            break

    if not selected:
        return None

    energy_total = remaining_target_kwh - max(0.0, remaining)
    return {
        "target_energy_kwh": target_grid_buy_kwh,
        "already_bought_kwh": already_bought_kwh or 0.0,
        "planned_energy_kwh": energy_total,
        "remaining_energy_kwh": max(0.0, remaining),
        "expected_battery_energy_kwh": energy_total * GRID_CHARGE_EFFICIENCY,
        "grid_charge_efficiency": GRID_CHARGE_EFFICIENCY,
        "average_price": total_cost / energy_total if energy_total else None,
        "interval_count": len(selected),
        "intervals": sorted(selected, key=lambda item: str(item.get("start_time"))),
        "reason": "cheapest_intervals_below_charge_ceiling",
    }


def current_plan_rate(plan: dict[str, Any] | None, current_start_time: str | None) -> float:
    """Return the planned current charge rate from a grid buy plan."""
    if plan is None or current_start_time is None:
        return 0.0
    for interval in plan.get("intervals", []):
        if interval.get("start_time") == current_start_time:
            rate = interval.get("rate_kw")
            return float(rate) if isinstance(rate, int | float) else 0.0
    return 0.0


def assumed_grid_charge_energy_today(plan: dict[str, Any] | None, now: datetime | None = None) -> float:
    """Return grid charge energy assumed completed from the current buy plan."""
    if plan is None:
        return 0.0

    now = now or dt_util.utcnow()
    completed_energy = 0.0
    for interval in plan.get("intervals", []):
        energy_kwh = interval.get("energy_kwh")
        if not isinstance(energy_kwh, int | float):
            continue
        start = _parse_datetime(interval.get("start_time"))
        end = _parse_datetime(interval.get("end_time"))
        if start is None or end is None:
            continue
        if now >= end:
            completed_energy += float(energy_kwh)
            continue
        if start <= now < end:
            duration = (end - start).total_seconds()
            elapsed = (now - start).total_seconds()
            if duration > 0 and elapsed > 0:
                completed_energy += float(energy_kwh) * min(1.0, elapsed / duration)
    return completed_energy


def target_battery_power_kw(
    recommendation: TradingRecommendation,
    *,
    site_context: SiteContext | None,
    grid_buy_plan_rate_kw: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """Return target battery power in kW, positive charge and negative discharge."""
    max_charge_kw = site_context.inverter_max_charge_kw if site_context else None
    max_discharge_kw = site_context.inverter_max_discharge_kw if site_context else None
    export_limit_kw = site_context.normal_export_limit_kw if site_context else None
    usable_above_reserve = site_context.usable_energy_above_reserve_kwh if site_context else None
    attrs = {
        "action": recommendation.action,
        "reason": recommendation.reason,
        "confidence": recommendation.confidence,
        "constrained_by": list(recommendation.constrained_by),
    }

    if recommendation.action == "charge_from_grid":
        if grid_buy_plan_rate_kw > 0:
            rate = grid_buy_plan_rate_kw
        elif max_charge_kw is not None:
            rate = max_charge_kw
        else:
            rate = 0.0
        attrs["target_direction"] = "charge"
        attrs["grid_charge_efficiency"] = GRID_CHARGE_EFFICIENCY
        return max(0.0, rate), attrs

    if recommendation.action == "charge_from_solar":
        solar_surplus_kw = site_context.solar_surplus_kw if site_context else None
        if solar_surplus_kw is None:
            solar_surplus_kw = 0.0
        if max_charge_kw is not None:
            solar_surplus_kw = min(solar_surplus_kw, max_charge_kw)
        attrs["target_direction"] = "charge"
        attrs["source"] = "solar_surplus"
        attrs["pv_discharge_efficiency"] = PV_DISCHARGE_EFFICIENCY
        return max(0.0, solar_surplus_kw), attrs

    if recommendation.action in {"export_to_grid", "discharge_to_home"}:
        rate_limit = max_discharge_kw
        if recommendation.action == "export_to_grid" and export_limit_kw is not None:
            rate_limit = min(rate_limit, export_limit_kw) if rate_limit is not None else export_limit_kw
        if rate_limit is None:
            rate_limit = 0.0
        if usable_above_reserve is not None:
            rate_limit = min(rate_limit, usable_above_reserve * PV_DISCHARGE_EFFICIENCY)
        attrs["target_direction"] = "discharge"
        attrs["pv_discharge_efficiency"] = PV_DISCHARGE_EFFICIENCY
        return -max(0.0, rate_limit), attrs

    attrs["target_direction"] = "hold"
    return 0.0, attrs


def summarise_window(window: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    """Return sensor state and attributes for a trading window."""
    if window is None:
        return None, {}
    price_values = [window.get("average_price"), window.get("max_price"), window.get("min_price")]
    numeric_values = [value for value in price_values if isinstance(value, int | float)]
    attrs = dict(window)
    if numeric_values and "average_price" not in attrs:
        attrs["average_price"] = fmean(numeric_values)
    return attrs.get("average_price"), attrs

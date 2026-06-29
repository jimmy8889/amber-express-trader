"""Constants for the Amber Express Trader integration."""

from typing import Final

DOMAIN: Final = "amber_express_trader"

# API Configuration
API_URL: Final = "https://api.amber.com.au/v1"
API_DEVELOPER_URL: Final = "https://app.amber.com.au/developers/"
WEBSOCKET_URL: Final = "wss://api-ws.amber.com.au"

# WebSocket Configuration
WS_MIN_RECONNECT_DELAY: Final = 5  # seconds
WS_MAX_RECONNECT_DELAY: Final = 60  # seconds
WS_HEARTBEAT_INTERVAL: Final = 30  # seconds
WS_STALE_TIMEOUT: Final = 360  # 6 minutes - reconnect if no price update received

# Forecast configuration
# Maximum value for the Amber API `/current` prices `next` parameter (documented upstream).
MAX_FORECAST_INTERVALS: Final = 2048

# Channel types
CHANNEL_GENERAL: Final = "general"
CHANNEL_FEED_IN: Final = "feed_in"
CHANNEL_CONTROLLED_LOAD: Final = "controlled_load"

# Pricing modes
PRICING_MODE_AEMO: Final = "per_kwh"  # Uses per_kwh
PRICING_MODE_APP: Final = "advanced_price_predicted"  # Uses advanced_price_predicted

# Config keys
CONF_API_TOKEN: Final = "api_token"  # noqa: S105
CONF_FORECAST_INTERVALS: Final = "forecast_intervals"
CONF_SITE_ID: Final = "site_id"
CONF_SITE_NAME: Final = "site_name"
CONF_PRICING_MODE: Final = "pricing_mode"
CONF_ENABLE_WEBSOCKET: Final = "enable_websocket"
CONF_WAIT_FOR_CONFIRMED: Final = "wait_for_confirmed"
CONF_CONFIRMATION_TIMEOUT: Final = "confirmation_timeout"
CONF_DEMAND_WINDOW_PRICE: Final = "demand_window_price"
CONF_POLLING_STRATEGY: Final = "polling_strategy"
CONF_FIXED_BOUNDARY_OFFSETS: Final = "fixed_boundary_offsets"
CONF_ZERO_PRICE_DEADBAND: Final = "zero_price_deadband"
CONF_EXPORT_PRICE_FLOOR: Final = "export_price_floor"
CONF_CHARGE_PRICE_CEILING: Final = "charge_price_ceiling"
CONF_SPIKE_PRICE_THRESHOLD: Final = "spike_price_threshold"
CONF_TARGET_GRID_BUY_KWH: Final = "target_grid_buy_kwh"
CONF_BATTERY_SOC_ENTITY: Final = "battery_soc_entity"
CONF_BATTERY_POWER_ENTITY: Final = "battery_power_entity"
CONF_GRID_POWER_ENTITY: Final = "grid_power_entity"
CONF_SOLAR_POWER_ENTITY: Final = "solar_power_entity"
CONF_HOUSE_LOAD_ENTITY: Final = "house_load_entity"
CONF_PV_ENERGY_TODAY_ENTITY: Final = "pv_energy_today_entity"
CONF_PV_FORECAST_REMAINING_TODAY_ENTITY: Final = "pv_forecast_remaining_today_entity"
CONF_GRID_CHARGE_ENERGY_TODAY_ENTITY: Final = "grid_charge_energy_today_entity"
CONF_BATTERY_CHARGE_ENERGY_TODAY_ENTITY: Final = "battery_charge_energy_today_entity"
CONF_BATTERY_DISCHARGE_ENERGY_TODAY_ENTITY: Final = "battery_discharge_energy_today_entity"
CONF_BATTERY_USABLE_KWH: Final = "battery_usable_kwh"
CONF_BATTERY_MIN_RESERVE_KWH: Final = "battery_min_reserve_kwh"
CONF_INVERTER_MAX_CHARGE_KW: Final = "inverter_max_charge_kw"
CONF_INVERTER_MAX_DISCHARGE_KW: Final = "inverter_max_discharge_kw"
CONF_NORMAL_EXPORT_LIMIT_KW: Final = "normal_export_limit_kw"
CONF_ALLOW_GRID_CHARGE: Final = "allow_grid_charge"
CONF_ALLOW_BATTERY_EXPORT: Final = "allow_battery_export"
CONF_BATTERY_USABLE_KWH_ENTITY: Final = "battery_usable_kwh_entity"
CONF_BATTERY_MIN_RESERVE_KWH_ENTITY: Final = "battery_min_reserve_kwh_entity"
CONF_INVERTER_MAX_CHARGE_KW_ENTITY: Final = "inverter_max_charge_kw_entity"
CONF_INVERTER_MAX_DISCHARGE_KW_ENTITY: Final = "inverter_max_discharge_kw_entity"
CONF_NORMAL_EXPORT_LIMIT_KW_ENTITY: Final = "normal_export_limit_kw_entity"
CONF_ALLOW_GRID_CHARGE_ENTITY: Final = "allow_grid_charge_entity"
CONF_ALLOW_BATTERY_EXPORT_ENTITY: Final = "allow_battery_export_entity"

SITE_CONTEXT_ENTITY_OPTIONS: Final = (
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_POWER_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_PV_ENERGY_TODAY_ENTITY,
    CONF_PV_FORECAST_REMAINING_TODAY_ENTITY,
    CONF_BATTERY_CHARGE_ENERGY_TODAY_ENTITY,
    CONF_BATTERY_DISCHARGE_ENERGY_TODAY_ENTITY,
)

SITE_CONTEXT_VALUE_OPTIONS: Final = (
    CONF_BATTERY_USABLE_KWH,
    CONF_BATTERY_MIN_RESERVE_KWH,
    CONF_INVERTER_MAX_CHARGE_KW,
    CONF_INVERTER_MAX_DISCHARGE_KW,
    CONF_NORMAL_EXPORT_LIMIT_KW,
)

# Polling strategies
POLLING_STRATEGY_ADAPTIVE: Final = "adaptive"
POLLING_STRATEGY_FIXED_BOUNDARY: Final = "fixed_boundary"
POLLING_STRATEGY_HYBRID: Final = "hybrid_boundary_adaptive"

# Default options
DEFAULT_PRICING_MODE: Final = PRICING_MODE_APP
# Default to the maximum forecast window supported by the Amber API
DEFAULT_FORECAST_INTERVALS: Final = MAX_FORECAST_INTERVALS
DEFAULT_ENABLE_WEBSOCKET: Final = True
DEFAULT_WAIT_FOR_CONFIRMED: Final = True  # Keep polling until non-estimated price
DEFAULT_CONFIRMATION_TIMEOUT: Final = 45  # seconds to wait for confirmed price
DEFAULT_DEMAND_WINDOW_PRICE: Final = 0.0  # $/kWh penalty during demand window
DEFAULT_POLLING_STRATEGY: Final = POLLING_STRATEGY_HYBRID
DEFAULT_FIXED_BOUNDARY_OFFSETS: Final = "3,8,15,20"
DEFAULT_ZERO_PRICE_DEADBAND: Final = 0.001
DEFAULT_EXPORT_PRICE_FLOOR: Final = 0.11
DEFAULT_CHARGE_PRICE_CEILING: Final = 0.03
DEFAULT_SPIKE_PRICE_THRESHOLD: Final = 0.50
DEFAULT_TARGET_GRID_BUY_KWH: Final = 0.0
DEFAULT_SITE_CONTEXT_ENTITY: Final = ""
DEFAULT_SITE_CONTEXT_VALUE: Final = ""
DEFAULT_ALLOW_GRID_CHARGE: Final = True
DEFAULT_ALLOW_BATTERY_EXPORT: Final = True
GRID_CHARGE_EFFICIENCY: Final = 0.80
PV_DISCHARGE_EFFICIENCY: Final = 0.85

# Sensor attributes
ATTR_FORECAST: Final = "forecast"
ATTR_DETAILED_FORECAST: Final = "detailedForecast"
ATTR_START_TIME: Final = "start_time"
ATTR_END_TIME: Final = "end_time"
ATTR_PER_KWH: Final = "per_kwh"
ATTR_SPOT_PER_KWH: Final = "spot_per_kwh"
ATTR_ADVANCED_PRICE: Final = "advanced_price_predicted"
ATTR_RENEWABLES: Final = "renewables"
ATTR_SPIKE_STATUS: Final = "spike_status"
ATTR_DESCRIPTOR: Final = "descriptor"
ATTR_ESTIMATE: Final = "estimate"
ATTR_NEM_TIME: Final = "nem_time"
ATTR_DEMAND_WINDOW: Final = "demand_window"
ATTR_TARIFF_PERIOD: Final = "tariff_period"
ATTR_TARIFF_SEASON: Final = "tariff_season"
ATTR_TARIFF_BLOCK: Final = "tariff_block"
ATTR_DURATION: Final = "duration"

# Data source tracking
DATA_SOURCE_POLLING: Final = "polling"
DATA_SOURCE_WEBSOCKET: Final = "websocket"

# Subentry types
SUBENTRY_TYPE_SITE: Final = "site"

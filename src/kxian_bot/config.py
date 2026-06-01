from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from kxian_bot.models import Exchange, Mode
from kxian_bot.strategies.factory import SUPPORTED_STRATEGIES


MarketDataSource = Literal["exchange", "sqlite"]
DEFAULT_STOP_LOSS_PCT = 2.0
DEFAULT_TAKE_PROFIT_PCT = 4.0
DEFAULT_TRAILING_STOP_PCT = 2.0
StrategyName = Literal[
    "moving_average_cross",
    "donchian_breakout",
    "trend_pullback",
    "mean_reversion",
    "rsi_mean_reversion",
    "momentum_breakout",
    "bollinger_mean_reversion",
    "regime_breakout",
    "regime_filtered_ma_cross",
    "trend_filtered_ma_cross",
    "defensive_trend",
    "panic_rebound",
    "regime_adaptive_long",
    "volatility_breakout_trend",
    "downtrend_breakdown_short",
]


class ConfigError(RuntimeError):
    pass


class RuntimeConfig(BaseModel):
    mode: Mode = "paper"
    exchange: Exchange = "binance"
    market_data_source: MarketDataSource = "exchange"
    db_path: str = "data/kxian.sqlite3"
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    poll_seconds: int = 30
    loop_lock_stale_seconds: float = Field(default=120.0, gt=0)
    max_consecutive_loop_errors: int = Field(default=3, ge=0)
    starting_usdt: float = 1000.0
    fee_rate: float = Field(default=0.001, ge=0)
    slippage_rate: float = Field(default=0.0005, ge=0)
    risk_per_trade: float = Field(default=0.1, gt=0, le=1)
    max_position_usdt: float = Field(default=300.0, gt=0)
    min_order_usdt: float = Field(default=10.0, gt=0)
    price_step: float = Field(default=0.01, gt=0)
    quantity_step: float = Field(default=0.00001, gt=0)
    min_exchange_quantity: float = Field(default=0.0, ge=0)
    min_exchange_notional: float = Field(default=10.0, ge=0)
    max_daily_trades: int = Field(default=20, gt=0)
    max_daily_loss_usdt: float = Field(default=100.0, gt=0)
    cooldown_seconds: int = Field(default=0, ge=0)
    allow_sell_without_position: bool = False
    stop_loss_pct: float = Field(default=0.0, ge=0, lt=100)
    take_profit_pct: float = Field(default=0.0, ge=0)
    trailing_stop_pct: float = Field(default=0.0, ge=0, lt=100)
    strategy: StrategyName = "moving_average_cross"
    short_window: int = Field(default=5, ge=2)
    long_window: int = Field(default=20, ge=3)
    allow_live: bool = False
    live_dry_run: bool = True
    use_testnet: bool = True
    enable_testnet_autotrade: bool = False
    enable_live_autotrade: bool = False
    live_confirmation: str = ""
    live_credentials_confirmed: bool = False
    max_live_order_usdt: float = Field(default=50.0, gt=0)
    require_strategy_gate: bool = True
    require_sample_validation_gate: bool = True
    min_gate_trades: int = Field(default=30, ge=0)
    min_gate_return_pct: float = 0.0
    max_gate_drawdown_pct: float = Field(default=20.0, ge=0)
    min_gate_profit_factor: float = Field(default=1.0, ge=0)
    require_stress_gate: bool = True
    min_stress_pass_rate: float = Field(default=100.0, ge=0, le=100)
    max_stress_drawdown_pct: float = Field(default=25.0, ge=0)
    require_walk_forward_gate: bool = True
    min_walk_forward_segments: int = Field(default=3, ge=1)
    min_walk_forward_pass_rate: float = Field(default=60.0, ge=0, le=100)
    min_walk_forward_trades: int = Field(default=30, ge=0)
    binance_api_key: str = ""
    binance_api_secret: str = ""
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_api_passphrase: str = ""
    bitget_api_key: str = ""
    bitget_api_secret: str = ""
    bitget_api_passphrase: str = ""


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_config(validate_execution: bool = True) -> RuntimeConfig:
    load_dotenv()
    try:
        config = RuntimeConfig(
            mode=os.getenv("KXIAN_MODE", "paper"),
            exchange=os.getenv("KXIAN_EXCHANGE", "binance"),
            market_data_source=os.getenv("KXIAN_MARKET_DATA_SOURCE", "exchange"),
            db_path=os.getenv("KXIAN_DB_PATH", "data/kxian.sqlite3"),
            symbol=os.getenv("KXIAN_SYMBOL", "BTCUSDT"),
            interval=os.getenv("KXIAN_INTERVAL", "1m"),
            poll_seconds=int(os.getenv("KXIAN_POLL_SECONDS", "30")),
            loop_lock_stale_seconds=float(os.getenv("KXIAN_LOOP_LOCK_STALE_SECONDS", "120")),
            max_consecutive_loop_errors=int(os.getenv("KXIAN_MAX_CONSECUTIVE_LOOP_ERRORS", "3")),
            starting_usdt=float(os.getenv("KXIAN_STARTING_USDT", "1000")),
            fee_rate=float(os.getenv("KXIAN_FEE_RATE", "0.001")),
            slippage_rate=float(os.getenv("KXIAN_SLIPPAGE_RATE", "0.0005")),
            risk_per_trade=float(os.getenv("KXIAN_RISK_PER_TRADE", "0.1")),
            max_position_usdt=float(os.getenv("KXIAN_MAX_POSITION_USDT", "300")),
            min_order_usdt=float(os.getenv("KXIAN_MIN_ORDER_USDT", "10")),
            price_step=float(os.getenv("KXIAN_PRICE_STEP", "0.01")),
            quantity_step=float(os.getenv("KXIAN_QUANTITY_STEP", "0.00001")),
            min_exchange_quantity=float(os.getenv("KXIAN_MIN_EXCHANGE_QUANTITY", "0")),
            min_exchange_notional=float(os.getenv("KXIAN_MIN_EXCHANGE_NOTIONAL", "10")),
            max_daily_trades=int(os.getenv("KXIAN_MAX_DAILY_TRADES", "20")),
            max_daily_loss_usdt=float(os.getenv("KXIAN_MAX_DAILY_LOSS_USDT", "100")),
            cooldown_seconds=int(os.getenv("KXIAN_COOLDOWN_SECONDS", "0")),
            allow_sell_without_position=_get_bool("KXIAN_ALLOW_SELL_WITHOUT_POSITION", False),
            stop_loss_pct=float(os.getenv("KXIAN_STOP_LOSS_PCT", str(DEFAULT_STOP_LOSS_PCT))),
            take_profit_pct=float(os.getenv("KXIAN_TAKE_PROFIT_PCT", str(DEFAULT_TAKE_PROFIT_PCT))),
            trailing_stop_pct=float(os.getenv("KXIAN_TRAILING_STOP_PCT", str(DEFAULT_TRAILING_STOP_PCT))),
            strategy=os.getenv("KXIAN_STRATEGY", "moving_average_cross"),
            short_window=int(os.getenv("KXIAN_SHORT_WINDOW", "5")),
            long_window=int(os.getenv("KXIAN_LONG_WINDOW", "20")),
            allow_live=_get_bool("KXIAN_ALLOW_LIVE", False),
            live_dry_run=_get_bool("KXIAN_LIVE_DRY_RUN", True),
            use_testnet=_get_bool("KXIAN_USE_TESTNET", True),
            enable_testnet_autotrade=_get_bool("KXIAN_ENABLE_TESTNET_AUTOTRADE", False),
            enable_live_autotrade=_get_bool("KXIAN_ENABLE_LIVE_AUTOTRADE", False),
            live_confirmation=os.getenv("KXIAN_LIVE_CONFIRMATION", ""),
            live_credentials_confirmed=_get_bool("KXIAN_LIVE_CREDENTIALS_CONFIRMED", False),
            max_live_order_usdt=float(os.getenv("KXIAN_MAX_LIVE_ORDER_USDT", "50")),
            require_strategy_gate=_get_bool("KXIAN_REQUIRE_STRATEGY_GATE", True),
            require_sample_validation_gate=_get_bool("KXIAN_REQUIRE_SAMPLE_VALIDATION_GATE", True),
            min_gate_trades=int(os.getenv("KXIAN_MIN_GATE_TRADES", "30")),
            min_gate_return_pct=float(os.getenv("KXIAN_MIN_GATE_RETURN_PCT", "0")),
            max_gate_drawdown_pct=float(os.getenv("KXIAN_MAX_GATE_DRAWDOWN_PCT", "20")),
            min_gate_profit_factor=float(os.getenv("KXIAN_MIN_GATE_PROFIT_FACTOR", "1")),
            require_stress_gate=_get_bool("KXIAN_REQUIRE_STRESS_GATE", True),
            min_stress_pass_rate=float(os.getenv("KXIAN_MIN_STRESS_PASS_RATE", "100")),
            max_stress_drawdown_pct=float(os.getenv("KXIAN_MAX_STRESS_DRAWDOWN_PCT", "25")),
            require_walk_forward_gate=_get_bool("KXIAN_REQUIRE_WALK_FORWARD_GATE", True),
            min_walk_forward_segments=int(os.getenv("KXIAN_MIN_WALK_FORWARD_SEGMENTS", "3")),
            min_walk_forward_pass_rate=float(os.getenv("KXIAN_MIN_WALK_FORWARD_PASS_RATE", "60")),
            min_walk_forward_trades=int(os.getenv("KXIAN_MIN_WALK_FORWARD_TRADES", "30")),
            binance_api_key=os.getenv("KXIAN_BINANCE_API_KEY", ""),
            binance_api_secret=os.getenv("KXIAN_BINANCE_API_SECRET", ""),
            okx_api_key=os.getenv("KXIAN_OKX_API_KEY", ""),
            okx_api_secret=os.getenv("KXIAN_OKX_API_SECRET", ""),
            okx_api_passphrase=os.getenv("KXIAN_OKX_API_PASSPHRASE", ""),
            bitget_api_key=os.getenv("KXIAN_BITGET_API_KEY", ""),
            bitget_api_secret=os.getenv("KXIAN_BITGET_API_SECRET", ""),
            bitget_api_passphrase=os.getenv("KXIAN_BITGET_API_PASSPHRASE", ""),
        )
    except ValidationError as exc:
        text = str(exc)
        if "market_data_source" in text:
            raise ConfigError("KXIAN_MARKET_DATA_SOURCE must be one of: exchange, sqlite") from exc
        if "exchange" in text:
            raise ConfigError("KXIAN_EXCHANGE must be one of: binance, okx, bitget") from exc
        if "strategy" in text:
            raise ConfigError(
                f"KXIAN_STRATEGY must be one of: {', '.join(SUPPORTED_STRATEGIES)}"
            ) from exc
        raise ConfigError(text) from exc

    if not validate_execution:
        return config

    if config.mode == "live" and not config.allow_live:
        raise ConfigError("Live mode requires KXIAN_ALLOW_LIVE=true")
    if config.mode == "live" and not config.live_dry_run:
        if not config.enable_live_autotrade:
            raise ConfigError("Live order execution requires KXIAN_ENABLE_LIVE_AUTOTRADE=true")
        if config.use_testnet:
            raise ConfigError("Live order execution requires KXIAN_USE_TESTNET=false")
        if config.live_confirmation != expected_live_confirmation(config):
            raise ConfigError(
                f"Live order execution requires KXIAN_LIVE_CONFIRMATION={expected_live_confirmation(config)}"
            )
        if not config.live_credentials_confirmed:
            raise ConfigError(
                "Live order execution requires KXIAN_LIVE_CREDENTIALS_CONFIRMED=true after production API keys are verified"
            )
    if config.mode == "testnet" and config.exchange == "binance" and not config.use_testnet:
        raise ConfigError("Binance testnet mode requires KXIAN_USE_TESTNET=true")
    if config.mode == "testnet" and config.exchange == "bitget":
        raise ConfigError("Bitget spot sandbox/demo is not confirmed; use live mode with live dry-run gates for Bitget")
    if config.mode in {"testnet", "live"} and config.exchange == "binance":
        if not config.binance_api_key or not config.binance_api_secret:
            raise ConfigError("Live Binance credentials require Binance credentials")
    if config.mode in {"testnet", "live"} and config.exchange == "okx":
        if not config.okx_api_key or not config.okx_api_secret or not config.okx_api_passphrase:
            raise ConfigError("Live OKX credentials require OKX credentials")
    if config.mode in {"testnet", "live"} and config.exchange == "bitget":
        if not config.bitget_api_key or not config.bitget_api_secret or not config.bitget_api_passphrase:
            raise ConfigError("Live Bitget credentials require Bitget credentials")
    return config


def expected_live_confirmation(config: RuntimeConfig) -> str:
    return f"LIVE:{config.exchange}:{config.symbol}:{config.interval}"

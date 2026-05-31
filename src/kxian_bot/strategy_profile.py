from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig


PROFILE_PARAMETER_KEYS = (
    "strategy",
    "short_window",
    "long_window",
    "stop_loss_pct",
    "take_profit_pct",
    "trailing_stop_pct",
    "cooldown_seconds",
)


def apply_active_strategy_profile(config: RuntimeConfig, storage: Any) -> RuntimeConfig:
    profile = storage.active_strategy_profile(config.mode, config.exchange, config.symbol, config.interval)
    if profile is None:
        return config

    updates: dict[str, Any] = {}
    parameters = profile.get("parameters", {})
    if profile.get("strategy"):
        updates["strategy"] = str(profile["strategy"])
    elif "strategy" in parameters:
        updates["strategy"] = str(parameters["strategy"])
    for key in ("short_window", "long_window"):
        if key not in parameters:
            continue
        updates[key] = _coerce_parameter(key, parameters[key])
    for key in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct"):
        updates[key] = _coerce_parameter(key, parameters.get(key, 0.0))
    if "cooldown_seconds" in parameters:
        updates["cooldown_seconds"] = _coerce_parameter("cooldown_seconds", parameters["cooldown_seconds"])
    if not updates:
        return config
    return config.model_copy(update=updates)


def active_profile_payload(
    *,
    mode: str,
    exchange: str,
    symbol: str,
    interval: str,
    strategy: str,
    parameters: dict[str, Any],
    evidence: dict[str, Any],
    updated_by: str,
    updated_at: float,
) -> dict[str, Any]:
    return {
        "profile_key": profile_key(mode, exchange, symbol, interval),
        "updated_at": updated_at,
        "mode": mode,
        "exchange": exchange,
        "symbol": symbol,
        "interval": interval,
        "strategy": strategy,
        "parameters": {
            "strategy": strategy,
            "short_window": int(parameters["short_window"]),
            "long_window": int(parameters["long_window"]),
            "stop_loss_pct": float(parameters.get("stop_loss_pct", 0.0)),
            "take_profit_pct": float(parameters.get("take_profit_pct", 0.0)),
            "trailing_stop_pct": float(parameters.get("trailing_stop_pct", 0.0)),
            "cooldown_seconds": int(parameters.get("cooldown_seconds", 0)),
        },
        "evidence": evidence,
        "active": True,
        "updated_by": updated_by,
    }


def profile_key(mode: str, exchange: str, symbol: str, interval: str) -> str:
    return f"{mode}:{exchange}:{symbol}:{interval}"


def _coerce_parameter(key: str, value: Any) -> int | float:
    if key in {"short_window", "long_window", "cooldown_seconds"}:
        return int(value)
    return float(value)

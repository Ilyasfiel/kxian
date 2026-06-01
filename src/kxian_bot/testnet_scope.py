from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig


CLOSED_LOOP_EXCHANGE = "binance"
CLOSED_LOOP_SYMBOL = "BTCUSDT"
CLOSED_LOOP_INTERVAL = "4h"
MIN_TESTNET_OBSERVATION_CYCLES = 6


def testnet_closed_loop_scope_failures(config: RuntimeConfig, *, require_autotrade: bool = True) -> list[str]:
    failures: list[str] = []
    if config.mode != "testnet":
        failures.append("testnet_mode_required")
    if config.exchange != CLOSED_LOOP_EXCHANGE:
        failures.append("binance_exchange_required")
    if config.symbol != CLOSED_LOOP_SYMBOL:
        failures.append("btcusdt_symbol_required")
    if config.interval != CLOSED_LOOP_INTERVAL:
        failures.append("4h_interval_required")
    if not config.use_testnet:
        failures.append("testnet_endpoint_required")
    if require_autotrade and not config.enable_testnet_autotrade:
        failures.append("testnet_autotrade_disabled")
    if config.allow_live:
        failures.append("live_allow_must_remain_disabled")
    if config.enable_live_autotrade:
        failures.append("live_autotrade_must_remain_disabled")
    if not config.live_dry_run:
        failures.append("live_dry_run_must_remain_enabled")
    if config.live_confirmation:
        failures.append("live_confirmation_must_remain_empty")
    return failures


def testnet_closed_loop_next_steps(failures: list[str]) -> list[str]:
    mapping = {
        "testnet_mode_required": "set KXIAN_MODE=testnet",
        "binance_exchange_required": "set KXIAN_EXCHANGE=binance",
        "btcusdt_symbol_required": "set KXIAN_SYMBOL=BTCUSDT",
        "4h_interval_required": "set KXIAN_INTERVAL=4h",
        "testnet_endpoint_required": "set KXIAN_USE_TESTNET=true",
        "testnet_autotrade_disabled": "set KXIAN_ENABLE_TESTNET_AUTOTRADE=true for bounded testnet closure only",
        "live_allow_must_remain_disabled": "set KXIAN_ALLOW_LIVE=false",
        "live_autotrade_must_remain_disabled": "set KXIAN_ENABLE_LIVE_AUTOTRADE=false",
        "live_dry_run_must_remain_enabled": "set KXIAN_LIVE_DRY_RUN=true",
        "live_confirmation_must_remain_empty": "clear KXIAN_LIVE_CONFIRMATION",
    }
    return [mapping[failure] for failure in failures if failure in mapping]


def testnet_observation_failures(
    observation: dict[str, Any] | None,
    *,
    execute_loop: bool,
    require_min_cycles: bool = True,
) -> list[str]:
    if observation is None:
        return ["missing_testnet_observation"]
    failures: list[str] = []
    if observation.get("status") != "pass":
        failures.append("testnet_observation_not_passed")
    if bool(observation.get("execute_loop")) != execute_loop:
        failures.append("testnet_observation_scope_mismatch")
    if require_min_cycles and int(observation.get("cycles_completed") or 0) < MIN_TESTNET_OBSERVATION_CYCLES:
        failures.append("insufficient_testnet_observation_cycles")
    lifecycle = observation.get("order_lifecycle")
    if execute_loop:
        if not isinstance(lifecycle, dict):
            failures.append("missing_order_lifecycle")
        elif not bool(lifecycle.get("acceptable", False)):
            failures.append("testnet_observation_order_lifecycle_not_acceptable")
    elif isinstance(lifecycle, dict) and not bool(lifecycle.get("acceptable", False)):
        failures.append("testnet_observation_order_lifecycle_not_acceptable")
    return failures


def has_unacceptable_order_lifecycle(observation: dict[str, Any] | None) -> bool:
    lifecycle = observation.get("order_lifecycle") if isinstance(observation, dict) else None
    return isinstance(lifecycle, dict) and not bool(lifecycle.get("acceptable", False))

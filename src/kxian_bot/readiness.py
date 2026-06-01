from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.preflight import run_preflight
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategy_profile import apply_active_strategy_profile


def run_readiness(
    config: RuntimeConfig,
    storage: SQLiteStorage | None = None,
    require_testnet_autotrade: bool = False,
) -> dict[str, Any]:
    storage = storage or SQLiteStorage(config.db_path)
    config = apply_active_strategy_profile(config, storage)
    preflight = run_preflight(config, storage, require_testnet_autotrade=require_testnet_autotrade)
    checks = [
        _profile_check(config),
        _credential_check(config),
        _endpoint_check(config),
        _automation_check(config, require_testnet_autotrade=require_testnet_autotrade),
        _risk_check(config),
        _live_support_check(config),
        _preflight_summary_check(preflight),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "credentials": _credential_presence(config),
        "checks": checks,
        "preflight": preflight,
        "next_steps": _next_steps(config, checks, preflight),
    }


def _profile_check(config: RuntimeConfig) -> dict[str, Any]:
    failures: list[str] = []
    if config.short_window >= config.long_window:
        failures.append("short_window_must_be_less_than_long_window")
    if config.min_order_usdt > config.max_position_usdt:
        failures.append("min_order_exceeds_max_position")
    return {
        "name": "profile",
        "status": "pass" if not failures else "fail",
        "message": "strategy profile is coherent" if not failures else "strategy profile has invalid sizing or window settings",
        "details": {
            "failures": failures,
            "short_window": config.short_window,
            "long_window": config.long_window,
            "min_order_usdt": config.min_order_usdt,
            "max_position_usdt": config.max_position_usdt,
        },
    }


def _credential_check(config: RuntimeConfig) -> dict[str, Any]:
    presence = _credential_presence(config)
    required = config.mode in {"testnet", "live"}
    failures: list[str] = []
    if required:
        if config.exchange == "binance":
            if not presence["binance_api_key"]:
                failures.append("missing_binance_api_key")
            if not presence["binance_api_secret"]:
                failures.append("missing_binance_api_secret")
        elif config.exchange == "okx":
            if not presence["okx_api_key"]:
                failures.append("missing_okx_api_key")
            if not presence["okx_api_secret"]:
                failures.append("missing_okx_api_secret")
            if not presence["okx_api_passphrase"]:
                failures.append("missing_okx_api_passphrase")
        elif config.exchange == "bitget":
            if not presence["bitget_api_key"]:
                failures.append("missing_bitget_api_key")
            if not presence["bitget_api_secret"]:
                failures.append("missing_bitget_api_secret")
            if not presence["bitget_api_passphrase"]:
                failures.append("missing_bitget_api_passphrase")
        else:
            failures.append("unsupported_exchange")
    return {
        "name": "credentials",
        "status": "pass" if not failures else "fail",
        "message": "required credentials are present" if not failures else "required credentials are missing",
        "details": {"required": required, "failures": failures, "present": presence},
    }


def _endpoint_check(config: RuntimeConfig) -> dict[str, Any]:
    failures: list[str] = []
    if config.mode == "testnet" and config.exchange == "binance" and not config.use_testnet:
        failures.append("binance_testnet_endpoint_required")
    if config.mode == "testnet" and config.exchange == "bitget":
        failures.append("bitget_testnet_not_supported")
    if config.mode == "live" and config.use_testnet:
        failures.append("live_mode_points_to_testnet")
    return {
        "name": "endpoint",
        "status": "pass" if not failures else "fail",
        "message": "exchange endpoint selection is coherent" if not failures else "exchange endpoint selection is unsafe",
        "details": {
            "failures": failures,
            "mode": config.mode,
            "exchange": config.exchange,
            "use_testnet": config.use_testnet,
            "okx_simulated_trading": config.exchange == "okx" and config.mode in {"testnet", "live"},
            "bitget_live_only": config.exchange == "bitget",
        },
    }


def _automation_check(config: RuntimeConfig, *, require_testnet_autotrade: bool = True) -> dict[str, Any]:
    failures: list[str] = []
    if config.mode == "testnet" and require_testnet_autotrade and not config.enable_testnet_autotrade:
        failures.append("testnet_autotrade_disabled")
    if config.mode == "live":
        if not config.allow_live:
            failures.append("live_not_allowed")
        if config.live_dry_run:
            failures.append("live_dry_run_enabled")
        if not config.enable_live_autotrade:
            failures.append("live_autotrade_disabled")
        if config.live_confirmation != expected_live_confirmation(config):
            failures.append("live_confirmation_required")
        if not config.live_credentials_confirmed:
            failures.append("live_credentials_not_confirmed")
        if config.exchange == "bitget" and config.max_live_order_usdt > 5:
            failures.append("bitget_live_canary_limit_exceeded")
    return {
        "name": "automation",
        "status": "pass" if not failures else "fail",
        "message": "automation flags are ready" if not failures else "automation flags are not ready",
        "details": {
            "failures": failures,
            "enable_testnet_autotrade": config.enable_testnet_autotrade,
            "enable_live_autotrade": config.enable_live_autotrade,
            "allow_live": config.allow_live,
            "live_dry_run": config.live_dry_run,
            "live_confirmation_required": expected_live_confirmation(config) if config.mode == "live" else "",
            "live_credentials_confirmed": config.live_credentials_confirmed,
            "max_live_order_usdt": config.max_live_order_usdt,
            "bitget_live_canary_limit": 5 if config.exchange == "bitget" else None,
        },
    }


def _risk_check(config: RuntimeConfig) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    if config.max_daily_loss_usdt > config.starting_usdt:
        failures.append("max_daily_loss_exceeds_starting_usdt")
    if config.risk_per_trade > 0.2:
        warnings.append("risk_per_trade_above_20_percent")
    if config.stop_loss_pct <= 0 and config.trailing_stop_pct <= 0:
        warnings.append("no_protective_exit_configured")
    return {
        "name": "risk",
        "status": "pass" if not failures else "fail",
        "message": "risk settings are within hard limits" if not failures else "risk settings violate hard limits",
        "details": {
            "failures": failures,
            "warnings": warnings,
            "starting_usdt": config.starting_usdt,
            "risk_per_trade": config.risk_per_trade,
            "max_position_usdt": config.max_position_usdt,
            "max_daily_loss_usdt": config.max_daily_loss_usdt,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "trailing_stop_pct": config.trailing_stop_pct,
        },
    }


def _live_support_check(config: RuntimeConfig) -> dict[str, Any]:
    failures: list[str] = []
    if config.mode == "live" and config.exchange not in {"binance", "okx", "bitget"}:
        failures.append("live_exchange_not_supported")
    return {
        "name": "live_support",
        "status": "pass" if not failures else "fail",
        "message": "live execution support is available" if config.mode == "live" and not failures else (
            "live execution is not requested" if not failures else "live exchange is not supported"
        ),
        "details": {
            "failures": failures,
            "mode": config.mode,
            "allow_live": config.allow_live,
            "live_dry_run": config.live_dry_run,
        },
    }


def _preflight_summary_check(preflight: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in preflight.get("checks", []) if check.get("status") != "pass"]
    return {
        "name": "preflight",
        "status": "pass" if preflight.get("status") == "pass" else "fail",
        "message": "startup preflight passes" if preflight.get("status") == "pass" else "startup preflight has blocking checks",
        "details": {"failed_checks": failed},
    }


def _credential_presence(config: RuntimeConfig) -> dict[str, bool]:
    return {
        "binance_api_key": bool(config.binance_api_key),
        "binance_api_secret": bool(config.binance_api_secret),
        "okx_api_key": bool(config.okx_api_key),
        "okx_api_secret": bool(config.okx_api_secret),
        "okx_api_passphrase": bool(config.okx_api_passphrase),
        "bitget_api_key": bool(config.bitget_api_key),
        "bitget_api_secret": bool(config.bitget_api_secret),
        "bitget_api_passphrase": bool(config.bitget_api_passphrase),
    }


def _next_steps(config: RuntimeConfig, checks: list[dict[str, Any]], preflight: dict[str, Any]) -> list[str]:
    failed = {failure for check in checks for failure in check.get("details", {}).get("failures", [])}
    failed_preflight = {check["name"] for check in preflight.get("checks", []) if check.get("status") != "pass"}
    steps: list[str] = []
    if any(item.startswith("missing_") for item in failed):
        credential_scope = "sandbox API" if config.mode == "testnet" else "API"
        steps.append(f"set {credential_scope} credentials for the selected exchange")
    if "testnet_autotrade_disabled" in failed:
        steps.append("set KXIAN_ENABLE_TESTNET_AUTOTRADE=true only after preflight and validation gates pass")
    if "live_dry_run_enabled" in failed:
        steps.append("set KXIAN_LIVE_DRY_RUN=false only after stable testnet observation")
    if "live_autotrade_disabled" in failed:
        steps.append("set KXIAN_ENABLE_LIVE_AUTOTRADE=true only for controlled small live execution")
    if "live_confirmation_required" in failed:
        steps.append(f"set KXIAN_LIVE_CONFIRMATION={expected_live_confirmation(config)} to explicitly confirm the live scope")
    if "live_credentials_not_confirmed" in failed:
        steps.append("set KXIAN_LIVE_CREDENTIALS_CONFIRMED=true only after production API keys are verified, withdrawal is disabled, and the key is not a testnet key")
    if "bitget_testnet_not_supported" in failed:
        steps.append("Bitget spot sandbox/demo is not confirmed; use KXIAN_MODE=live with live dry-run and 5U canary gates")
    if "bitget_live_canary_limit_exceeded" in failed:
        steps.append("set KXIAN_MAX_LIVE_ORDER_USDT<=5 for the Bitget first canary")
    if {"strategy_gate", "stress_gate", "walk_forward_gate"} & failed_preflight:
        steps.append("run backtest, stress-backtest, and walk-forward for the exact current strategy parameters")
    if "sample_validation_gate" in failed_preflight:
        steps.append("run select-samples --promote so the active profile has passing multi-sample evidence")
    if "market_data" in failed_preflight and config.market_data_source == "sqlite":
        steps.append("download or import enough candles for the current interval and window")
    if "open_orders" in failed_preflight:
        steps.append("refresh, fill, or cancel existing sandbox orders before starting a new loop")
    if not steps and config.mode == "testnet":
        if config.enable_testnet_autotrade:
            steps.append("run kxian-bot testnet-dry-run, then add --execute-loop for one bounded sandbox iteration")
        else:
            steps.append(
                "run kxian-bot testnet-dry-run and non-ordering testnet-observe; set KXIAN_ENABLE_TESTNET_AUTOTRADE=true before bounded --execute-loop"
            )
    if not steps and config.mode == "live":
        steps.append("run a bounded live trade-loop with a very small KXIAN_MAX_LIVE_ORDER_USDT and monitor fills")
    if not steps:
        steps.append("review readiness output and keep operating in paper mode until testnet evidence exists")
    return steps

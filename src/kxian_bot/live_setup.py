from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.exchange_health import run_exchange_health_check
from kxian_bot.launch_checklist import run_launch_checklist
from kxian_bot.readiness import run_readiness
from kxian_bot.storage import SQLiteStorage
from kxian_bot.testnet_dry_run import exchange_credential_status


LIVE_CANARY_MAX_ORDER_USDT = 50.0


def run_live_setup_check(
    config: RuntimeConfig,
    storage: SQLiteStorage | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    storage = storage or SQLiteStorage(config.db_path)
    live_config = _live_config(config)
    credential_failures, credential_presence = exchange_credential_status(live_config)
    readiness = run_readiness(live_config, storage)
    launch = run_launch_checklist(live_config, storage, target_mode="live")
    exchange_health = run_exchange_health_check(live_config, timeout_seconds=timeout_seconds)
    checks = [
        _credential_check(credential_failures, credential_presence),
        _readiness_check(readiness),
        _launch_check(launch),
        _exchange_health_check(exchange_health),
        _endpoint_safety_check(live_config, exchange_health),
        _risk_limit_check(live_config),
        _no_order_submission_check(),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "blocked"
    return {
        "status": status,
        "reason": "live_setup_ready" if status == "pass" else "live_setup_blocked",
        "phase": "ready_for_bounded_live_canary" if status == "pass" else "blocked_before_live_canary",
        "mode": "live",
        "exchange": live_config.exchange,
        "symbol": live_config.symbol,
        "interval": live_config.interval,
        "use_testnet": live_config.use_testnet,
        "will_submit_orders": False,
        "live_confirmation_required": expected_live_confirmation(live_config),
        "credentials": {
            "required": True,
            "present": credential_presence,
            "failures": credential_failures,
            "production_credentials_confirmed": live_config.live_credentials_confirmed,
        },
        "risk_limits": {
            "max_live_order_usdt": live_config.max_live_order_usdt,
            "max_live_canary_order_usdt": LIVE_CANARY_MAX_ORDER_USDT,
        },
        "checks": checks,
        "readiness": readiness,
        "launch_checklist": launch,
        "exchange_health": exchange_health,
        "next_steps": _next_steps(
            live_config,
            credential_failures,
            readiness,
            launch,
            exchange_health,
            checks,
        ),
    }


def _live_config(config: RuntimeConfig) -> RuntimeConfig:
    return config.model_copy(
        update={
            "mode": "live",
            "use_testnet": False,
            "market_data_source": "exchange",
        }
    )


def _credential_check(failures: list[str], presence: dict[str, bool]) -> dict[str, Any]:
    return {
        "name": "credentials",
        "status": "pass" if not failures else "fail",
        "message": "exchange credential fields are present" if not failures else "exchange credential fields are missing",
        "details": {
            "failures": failures,
            "present": presence,
        },
    }


def _readiness_check(readiness: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in readiness.get("checks", []) if check.get("status") != "pass"]
    return {
        "name": "readiness",
        "status": "pass" if readiness.get("status") == "pass" else "fail",
        "message": "live readiness passes" if readiness.get("status") == "pass" else "live readiness has blocking checks",
        "details": {"failed_checks": failed},
    }


def _launch_check(launch: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in launch.get("checks", []) if check.get("status") != "pass"]
    expected_phase = "ready_for_bounded_live_loop"
    phase = launch.get("phase")
    failures = [] if launch.get("status") == "pass" and phase == expected_phase else ["live_launch_checklist_blocked"]
    return {
        "name": "launch_checklist",
        "status": "pass" if not failures else "fail",
        "message": "live launch checklist passes" if not failures else "live launch checklist is blocked",
        "details": {
            "failed_checks": failed,
            "failures": failures,
            "phase": phase,
            "reason": launch.get("reason"),
            "expected_phase": expected_phase,
        },
    }


def _exchange_health_check(exchange_health: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in exchange_health.get("checks", []) if check.get("status") != "pass"]
    return {
        "name": "exchange_health",
        "status": "pass" if exchange_health.get("status") == "pass" else "fail",
        "message": "production exchange endpoints are reachable" if exchange_health.get("status") == "pass" else "production exchange endpoints are not reachable",
        "details": {"failed_checks": failed},
    }


def _endpoint_safety_check(config: RuntimeConfig, exchange_health: dict[str, Any]) -> dict[str, Any]:
    endpoint = _trading_endpoint(exchange_health)
    failures: list[str] = []
    if config.use_testnet:
        failures.append("live_endpoint_points_to_testnet")
    if config.exchange == "binance" and endpoint and "testnet.binance" in endpoint:
        failures.append("live_trading_endpoint_is_testnet")
    if config.exchange == "binance" and endpoint and "api.binance.com" not in endpoint:
        failures.append("unexpected_binance_live_trading_endpoint")
    return {
        "name": "endpoint_safety",
        "status": "pass" if not failures else "fail",
        "message": "live trading endpoint is production" if not failures else "live trading endpoint is unsafe",
        "details": {
            "failures": failures,
            "trading_endpoint": endpoint,
            "use_testnet": config.use_testnet,
        },
    }


def _risk_limit_check(config: RuntimeConfig) -> dict[str, Any]:
    failures: list[str] = []
    if config.max_live_order_usdt > LIVE_CANARY_MAX_ORDER_USDT:
        failures.append("max_live_order_exceeds_canary_limit")
    return {
        "name": "live_canary_risk_limit",
        "status": "pass" if not failures else "fail",
        "message": "live canary order limit is bounded" if not failures else "live canary order limit is too high",
        "details": {
            "failures": failures,
            "max_live_order_usdt": config.max_live_order_usdt,
            "max_live_canary_order_usdt": LIVE_CANARY_MAX_ORDER_USDT,
        },
    }


def _no_order_submission_check() -> dict[str, Any]:
    return {
        "name": "no_order_submission",
        "status": "pass",
        "message": "live setup check is read-only and does not submit orders",
        "details": {
            "will_submit_orders": False,
            "forbidden_commands": ["trade-loop", "test-order", "promote-profile-to-live"],
        },
    }


def _trading_endpoint(exchange_health: dict[str, Any]) -> str | None:
    for check in exchange_health.get("checks", []):
        if check.get("name") == "trading_endpoint":
            endpoint = check.get("details", {}).get("endpoint")
            return str(endpoint) if endpoint else None
    return None


def _next_steps(
    config: RuntimeConfig,
    credential_failures: list[str],
    readiness: dict[str, Any],
    launch: dict[str, Any],
    exchange_health: dict[str, Any],
    checks: list[dict[str, Any]],
) -> list[str]:
    steps: list[str] = []
    if credential_failures:
        steps.append("put production exchange API credentials in .env; do not reuse testnet keys")
    if not config.live_credentials_confirmed:
        steps.append("verify production API key permissions, disable withdrawal, add IP allowlist when possible, then set KXIAN_LIVE_CREDENTIALS_CONFIRMED=true")
    if readiness.get("status") != "pass":
        steps.extend(readiness.get("next_steps", []))
    if launch.get("status") != "pass":
        steps.extend(launch.get("next_steps", []))
    if exchange_health.get("status") != "pass":
        steps.extend(exchange_health.get("next_steps", []))
    if any(check["name"] == "endpoint_safety" and check["status"] != "pass" for check in checks):
        steps.append("confirm KXIAN_USE_TESTNET=false and the live trading endpoint is production before any live canary")
    if any(check["name"] == "live_canary_risk_limit" and check["status"] != "pass" for check in checks):
        steps.append(f"set KXIAN_MAX_LIVE_ORDER_USDT<={LIVE_CANARY_MAX_ORDER_USDT:g} for the first live canary")
    if not steps:
        steps.append("ask the operator for explicit approval, then run exactly one bounded live canary with kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0")
        steps.append("after the canary, run order-status if needed, sync-fills, account-balance, and launch-checklist --target live before any longer loop")
    return _dedupe(steps)


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output

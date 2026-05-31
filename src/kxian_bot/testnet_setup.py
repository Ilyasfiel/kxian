from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig
from kxian_bot.exchange_health import run_exchange_health_check
from kxian_bot.launch_checklist import run_launch_checklist
from kxian_bot.readiness import run_readiness
from kxian_bot.testnet_dry_run import exchange_credential_status


def run_testnet_setup_check(config: RuntimeConfig, timeout_seconds: float = 5.0) -> dict[str, Any]:
    testnet_config = config.model_copy(update={"mode": "testnet", "use_testnet": True, "market_data_source": "exchange"})
    credential_failures, credential_presence = exchange_credential_status(testnet_config)
    readiness = run_readiness(testnet_config)
    launch = run_launch_checklist(testnet_config, target_mode="testnet")
    exchange_health = run_exchange_health_check(testnet_config, timeout_seconds=timeout_seconds)
    checks = [
        _credential_check(credential_failures, credential_presence),
        _automation_check(testnet_config),
        _exchange_health_check(exchange_health),
        _readiness_check(readiness),
        _launch_check(launch),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "mode": "testnet",
        "exchange": testnet_config.exchange,
        "symbol": testnet_config.symbol,
        "interval": testnet_config.interval,
        "checks": checks,
        "credentials": {
            "required": True,
            "present": credential_presence,
            "failures": credential_failures,
        },
        "exchange_health": exchange_health,
        "readiness_summary": _summary(readiness),
        "launch_summary": _summary(launch),
        "next_steps": _next_steps(testnet_config, credential_failures, readiness, launch, exchange_health),
    }


def _credential_check(failures: list[str], presence: dict[str, bool]) -> dict[str, Any]:
    return {
        "name": "credentials",
        "status": "pass" if not failures else "fail",
        "message": "sandbox credentials are present" if not failures else "sandbox credentials are missing",
        "details": {
            "failures": failures,
            "present": presence,
        },
    }


def _automation_check(config: RuntimeConfig) -> dict[str, Any]:
    failures = [] if config.enable_testnet_autotrade else ["testnet_autotrade_disabled"]
    return {
        "name": "testnet_autotrade",
        "status": "pass" if not failures else "fail",
        "message": "testnet autotrade is enabled" if not failures else "testnet autotrade is disabled",
        "details": {"failures": failures, "enable_testnet_autotrade": config.enable_testnet_autotrade},
    }


def _exchange_health_check(exchange_health: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in exchange_health.get("checks", []) if check.get("status") != "pass"]
    return {
        "name": "exchange_health",
        "status": "pass" if exchange_health.get("status") == "pass" else "fail",
        "message": "exchange endpoints are reachable" if exchange_health.get("status") == "pass" else "exchange endpoints are not reachable",
        "details": {"failed_checks": failed},
    }


def _readiness_check(readiness: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in readiness.get("checks", []) if check.get("status") != "pass"]
    return {
        "name": "readiness",
        "status": "pass" if readiness.get("status") == "pass" else "fail",
        "message": "readiness passes" if readiness.get("status") == "pass" else "readiness has blocking checks",
        "details": {"failed_checks": failed},
    }


def _launch_check(launch: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in launch.get("checks", []) if check.get("status") != "pass"]
    return {
        "name": "launch_checklist",
        "status": "pass" if launch.get("status") == "pass" else "fail",
        "message": "testnet launch checklist passes" if launch.get("status") == "pass" else "testnet launch checklist is blocked",
        "details": {
            "failed_checks": failed,
            "phase": launch.get("phase"),
            "reason": launch.get("reason"),
        },
    }


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "phase": payload.get("phase"),
        "next_steps": payload.get("next_steps", []),
    }


def _next_steps(
    config: RuntimeConfig,
    credential_failures: list[str],
    readiness: dict[str, Any],
    launch: dict[str, Any],
    exchange_health: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    if credential_failures:
        if config.exchange == "binance":
            steps.append("put Binance Spot Testnet KXIAN_BINANCE_API_KEY and KXIAN_BINANCE_API_SECRET in .env")
        else:
            steps.append("put OKX demo API key, secret, and passphrase in .env")
    steps.extend(exchange_health.get("next_steps", []))
    if not config.enable_testnet_autotrade:
        steps.append("set KXIAN_ENABLE_TESTNET_AUTOTRADE=true only after credentials and exchange-health pass")
    if readiness.get("status") != "pass":
        steps.extend(readiness.get("next_steps", []))
    if launch.get("status") == "pass":
        steps.append("run kxian-bot testnet-dry-run before any longer testnet loop")
    else:
        steps.extend(launch.get("next_steps", []))
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

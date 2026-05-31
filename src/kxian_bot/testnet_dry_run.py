from __future__ import annotations

import time
import uuid
from typing import Any

from kxian_bot.brokers.base import create_broker
from kxian_bot.config import RuntimeConfig
from kxian_bot.models import LoopEvent
from kxian_bot.preflight import run_preflight
from kxian_bot.runner import TradingRunner
from kxian_bot.storage import SQLiteStorage


def run_testnet_dry_run(
    config: RuntimeConfig,
    sync_limit: int,
    execute_loop: bool,
    sleep_seconds: float,
) -> dict[str, Any]:
    if config.mode != "testnet":
        return {"status": "fail", "reason": "testnet_mode_required", "mode": config.mode}
    credential_failures, credential_presence = exchange_credential_status(config)
    if credential_failures:
        return {
            "status": "fail",
            "reason": "missing_exchange_credentials",
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "credentials": {
                "required": True,
                "failures": credential_failures,
                "present": credential_presence,
            },
            "next_steps": [
                "set sandbox API credentials for the selected exchange",
                "run kxian-bot readiness",
                "run kxian-bot testnet-dry-run",
            ],
        }
    first_preflight = run_preflight(config)
    if first_preflight["status"] != "pass":
        return {"status": "fail", "reason": "preflight_failed", "preflight": first_preflight}

    broker = create_broker(config)
    account = broker.account_balance(config.symbol)
    account_payload = account if isinstance(account, dict) else account.model_dump()
    if account_payload.get("status") != "synced":
        return {
            "status": "fail",
            "reason": account_payload.get("reason") or "account_sync_failed",
            "preflight": first_preflight,
            "account": account_payload,
        }

    runner = TradingRunner(config)
    sync = runner.sync_exchange_fills(limit=sync_limit)
    if sync.get("status") not in {"synced", "idle"}:
        return {
            "status": "fail",
            "reason": sync.get("reason") or "fill_sync_failed",
            "preflight": first_preflight,
            "account": account_payload,
            "fill_sync": sync,
        }

    second_preflight = run_preflight(config)
    if second_preflight["status"] != "pass":
        return {
            "status": "fail",
            "reason": "preflight_failed_after_sync",
            "preflight": second_preflight,
            "account": account_payload,
            "fill_sync": sync,
        }

    loop_result = None
    if execute_loop:
        loop_result = runner.run_loop(max_iterations=1, sleep_seconds=sleep_seconds)
        last = loop_result.get("last_result", {})
        if last.get("status") in {"error", "rejected"}:
            return {
                "status": "fail",
                "reason": last.get("reason") or last.get("status"),
                "preflight": second_preflight,
                "account": account_payload,
                "fill_sync": sync,
                "loop": loop_result,
            }

    return {
        "status": "pass",
        "mode": config.mode,
        "symbol": config.symbol,
        "preflight": second_preflight,
        "account": account_payload,
        "fill_sync": sync,
        "loop": loop_result,
    }


def run_testnet_observation(
    config: RuntimeConfig,
    cycles: int,
    sync_limit: int,
    execute_loop: bool,
    sleep_seconds: float,
    continue_on_failure: bool = False,
) -> dict[str, Any]:
    bounded_cycles = _bounded_int(cycles, default=3, minimum=1, maximum=1000)
    bounded_sync_limit = _bounded_int(sync_limit, default=500, minimum=1, maximum=1000)
    bounded_sleep_seconds = _bounded_float(sleep_seconds, default=0.0, minimum=0.0, maximum=3600.0)
    results: list[dict[str, Any]] = []
    failures = 0
    stopped_early = False
    observation_id = str(uuid.uuid4())
    storage = SQLiteStorage(config.db_path)

    for cycle in range(1, bounded_cycles + 1):
        started_at = time.time()
        result = run_testnet_dry_run(
            config,
            sync_limit=bounded_sync_limit,
            execute_loop=execute_loop,
            sleep_seconds=0.0 if execute_loop else bounded_sleep_seconds,
        )
        duration_seconds = round(time.time() - started_at, 4)
        if result.get("status") != "pass":
            failures += 1
        cycle_result = {
            "cycle": cycle,
            "status": result.get("status", "unknown"),
            "reason": result.get("reason", ""),
            "duration_seconds": duration_seconds,
            "execute_loop": execute_loop,
            "result": result,
        }
        results.append(cycle_result)
        _record_observation_event(storage, config, observation_id, cycle_result)
        if result.get("status") != "pass" and not continue_on_failure:
            stopped_early = cycle < bounded_cycles
            break
        if cycle < bounded_cycles:
            time.sleep(bounded_sleep_seconds)

    return {
        "status": "pass" if failures == 0 and len(results) == bounded_cycles else "fail",
        "mode": config.mode,
        "observation_id": observation_id,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "cycles_requested": bounded_cycles,
        "cycles_completed": len(results),
        "failures": failures,
        "stopped_early": stopped_early,
        "execute_loop": execute_loop,
        "continue_on_failure": continue_on_failure,
        "sync_limit": bounded_sync_limit,
        "sleep_seconds": bounded_sleep_seconds,
        "results": results,
    }


def _record_observation_event(
    storage: SQLiteStorage,
    config: RuntimeConfig,
    observation_id: str,
    cycle_result: dict[str, Any],
) -> None:
    status = "idle" if cycle_result.get("status") == "pass" else "error"
    reason = str(cycle_result.get("reason") or cycle_result.get("status") or "")
    message = "testnet_observe_passed" if status == "idle" else f"testnet_observe_failed:{reason}"
    storage.record_loop_event(
        LoopEvent(
            loop_id=f"observe-{observation_id}",
            iteration=int(cycle_result.get("cycle") or 0),
            status=status,
            mode=config.mode,
            exchange=config.exchange,
            symbol=config.symbol,
            interval=config.interval,
            message=message,
            payload={
                "kind": "testnet_observe",
                "observation_id": observation_id,
                "cycle": cycle_result.get("cycle"),
                "status": cycle_result.get("status"),
                "reason": reason,
                "duration_seconds": cycle_result.get("duration_seconds"),
                "execute_loop": bool(cycle_result.get("execute_loop", False)),
            },
        )
    )


def exchange_credential_status(config: RuntimeConfig) -> tuple[list[str], dict[str, bool]]:
    presence = {
        "binance_api_key": bool(config.binance_api_key),
        "binance_api_secret": bool(config.binance_api_secret),
        "okx_api_key": bool(config.okx_api_key),
        "okx_api_secret": bool(config.okx_api_secret),
        "okx_api_passphrase": bool(config.okx_api_passphrase),
    }
    failures: list[str] = []
    if config.exchange == "binance":
        if not presence["binance_api_key"]:
            failures.append("missing_binance_api_key")
        if not presence["binance_api_secret"]:
            failures.append("missing_binance_api_secret")
    else:
        if not presence["okx_api_key"]:
            failures.append("missing_okx_api_key")
        if not presence["okx_api_secret"]:
            failures.append("missing_okx_api_secret")
        if not presence["okx_api_passphrase"]:
            failures.append("missing_okx_api_passphrase")
    return failures, presence


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))

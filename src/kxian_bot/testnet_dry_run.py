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
from kxian_bot.testnet_scope import testnet_closed_loop_next_steps, testnet_closed_loop_scope_failures


FINAL_ORDER_STATUSES = {"filled", "canceled"}
SAFE_REJECTION_REASONS = {
    "no_signal",
    "no_new_candle",
    "position_already_open",
    "no_size",
    "cooldown_active",
    "daily_trade_limit",
    "daily_loss_limit",
}


def run_testnet_dry_run(
    config: RuntimeConfig,
    sync_limit: int,
    execute_loop: bool,
    sleep_seconds: float,
) -> dict[str, Any]:
    storage = SQLiteStorage(config.db_path)
    config_summary = _config_summary(config)
    profile_summary = _profile_summary(storage, config)
    credential_failures, credential_presence = exchange_credential_status(config)
    scope_failures = testnet_closed_loop_scope_failures(config, require_autotrade=execute_loop)
    if scope_failures:
        return {
            "status": "fail",
            "reason": scope_failures[0],
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "interval": config.interval,
            "config": config_summary,
            "profile": profile_summary,
            "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
            "scope": {"required": True, "failures": scope_failures},
            "next_steps": testnet_closed_loop_next_steps(scope_failures),
        }
    if credential_failures:
        return {
            "status": "fail",
            "reason": "missing_exchange_credentials",
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "config": config_summary,
            "profile": profile_summary,
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
    first_preflight = run_preflight(config, require_testnet_autotrade=execute_loop)
    if first_preflight["status"] != "pass":
        return {
            "status": "fail",
            "reason": "preflight_failed",
            "config": config_summary,
            "profile": profile_summary,
            "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
            "preflight": first_preflight,
        }

    broker = create_broker(config)
    account = broker.account_balance(config.symbol)
    account_payload = account if isinstance(account, dict) else account.model_dump()
    if account_payload.get("status") != "synced":
        return {
            "status": "fail",
            "reason": account_payload.get("reason") or "account_sync_failed",
            "config": config_summary,
            "profile": profile_summary,
            "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
            "preflight": first_preflight,
            "account": account_payload,
        }

    runner = TradingRunner(config)
    sync = runner.sync_exchange_fills(limit=sync_limit)
    if sync.get("status") not in {"synced", "idle"}:
        return {
            "status": "fail",
            "reason": sync.get("reason") or "fill_sync_failed",
            "config": config_summary,
            "profile": profile_summary,
            "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
            "preflight": first_preflight,
            "account": account_payload,
            "fill_sync": sync,
        }

    second_preflight = run_preflight(config, require_testnet_autotrade=execute_loop)
    if second_preflight["status"] != "pass":
        return {
            "status": "fail",
            "reason": "preflight_failed_after_sync",
            "config": config_summary,
            "profile": profile_summary,
            "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
            "preflight": second_preflight,
            "account": account_payload,
            "fill_sync": sync,
        }

    loop_result = None
    order_lifecycle = _order_lifecycle_summary(storage, config, loop_result, since_created_at=None)
    if execute_loop:
        order_baseline_time = time.time()
        loop_result = runner.run_loop(max_iterations=1, sleep_seconds=sleep_seconds)
        last = loop_result.get("last_result", {})
        order_lifecycle = _order_lifecycle_summary(storage, config, loop_result, since_created_at=order_baseline_time)
        if last.get("status") == "error":
            return {
                "status": "fail",
                "reason": last.get("reason") or last.get("status"),
                "config": config_summary,
                "profile": profile_summary,
                "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
                "preflight": second_preflight,
                "account": account_payload,
                "fill_sync": sync,
                "loop": loop_result,
                "order_lifecycle": order_lifecycle,
                "next_steps": _order_cleanup_next_steps(order_lifecycle),
            }
        if not order_lifecycle["acceptable"]:
            return {
                "status": "fail",
                "reason": (
                    "open_testnet_order_requires_cleanup"
                    if order_lifecycle["state"] == "open_orders"
                    else "testnet_order_lifecycle_not_acceptable"
                ),
                "config": config_summary,
                "profile": profile_summary,
                "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
                "preflight": second_preflight,
                "account": account_payload,
                "fill_sync": sync,
                "loop": loop_result,
                "order_lifecycle": order_lifecycle,
                "next_steps": _order_cleanup_next_steps(order_lifecycle),
            }

    return {
        "status": "pass",
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "config": config_summary,
        "profile": profile_summary,
        "credentials": {"required": True, "failures": credential_failures, "present": credential_presence},
        "preflight": second_preflight,
        "account": account_payload,
        "fill_sync": sync,
        "loop": loop_result,
        "order_lifecycle": order_lifecycle,
    }


def run_testnet_observation(
    config: RuntimeConfig,
    cycles: int,
    sync_limit: int,
    execute_loop: bool,
    sleep_seconds: float,
    continue_on_failure: bool = False,
) -> dict[str, Any]:
    bounded_cycles = _bounded_int(cycles, default=6, minimum=1, maximum=1000)
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
        "order_lifecycle": _latest_order_lifecycle(results),
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
                "order_lifecycle": cycle_result.get("result", {}).get("order_lifecycle"),
            },
        )
    )


def _latest_order_lifecycle(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for cycle_result in reversed(results):
        result = cycle_result.get("result")
        if isinstance(result, dict) and isinstance(result.get("order_lifecycle"), dict):
            return result["order_lifecycle"]
    return None


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


def _config_summary(config: RuntimeConfig) -> dict[str, Any]:
    return {
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "market_data_source": config.market_data_source,
        "use_testnet": config.use_testnet,
        "enable_testnet_autotrade": config.enable_testnet_autotrade,
        "enable_live_autotrade": config.enable_live_autotrade,
        "allow_live": config.allow_live,
        "live_dry_run": config.live_dry_run,
        "require_strategy_gate": config.require_strategy_gate,
        "require_sample_validation_gate": config.require_sample_validation_gate,
        "require_stress_gate": config.require_stress_gate,
        "require_walk_forward_gate": config.require_walk_forward_gate,
        "strategy": config.strategy,
        "short_window": config.short_window,
        "long_window": config.long_window,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "trailing_stop_pct": config.trailing_stop_pct,
        "cooldown_seconds": config.cooldown_seconds,
    }


def _profile_summary(storage: SQLiteStorage, config: RuntimeConfig) -> dict[str, Any]:
    profile = storage.active_strategy_profile(config.mode, config.exchange, config.symbol, config.interval)
    if profile is None:
        return {
            "status": "missing",
            "profile_key": f"{config.mode}:{config.exchange}:{config.symbol}:{config.interval}",
        }
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    gates = evidence.get("gates", {}) if isinstance(evidence.get("gates"), dict) else {}
    validation_run_ids: dict[str, str] = {}
    for name in ("strategy_gate", "stress_gate", "walk_forward_gate"):
        gate = gates.get(name)
        if isinstance(gate, dict) and gate.get("run_id"):
            validation_run_ids[name] = str(gate["run_id"])
    sample_validation = evidence.get("sample_validation")
    return {
        "status": "active",
        "profile_key": profile.get("profile_key"),
        "updated_by": profile.get("updated_by"),
        "strategy": profile.get("strategy"),
        "parameters": profile.get("parameters", {}),
        "sample_validation": {
            "status": sample_validation.get("status") if isinstance(sample_validation, dict) else None,
            "sample_count": sample_validation.get("sample_count") if isinstance(sample_validation, dict) else None,
        },
        "validation_run_ids": validation_run_ids,
    }


def _order_lifecycle_summary(
    storage: SQLiteStorage,
    config: RuntimeConfig,
    loop_result: dict[str, Any] | None,
    since_created_at: float | None,
) -> dict[str, Any]:
    open_orders = storage.list_open_exchange_orders(config.mode, config.exchange, config.symbol)
    all_rows = [
        dict(row)
        for row in storage.fetch_all("exchange_orders")
        if row["mode"] == config.mode and row["exchange"] == config.exchange and row["symbol"] == config.symbol
    ]
    last_result = (loop_result or {}).get("last_result", {}) if isinstance(loop_result, dict) else {}
    result_order_id = str(last_result.get("exchange_order_id") or "")
    rows = [
        row
        for row in all_rows
        if (since_created_at is None or float(row.get("created_at") or 0) >= since_created_at)
        or (result_order_id and str(row.get("exchange_order_id") or "") == result_order_id)
    ]
    rows.sort(key=lambda row: (float(row.get("created_at") or 0), int(row.get("id") or 0)))
    latest = rows[-1] if rows else None
    last_status = str(last_result.get("status") or "")
    last_reason = str(last_result.get("reason") or "")
    if open_orders:
        state = "open_orders"
        acceptable = False
    elif latest and latest.get("status") in FINAL_ORDER_STATUSES:
        state = str(latest.get("status"))
        acceptable = True
    elif latest and latest.get("status") == "rejected":
        state = "safe_rejected" if latest.get("reason") in SAFE_REJECTION_REASONS else "rejected"
        acceptable = latest.get("reason") in SAFE_REJECTION_REASONS
    elif last_status == "idle":
        state = "healthy_idle"
        acceptable = True
    elif last_status == "rejected":
        state = "safe_rejected" if last_reason in SAFE_REJECTION_REASONS else "rejected"
        acceptable = last_reason in SAFE_REJECTION_REASONS
    elif latest:
        state = str(latest.get("status") or "unknown")
        acceptable = False
    elif last_status:
        state = "unverified_order_result"
        acceptable = False
    else:
        state = "not_attempted" if loop_result is None else "unverified_loop_result"
        acceptable = loop_result is None
    return {
        "state": state,
        "acceptable": acceptable,
        "open_order_count": len(open_orders),
        "open_orders": open_orders,
        "latest_order": _public_order(latest),
        "last_loop_result": {
            "status": last_result.get("status"),
            "reason": last_result.get("reason", ""),
            "exchange_order_id": last_result.get("exchange_order_id", ""),
        },
    }


def _public_order(order: dict[str, Any] | None) -> dict[str, Any] | None:
    if not order:
        return None
    return {
        "created_at": order.get("created_at"),
        "mode": order.get("mode"),
        "exchange": order.get("exchange"),
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "quantity": order.get("quantity"),
        "price": order.get("price"),
        "status": order.get("status"),
        "exchange_order_id": order.get("exchange_order_id") or "",
        "reason": order.get("reason") or "",
    }


def _order_cleanup_next_steps(order_lifecycle: dict[str, Any]) -> list[str]:
    steps = []
    for order in order_lifecycle.get("open_orders", []):
        order_id = str(order.get("exchange_order_id") or "")
        if order_id:
            steps.append(f"run kxian-bot order-status --order-id {order_id}")
            steps.append(f"run kxian-bot cancel-order --order-id {order_id} if the sandbox order is still open")
    steps.extend(
        [
            "run kxian-bot sync-fills",
            "run kxian-bot preflight before resuming bounded testnet observation",
        ]
    )
    return steps


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

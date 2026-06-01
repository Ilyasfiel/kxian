from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.market_data import MarketDataError, latest_contiguous_candles
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategy_profile import apply_active_strategy_profile
from kxian_bot.strategy_parameters import strategy_parameters


REQUIRED_TABLES = {
    "exchange_orders",
    "strategy_signals",
    "fills",
    "backtest_trades",
    "trading_rules",
    "automation_controls",
    "strategy_profiles",
    "position_runtime_state",
    "risk_state",
    "candles",
    "backtest_runs",
    "stress_backtest_runs",
    "walk_forward_runs",
    "loop_events",
    "loop_locks",
}


def run_preflight(
    config: RuntimeConfig,
    storage: SQLiteStorage | None = None,
    require_testnet_autotrade: bool = True,
) -> dict[str, Any]:
    storage = storage or SQLiteStorage(config.db_path)
    config = apply_active_strategy_profile(config, storage)
    checks = [
        _schema_check(storage),
        _automation_control_check(config, storage),
        _trading_rule_check(config, storage),
        _market_data_check(config, storage),
        _position_state_check(config, storage),
        _strategy_gate_check(config, storage),
        _sample_validation_gate_check(config, storage),
        _stress_gate_check(config, storage),
        _walk_forward_gate_check(config, storage),
        _open_orders_check(config, storage),
        _loop_lock_check(config, storage),
        _execution_mode_check(config, require_testnet_autotrade=require_testnet_autotrade),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "checks": checks,
    }


def _schema_check(storage: SQLiteStorage) -> dict[str, Any]:
    tables = storage.table_names()
    missing = sorted(REQUIRED_TABLES - tables)
    return {
        "name": "sqlite_schema",
        "status": "pass" if not missing else "fail",
        "message": "required tables are present" if not missing else "missing required tables",
        "details": {"missing_tables": missing},
    }


def _automation_control_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    control = storage.automation_control_status(config.mode, config.exchange, config.symbol, config.interval)
    paused = bool(control.get("paused"))
    return {
        "name": "automation_control",
        "status": "fail" if paused else "pass",
        "message": "automation is paused" if paused else "automation control is active",
        "details": {
            "paused": paused,
            "reason": control.get("reason", ""),
            "updated_by": control.get("updated_by", ""),
            "updated_at": control.get("updated_at"),
            "source": control.get("source"),
        },
    }


def _market_data_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    candles = storage.load_candles(config.exchange, config.symbol, config.interval)
    required = config.long_window + 5
    local_coverage = _local_candle_coverage(candles, config.interval)
    count = int(local_coverage["local_coverage_candles"])
    if config.market_data_source == "exchange":
        return {
            "name": "market_data",
            "status": "pass",
            "message": "exchange market data will be fetched at runtime",
            "details": {
                **local_coverage,
                "required_for_sqlite_replay": required,
                "source": config.market_data_source,
            },
        }
    return {
        "name": "market_data",
        "status": "pass" if count >= required else "fail",
        "message": "enough local candles for strategy window" if count >= required else "not enough local candles",
        "details": {
            **local_coverage,
            "candles": count,
            "required": required,
            "source": config.market_data_source,
        },
    }


def _local_candle_coverage(candles: list[Any], interval: str) -> dict[str, Any]:
    if not candles:
        return {
            "local_candles": 0,
            "local_coverage_candles": 0,
            "local_outlier_candles": 0,
            "local_first_open_time": None,
            "local_last_open_time": None,
            "local_coverage_days": 0.0,
        }
    try:
        covered = latest_contiguous_candles(candles, interval)
    except MarketDataError:
        covered = candles[-1:]
    first_open = covered[0].open_time
    last_open = covered[-1].open_time
    last_close = covered[-1].close_time or last_open
    coverage_ms = max(0, last_close - first_open)
    return {
        "local_candles": len(candles),
        "local_coverage_candles": len(covered),
        "local_outlier_candles": len(candles) - len(covered),
        "local_first_open_time": first_open,
        "local_last_open_time": last_open,
        "local_coverage_days": round(coverage_ms / 86_400_000, 4),
    }
def _trading_rule_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    rule = storage.latest_trading_rule(config.exchange, config.symbol)
    if rule is None:
        return {
            "name": "trading_rules",
            "status": "pass",
            "message": "default trading rules will be used",
            "details": {
                "source": "config",
                "price_step": config.price_step,
                "quantity_step": config.quantity_step,
                "min_quantity": config.min_exchange_quantity,
                "min_notional": config.min_exchange_notional,
            },
        }
    failures: list[str] = []
    if float(rule["price_step"] or 0) <= 0:
        failures.append("invalid_price_step")
    if float(rule["quantity_step"] or 0) <= 0:
        failures.append("invalid_quantity_step")
    if float(rule["min_quantity"] or 0) < 0:
        failures.append("invalid_min_quantity")
    if float(rule["min_notional"] or 0) < 0:
        failures.append("invalid_min_notional")
    return {
        "name": "trading_rules",
        "status": "pass" if not failures else "fail",
        "message": "trading rules are ready" if not failures else "trading rules are invalid",
        "details": {
            "source": "sqlite",
            "failures": failures,
            "price_step": rule["price_step"],
            "quantity_step": rule["quantity_step"],
            "min_quantity": rule["min_quantity"],
            "min_notional": rule["min_notional"],
        },
    }


def _strategy_gate_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    if not _requires_evidence_gates(config):
        return {
            "name": "strategy_gate",
            "status": "pass",
            "message": "strategy gate is not required for this mode",
            "details": {"required": False},
        }
    if not config.require_strategy_gate:
        return {
            "name": "strategy_gate",
            "status": "pass",
            "message": "strategy gate disabled for controlled smoke test",
            "details": {"required": False},
        }

    parameters = _strategy_parameters(config)
    run = storage.latest_backtest_run(
        config.exchange,
        config.symbol,
        config.interval,
        config.short_window,
        config.long_window,
        parameters=parameters,
        strategy=config.strategy,
    )
    if run is None:
        return {
            "name": "strategy_gate",
            "status": "fail",
            "message": "missing matching backtest run",
            "details": {
                "required": True,
                "strategy": config.strategy,
                "short_window": config.short_window,
                "long_window": config.long_window,
                "parameters": parameters,
            },
        }

    metrics = run.get("metrics", {})
    trade_count = int(_metric(metrics, "trade_count", 0))
    return_pct = _metric(metrics, "return_pct", 0)
    drawdown_pct = abs(_metric(metrics, "max_drawdown_pct", 0))
    profit_factor = _metric(metrics, "profit_factor", 0)
    failures: list[str] = []
    if trade_count < config.min_gate_trades:
        failures.append("insufficient_trades")
    if return_pct < config.min_gate_return_pct:
        failures.append("return_too_low")
    if drawdown_pct > config.max_gate_drawdown_pct:
        failures.append("drawdown_too_high")
    if profit_factor < config.min_gate_profit_factor:
        failures.append("profit_factor_too_low")

    return {
        "name": "strategy_gate",
        "status": "pass" if not failures else "fail",
        "message": "matching backtest passes gate" if not failures else "matching backtest fails gate",
        "details": {
            "required": True,
            "run_id": run["run_id"],
            "failures": failures,
            "parameters": parameters,
            "metrics": {
                "trade_count": trade_count,
                "return_pct": return_pct,
                "max_drawdown_pct": drawdown_pct,
                "profit_factor": profit_factor,
            },
            "thresholds": {
                "min_gate_trades": config.min_gate_trades,
                "min_gate_return_pct": config.min_gate_return_pct,
                "max_gate_drawdown_pct": config.max_gate_drawdown_pct,
                "min_gate_profit_factor": config.min_gate_profit_factor,
            },
        },
    }


def _sample_validation_gate_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    if not _requires_evidence_gates(config):
        return {
            "name": "sample_validation_gate",
            "status": "pass",
            "message": "sample validation gate is not required for this mode",
            "details": {"required": False},
        }
    if not config.require_sample_validation_gate:
        return {
            "name": "sample_validation_gate",
            "status": "pass",
            "message": "sample validation gate disabled for controlled smoke test",
            "details": {"required": False},
        }

    profile = storage.active_strategy_profile(config.mode, config.exchange, config.symbol, config.interval)
    if profile is None:
        return {
            "name": "sample_validation_gate",
            "status": "fail",
            "message": "missing active multi-sample strategy profile",
            "details": {"required": True, "reason": "missing_active_profile"},
        }
    evidence = profile.get("evidence", {}).get("sample_validation")
    if not isinstance(evidence, dict):
        return {
            "name": "sample_validation_gate",
            "status": "fail",
            "message": "missing multi-sample validation evidence",
            "details": {
                "required": True,
                "reason": "missing_sample_validation_evidence",
                "profile_key": profile.get("profile_key"),
            },
        }

    failures: list[str] = []
    if evidence.get("status") != "pass":
        failures.append("sample_validation_not_passed")
    sample_count = int(_metric(evidence, "sample_count", 0))
    passed_samples = int(_metric(evidence, "passed_samples", 0))
    failed_samples = int(_metric(evidence, "failed_samples", 0))
    if sample_count < 1:
        failures.append("no_validation_samples")
    if failed_samples > 0 or passed_samples < sample_count:
        failures.append("not_all_samples_passed")
    summary = evidence.get("summary", {})
    if isinstance(summary, dict):
        if int(_metric(summary, "total_trade_count", 0)) < config.min_gate_trades:
            failures.append("sample_validation_insufficient_trades")
        if _metric(summary, "min_return_pct", 0) < config.min_gate_return_pct:
            failures.append("sample_validation_return_too_low")
        if _metric(summary, "min_profit_factor", 0) < config.min_gate_profit_factor:
            failures.append("sample_validation_profit_factor_too_low")
        if _metric(summary, "min_stress_pass_rate", 0) < config.min_stress_pass_rate:
            failures.append("sample_validation_stress_pass_rate_too_low")
        if _metric(summary, "min_walk_forward_pass_rate", 0) < config.min_walk_forward_pass_rate:
            failures.append("sample_validation_walk_forward_pass_rate_too_low")

    return {
        "name": "sample_validation_gate",
        "status": "pass" if not failures else "fail",
        "message": "multi-sample validation evidence passes" if not failures else "multi-sample validation evidence fails",
        "details": {
            "required": True,
            "failures": failures,
            "profile_key": profile.get("profile_key"),
            "status": evidence.get("status"),
            "sample_count": sample_count,
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "summary": summary,
            "thresholds": {
                "min_gate_trades": config.min_gate_trades,
                "min_gate_return_pct": config.min_gate_return_pct,
                "min_gate_profit_factor": config.min_gate_profit_factor,
                "min_stress_pass_rate": config.min_stress_pass_rate,
                "min_walk_forward_pass_rate": config.min_walk_forward_pass_rate,
            },
        },
    }


def _stress_gate_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    if not _requires_evidence_gates(config):
        return {
            "name": "stress_gate",
            "status": "pass",
            "message": "stress gate is not required for this mode",
            "details": {"required": False},
        }
    if not config.require_stress_gate:
        return {
            "name": "stress_gate",
            "status": "pass",
            "message": "stress gate disabled for controlled smoke test",
            "details": {"required": False},
        }

    run = storage.latest_stress_backtest_run(
        config.exchange,
        config.symbol,
        config.interval,
        config.short_window,
        config.long_window,
        parameters=_strategy_parameters(config),
        strategy=config.strategy,
    )
    if run is None:
        return {
            "name": "stress_gate",
            "status": "fail",
            "message": "missing matching stress backtest run",
            "details": {
                "required": True,
                "strategy": config.strategy,
                "short_window": config.short_window,
                "long_window": config.long_window,
            },
        }

    metrics = run.get("metrics", {})
    pass_rate = _metric(metrics, "pass_rate", 0)
    min_trade_count = int(_metric(metrics, "min_trade_count", 0))
    worst_return_pct = _metric(metrics, "worst_return_pct", 0)
    worst_drawdown_pct = abs(_metric(metrics, "worst_drawdown_pct", 0))
    worst_profit_factor = _metric(metrics, "worst_profit_factor", 0)
    failures: list[str] = []
    if pass_rate < config.min_stress_pass_rate:
        failures.append("stress_pass_rate_too_low")
    if min_trade_count < config.min_gate_trades:
        failures.append("stress_insufficient_trades")
    if worst_return_pct < config.min_gate_return_pct:
        failures.append("stress_return_too_low")
    if worst_drawdown_pct > config.max_stress_drawdown_pct:
        failures.append("stress_drawdown_too_high")
    if worst_profit_factor < config.min_gate_profit_factor:
        failures.append("stress_profit_factor_too_low")

    return {
        "name": "stress_gate",
        "status": "pass" if not failures else "fail",
        "message": "matching stress backtest passes gate" if not failures else "matching stress backtest fails gate",
        "details": {
            "required": True,
            "run_id": run["run_id"],
            "failures": failures,
            "metrics": {
                "pass_rate": pass_rate,
                "min_trade_count": min_trade_count,
                "worst_return_pct": worst_return_pct,
                "worst_drawdown_pct": worst_drawdown_pct,
                "worst_profit_factor": worst_profit_factor,
            },
            "thresholds": {
                "min_stress_pass_rate": config.min_stress_pass_rate,
                "min_gate_trades": config.min_gate_trades,
                "min_gate_return_pct": config.min_gate_return_pct,
                "max_stress_drawdown_pct": config.max_stress_drawdown_pct,
                "min_gate_profit_factor": config.min_gate_profit_factor,
            },
        },
    }


def _walk_forward_gate_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    if not _requires_evidence_gates(config):
        return {
            "name": "walk_forward_gate",
            "status": "pass",
            "message": "walk forward gate is not required for this mode",
            "details": {"required": False},
        }
    if not config.require_walk_forward_gate:
        return {
            "name": "walk_forward_gate",
            "status": "pass",
            "message": "walk forward gate disabled for controlled smoke test",
            "details": {"required": False},
        }

    run = storage.latest_walk_forward_run(
        config.exchange,
        config.symbol,
        config.interval,
        config.short_window,
        config.long_window,
        parameters=_strategy_parameters(config),
        strategy=config.strategy,
    )
    if run is None:
        return {
            "name": "walk_forward_gate",
            "status": "fail",
            "message": "missing matching walk forward run",
            "details": {
                "required": True,
                "strategy": config.strategy,
                "short_window": config.short_window,
                "long_window": config.long_window,
            },
        }

    metrics = run.get("metrics", {})
    segment_count = int(_metric(metrics, "segment_count", 0))
    pass_rate = _metric(metrics, "pass_rate", 0)
    total_trade_count = int(_metric(metrics, "total_trade_count", 0))
    worst_return_pct = _metric(metrics, "worst_return_pct", 0)
    worst_drawdown_pct = abs(_metric(metrics, "worst_drawdown_pct", 0))
    worst_profit_factor = _metric(metrics, "worst_profit_factor", 0)
    failures: list[str] = []
    if segment_count < config.min_walk_forward_segments:
        failures.append("walk_forward_insufficient_segments")
    if pass_rate < config.min_walk_forward_pass_rate:
        failures.append("walk_forward_pass_rate_too_low")
    if total_trade_count < config.min_walk_forward_trades:
        failures.append("walk_forward_insufficient_trades")
    if worst_return_pct < config.min_gate_return_pct:
        failures.append("walk_forward_return_too_low")
    if worst_drawdown_pct > config.max_gate_drawdown_pct:
        failures.append("walk_forward_drawdown_too_high")
    if worst_profit_factor < config.min_gate_profit_factor:
        failures.append("walk_forward_profit_factor_too_low")

    return {
        "name": "walk_forward_gate",
        "status": "pass" if not failures else "fail",
        "message": "matching walk forward run passes gate" if not failures else "matching walk forward run fails gate",
        "details": {
            "required": True,
            "run_id": run["run_id"],
            "failures": failures,
            "metrics": {
                "segment_count": segment_count,
                "pass_rate": pass_rate,
                "total_trade_count": total_trade_count,
                "worst_return_pct": worst_return_pct,
                "worst_drawdown_pct": worst_drawdown_pct,
                "worst_profit_factor": worst_profit_factor,
            },
            "thresholds": {
                "min_walk_forward_segments": config.min_walk_forward_segments,
                "min_walk_forward_pass_rate": config.min_walk_forward_pass_rate,
                "min_walk_forward_trades": config.min_walk_forward_trades,
                "min_gate_return_pct": config.min_gate_return_pct,
                "max_gate_drawdown_pct": config.max_gate_drawdown_pct,
                "min_gate_profit_factor": config.min_gate_profit_factor,
            },
        },
    }


def _position_state_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    balances = storage.replay_position_state(config.mode, config.exchange, config.symbol, config.starting_usdt)
    failures = []
    if balances["asset_balance"] > 0 and balances["average_entry_price"] <= 0:
        failures.append("missing_local_entry_price")
    return {
        "name": "position_state",
        "status": "pass" if not failures else "fail",
        "message": "local fill replay completed" if not failures else "local position entry price is missing",
        "details": {**balances, "failures": failures},
    }


def _open_orders_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    orders = storage.list_open_exchange_orders(config.mode, config.exchange, config.symbol)
    return {
        "name": "open_orders",
        "status": "pass" if not orders else "fail",
        "message": "no open exchange orders" if not orders else "open exchange orders must be refreshed or resolved",
        "details": {"open_order_count": len(orders), "orders": orders[:5]},
    }


def _loop_lock_check(config: RuntimeConfig, storage: SQLiteStorage) -> dict[str, Any]:
    lock = storage.active_loop_lock(
        config.mode,
        config.exchange,
        config.symbol,
        config.interval,
        config.loop_lock_stale_seconds,
    )
    return {
        "name": "loop_lock",
        "status": "pass" if lock is None else "fail",
        "message": "no active strategy loop" if lock is None else "another strategy loop is active",
        "details": {
            "active": lock is not None,
            "lock": lock,
            "stale_after_seconds": config.loop_lock_stale_seconds,
        },
    }


def _execution_mode_check(config: RuntimeConfig, *, require_testnet_autotrade: bool = True) -> dict[str, Any]:
    failures: list[str] = []
    if config.mode == "live":
        if not config.allow_live:
            failures.append("live_not_allowed")
        if config.live_dry_run:
            failures.append("live_dry_run_enabled")
        if not config.enable_live_autotrade:
            failures.append("live_autotrade_disabled")
        if config.use_testnet:
            failures.append("live_endpoint_points_to_testnet")
        if config.live_confirmation != expected_live_confirmation(config):
            failures.append("live_confirmation_required")
        if not config.live_credentials_confirmed:
            failures.append("live_credentials_not_confirmed")
        if config.exchange == "bitget" and config.max_live_order_usdt > 5:
            failures.append("bitget_live_canary_limit_exceeded")
    if config.mode == "testnet" and config.exchange == "binance" and not config.use_testnet:
        failures.append("binance_testnet_endpoint_required")
    if config.mode == "testnet" and config.exchange == "bitget":
        failures.append("bitget_testnet_not_supported")
    if config.mode == "testnet" and require_testnet_autotrade and not config.enable_testnet_autotrade:
        failures.append("testnet_autotrade_disabled")
    return {
        "name": "execution_mode",
        "status": "pass" if not failures else "fail",
        "message": "execution mode is ready" if not failures else "execution mode is not ready for automation",
        "details": {
            "failures": failures,
            "mode": config.mode,
            "use_testnet": config.use_testnet,
            "enable_testnet_autotrade": config.enable_testnet_autotrade,
            "enable_live_autotrade": config.enable_live_autotrade,
            "live_dry_run": config.live_dry_run,
            "live_confirmation_required": expected_live_confirmation(config) if config.mode == "live" else "",
            "live_credentials_confirmed": config.live_credentials_confirmed,
            "max_live_order_usdt": config.max_live_order_usdt,
            "bitget_live_canary_limit": 5 if config.exchange == "bitget" else None,
        },
    }


def _requires_evidence_gates(config: RuntimeConfig) -> bool:
    return (
        config.mode == "testnet"
        and config.enable_testnet_autotrade
        or config.mode == "live"
        and config.allow_live
        and config.enable_live_autotrade
        and not config.live_dry_run
    )


def _metric(metrics: dict, key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _strategy_parameters(config: RuntimeConfig) -> dict:
    return strategy_parameters(
        config.strategy,
        config.short_window,
        config.long_window,
        config.stop_loss_pct,
        config.take_profit_pct,
        config.trailing_stop_pct,
        config.cooldown_seconds,
    )

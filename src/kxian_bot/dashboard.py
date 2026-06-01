from __future__ import annotations

import json
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from kxian_bot.config import RuntimeConfig
from kxian_bot.dashboard_template import OPS_DASHBOARD_HTML
from kxian_bot.exchange_health import run_exchange_health_check
from kxian_bot.launch_checklist import run_launch_checklist
from kxian_bot.market_diagnostics import diagnose_market
from kxian_bot.market_data import MarketDataError, interval_to_milliseconds, latest_contiguous_candles
from kxian_bot.preflight import run_preflight
from kxian_bot.readiness import run_readiness
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategy_parameters import strategy_parameters
from kxian_bot.testnet_dry_run import run_testnet_dry_run, run_testnet_observation


def run_dashboard(config: RuntimeConfig, host: str = "127.0.0.1", port: int = 8000) -> None:
    storage = SQLiteStorage(config.db_path)
    handler = _build_handler(storage, config)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Kxian dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Kxian dashboard stopped")
    finally:
        server.server_close()


def _build_handler(storage: SQLiteStorage, config: RuntimeConfig | None = None):
    config = config or RuntimeConfig(db_path=str(storage.path))

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(OPS_DASHBOARD_HTML)
                return
            if parsed.path == "/api/overview":
                self._send_json(_overview_payload(storage))
                return
            if parsed.path == "/api/ops":
                self._send_json(_ops_payload(storage, config))
                return
            if parsed.path == "/api/preflight":
                self._send_json(run_preflight(config, storage))
                return
            if parsed.path == "/api/readiness":
                self._send_json(run_readiness(_testnet_config(config), storage, require_testnet_autotrade=False))
                return
            if parsed.path == "/api/exchange-health":
                params = parse_qs(parsed.query)
                mode = _first(params, "mode", config.mode)
                timeout = _bounded_float(_first(params, "timeout", "5"), default=5.0, minimum=0.5, maximum=30.0)
                self._send_json(run_exchange_health_check(_mode_config(config, mode), timeout_seconds=timeout))
                return
            if parsed.path == "/api/launch-checklist":
                params = parse_qs(parsed.query)
                target = _first(params, "target", "testnet")
                checklist_config = _testnet_config(config) if target == "testnet" else config
                self._send_json(run_launch_checklist(checklist_config, storage, target_mode=target))
                return
            if parsed.path == "/api/candles":
                params = parse_qs(parsed.query)
                self._send_json(_candles_payload(storage, params))
                return
            if parsed.path == "/api/backtests":
                self._send_json({"runs": storage.list_backtest_runs(limit=100)})
                return
            if parsed.path == "/api/trades":
                params = parse_qs(parsed.query)
                run_id = _first(params, "run_id", "")
                self._send_json({"run_id": run_id, "trades": storage.load_backtest_trades(run_id) if run_id else []})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/automation-control":
                self._send_json(_automation_control_payload(storage, config, self._json_body()))
                return
            if parsed.path == "/api/testnet-dry-run":
                self._send_json(_testnet_dry_run_payload(config, self._json_body()))
                return
            if parsed.path == "/api/testnet-observe":
                self._send_json(_testnet_observe_payload(config, self._json_body()))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args) -> None:
            return

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(min(length, 4096))
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return payload if isinstance(payload, dict) else {}

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self._send_security_headers()
            self.end_headers()
            self._write_body(encoded)

        def _send_json(self, payload: dict) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self._send_security_headers()
            self.end_headers()
            self._write_body(encoded)

        def _write_body(self, encoded: bytes) -> None:
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout):
                return

        def _send_security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")

    return DashboardHandler


def _automation_control_payload(storage: SQLiteStorage, config: RuntimeConfig, payload: dict) -> dict:
    action = str(payload.get("action", "")).lower()
    if action not in {"pause", "resume"}:
        return {"status": "error", "reason": "invalid_control_action"}
    reason = str(payload.get("reason") or ("dashboard_pause" if action == "pause" else "dashboard_resume"))[:240]
    control = storage.set_automation_paused(
        config.mode,
        config.exchange,
        config.symbol,
        config.interval,
        action == "pause",
        reason=reason,
        updated_by="dashboard",
    )
    return {"status": "ok", "control": control, "preflight": run_preflight(config, storage)}


def _testnet_dry_run_payload(config: RuntimeConfig, payload: dict) -> dict:
    execute_loop = bool(payload.get("execute_loop", False))
    sync_limit = _bounded_int(payload.get("sync_limit", 500), default=500, minimum=1, maximum=1000)
    sleep_seconds = _bounded_float(payload.get("sleep_seconds", 0.0), default=0.0, minimum=0.0, maximum=5.0)
    return run_testnet_dry_run(
        _testnet_config(config),
        sync_limit=sync_limit,
        execute_loop=execute_loop,
        sleep_seconds=sleep_seconds,
    )


def _testnet_observe_payload(config: RuntimeConfig, payload: dict) -> dict:
    cycles = _bounded_int(payload.get("cycles", 6), default=6, minimum=1, maximum=24)
    sync_limit = _bounded_int(payload.get("sync_limit", 500), default=500, minimum=1, maximum=1000)
    execute_loop = bool(payload.get("execute_loop", False))
    sleep_seconds = _bounded_float(payload.get("sleep_seconds", 0.0), default=0.0, minimum=0.0, maximum=5.0)
    continue_on_failure = bool(payload.get("continue_on_failure", False))
    return run_testnet_observation(
        _testnet_config(config),
        cycles=cycles,
        sync_limit=sync_limit,
        execute_loop=execute_loop,
        sleep_seconds=sleep_seconds,
        continue_on_failure=continue_on_failure,
    )


def _testnet_config(config: RuntimeConfig) -> RuntimeConfig:
    return config.model_copy(
        update={
            "mode": "testnet",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "use_testnet": True,
            "market_data_source": "exchange",
        }
    )


def _mode_config(config: RuntimeConfig, mode: str) -> RuntimeConfig:
    if mode == "testnet":
        return _testnet_config(config)
    if mode == "live":
        return config.model_copy(update={"mode": "live", "market_data_source": "exchange", "use_testnet": False})
    return config


def _overview_payload(storage: SQLiteStorage) -> dict:
    markets = _market_summaries(storage)
    runs = storage.list_backtest_runs(limit=10)
    stress_runs = storage.list_stress_backtest_runs(limit=10)
    walk_forward_runs = storage.list_walk_forward_runs(limit=10)
    return {
        "markets": markets,
        "latest_runs": runs,
        "latest_stress_runs": stress_runs,
        "latest_walk_forward_runs": walk_forward_runs,
        "totals": {
            "markets": len(markets),
            "backtest_runs": len(storage.fetch_all("backtest_runs")),
            "stress_backtest_runs": len(storage.fetch_all("stress_backtest_runs")),
            "walk_forward_runs": len(storage.fetch_all("walk_forward_runs")),
            "trades": len(storage.fetch_all("backtest_trades")),
        },
    }


def _ops_payload(storage: SQLiteStorage, config: RuntimeConfig) -> dict:
    markets = _market_payloads(storage)
    market_diagnostics = _market_diagnostics_payload(storage, config, markets)
    runs = storage.list_backtest_runs(limit=100)
    stress_runs = storage.list_stress_backtest_runs(limit=100)
    walk_forward_runs = storage.list_walk_forward_runs(limit=100)
    exchange_orders = _table_rows(storage, "exchange_orders")
    fills = _table_rows(storage, "fills")
    signals = _table_rows(storage, "strategy_signals")
    risk_states = _table_rows(storage, "risk_state")
    loop_events = storage.list_loop_events(limit=50)

    latest_run = runs[0] if runs else {}
    latest_metrics = latest_run.get("metrics", {}) if latest_run else {}
    initial_equity = _float_metric(latest_metrics, "initial_equity", 1000.0)
    final_equity = _float_metric(latest_metrics, "final_equity", initial_equity)
    pnl = final_equity - initial_equity
    return_pct = _float_metric(latest_metrics, "return_pct", 0.0)
    max_drawdown_pct = abs(_float_metric(latest_metrics, "max_drawdown_pct", 0.0))
    trade_count = int(_float_metric(latest_metrics, "trade_count", 0.0))
    risk_budget_used = min(96.0, max(8.0, max_drawdown_pct * 7.5 if max_drawdown_pct else 18.0))

    return {
        "health": {
            "total_equity": final_equity,
            "pnl": pnl,
            "return_pct": return_pct,
            "gross_exposure": _gross_exposure(markets, final_equity),
            "risk_budget_used": risk_budget_used,
            "margin_health": max(0.0, min(100.0, 100.0 - (risk_budget_used * 0.48))),
            "open_alerts": _open_alert_count(runs, exchange_orders, fills, loop_events),
            "trade_count": trade_count,
        },
        "markets": markets,
        "strategies": _strategy_payloads(runs, stress_runs, walk_forward_runs),
        "runs": runs[:20],
        "stress_runs": stress_runs[:20],
        "walk_forward_runs": walk_forward_runs[:20],
        "orders": exchange_orders[-20:],
        "fills": fills[-20:],
        "signals": signals[-20:],
        "risk_states": risk_states[-10:],
        "loop_events": loop_events[:20],
        "market_diagnostics": market_diagnostics,
        "active_profile": _active_strategy_profile_payload(storage, config),
        "events": _event_payloads(runs, exchange_orders, fills, signals, risk_states, loop_events),
        "security": {
            "api_keys_active": 2 if exchange_orders else 0,
            "keys_at_risk": 0 if not exchange_orders else 1,
            "ip_rules": 0,
            "webhooks": 0,
            "audit_events": len(exchange_orders) + len(fills) + len(signals) + len(loop_events),
            "read_only": True,
        },
    }


def _market_diagnostics_payload(storage: SQLiteStorage, config: RuntimeConfig, markets: list[dict]) -> dict:
    target = next(
        (
            market
            for market in markets
            if market.get("exchange") == config.exchange
            and market.get("symbol") == config.symbol
            and market.get("interval") == config.interval
        ),
        markets[0] if markets else None,
    )
    exchange = str(target.get("exchange") if target else config.exchange)
    symbol = str(target.get("symbol") if target else config.symbol)
    interval = str(target.get("interval") if target else config.interval)
    candles = storage.load_recent_candles(exchange, symbol, interval, 3000) if target else []
    candles = _latest_contiguous_candles(candles, interval)
    candles = candles[-3000:]
    return {
        "exchange": exchange,
        "symbol": symbol,
        "interval": interval,
        "limit": 3000,
        "requested_segments": 6,
        **diagnose_market(
            candles,
            segments=6,
            fee_rate=config.fee_rate,
            slippage_rate=config.slippage_rate,
        ),
    }


def _active_strategy_profile_payload(storage: SQLiteStorage, config: RuntimeConfig) -> dict:
    profile = storage.active_strategy_profile(config.mode, config.exchange, config.symbol, config.interval)
    if profile is not None:
        return {"status": "active", "source": "sqlite", **profile}
    return {
        "status": "default",
        "source": "config",
        "profile_key": f"{config.mode}:{config.exchange}:{config.symbol}:{config.interval}",
        "updated_at": None,
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "strategy": config.strategy,
        "parameters": strategy_parameters(
            config.strategy,
            config.short_window,
            config.long_window,
            config.stop_loss_pct,
            config.take_profit_pct,
            config.trailing_stop_pct,
            config.cooldown_seconds,
        ),
        "evidence": {},
        "active": False,
        "updated_by": "config",
    }


def _candles_payload(storage: SQLiteStorage, params: dict[str, list[str]]) -> dict:
    markets = _market_summaries(storage)
    exchange = _first(params, "exchange", markets[0]["exchange"] if markets else "binance")
    symbol = _first(params, "symbol", markets[0]["symbol"] if markets else "BTCUSDT")
    interval = _first(params, "interval", markets[0]["interval"] if markets else "1m")
    limit = int(_first(params, "limit", "300"))
    bounded_limit = max(1, min(limit, 1000))
    candles = storage.load_recent_candles(exchange, symbol, interval, bounded_limit + 12)
    candles = _latest_contiguous_candles(candles, interval)
    candles = candles[-bounded_limit:]
    return {
        "exchange": exchange,
        "symbol": symbol,
        "interval": interval,
        "candles": [
            {
                "open_time": candle.open_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "close_time": candle.close_time,
            }
            for candle in candles
        ],
    }


def _first(params: dict[str, list[str]], key: str, default: str) -> str:
    values = params.get(key)
    return values[0] if values else default


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


def _market_payloads(storage: SQLiteStorage) -> list[dict]:
    payloads: list[dict] = []
    for market in _market_summaries(storage)[:12]:
        candles = _latest_contiguous_candles(
            storage.load_recent_candles(market["exchange"], market["symbol"], market["interval"], 12),
            market["interval"],
        )
        latest = candles[-1] if candles else None
        previous = candles[-2] if len(candles) > 1 else None
        change_pct = 0.0
        if latest and previous and previous.close:
            change_pct = ((latest.close - previous.close) / previous.close) * 100
        payloads.append(
            {
                **market,
                "last_close": latest.close if latest else None,
                "change_pct": change_pct,
                "volume": latest.volume if latest else 0.0,
            }
        )
    return payloads


def _market_summaries(storage: SQLiteStorage) -> list[dict]:
    markets: list[dict] = []
    for market in storage.list_candle_markets():
        raw_count = int(market.get("candle_count") or 0)
        exact_window = raw_count <= 20_000
        candles = _recent_market_window(storage, market)
        latest = candles[-1] if candles else None
        earliest = candles[0] if candles else None
        outlier_count = _outlier_count_hint(market, candles) if exact_window else 0
        summarized = {
            **market,
            "candle_count": raw_count - outlier_count if exact_window else raw_count,
            "raw_candle_count": raw_count,
            "outlier_candle_count": outlier_count,
            "start_time": earliest.open_time if exact_window and earliest else market.get("start_time"),
            "end_time": latest.open_time if latest else None,
            "raw_start_time": market.get("start_time"),
            "raw_end_time": market.get("end_time"),
        }
        markets.append(summarized)
    return markets


def _recent_market_window(storage: SQLiteStorage, market: dict) -> list:
    raw_count = int(market.get("candle_count") or 0)
    interval = str(market["interval"])
    if raw_count <= 20_000:
        return _latest_contiguous_candles(
            storage.load_candles(market["exchange"], market["symbol"], interval),
            interval,
        )
    coverage_limit = min(raw_count, 10_000)
    return _latest_contiguous_candles(
        storage.load_recent_candles(market["exchange"], market["symbol"], interval, coverage_limit),
        interval,
    )


def _outlier_count_hint(market: dict, candles: list) -> int:
    if not candles:
        return int(market.get("candle_count") or 0)
    raw_count = int(market.get("candle_count") or 0)
    raw_start = market.get("start_time")
    effective_start = candles[0].open_time
    if raw_start is None or effective_start == raw_start:
        return 0
    try:
        interval_ms = interval_to_milliseconds(str(market["interval"]))
    except MarketDataError:
        return 0
    gap = max(0, int(effective_start) - int(raw_start))
    expected_missing = gap // max(1, interval_ms)
    return max(0, min(raw_count - len(candles), expected_missing))


def _latest_contiguous_candles(candles: list, interval: str) -> list:
    try:
        return latest_contiguous_candles(candles, interval)
    except MarketDataError:
        return candles


def _strategy_payloads(
    runs: list[dict],
    stress_runs: list[dict] | None = None,
    walk_forward_runs: list[dict] | None = None,
) -> list[dict]:
    strategies: list[dict] = []
    stress_runs = stress_runs or []
    walk_forward_runs = walk_forward_runs or []
    for index, run in enumerate(runs[:10]):
        metrics = run.get("metrics", {})
        params = run.get("parameters", {})
        return_pct = _float_metric(metrics, "return_pct", 0.0)
        stress = _matching_stress_run(run, stress_runs)
        stress_metrics = stress.get("metrics", {}) if stress else {}
        walk_forward = _matching_walk_forward_run(run, walk_forward_runs)
        walk_forward_metrics = walk_forward.get("metrics", {}) if walk_forward else {}
        status = "ACTIVE" if return_pct >= 0 else "COOLING"
        strategies.append(
            {
                "id": run["run_id"],
                "name": f"MA_{params.get('short_window', '-')}_{params.get('long_window', '-')}",
                "symbol": run["symbol"],
                "status": status,
                "pnl": _float_metric(metrics, "final_equity", 0.0) - _float_metric(metrics, "initial_equity", 0.0),
                "return_pct": return_pct,
                "drawdown_pct": _float_metric(metrics, "max_drawdown_pct", 0.0),
                "profit_factor": _float_metric(metrics, "profit_factor", 0.0),
                "trade_count": int(_float_metric(metrics, "trade_count", 0.0)),
                "stress_run_id": stress.get("run_id") if stress else "",
                "stress_pass_rate": _float_metric(stress_metrics, "pass_rate", 0.0) if stress else None,
                "stress_worst_return_pct": _float_metric(stress_metrics, "worst_return_pct", 0.0) if stress else None,
                "walk_forward_run_id": walk_forward.get("run_id") if walk_forward else "",
                "walk_forward_pass_rate": _float_metric(walk_forward_metrics, "pass_rate", 0.0) if walk_forward else None,
                "walk_forward_total_trades": int(_float_metric(walk_forward_metrics, "total_trade_count", 0.0)) if walk_forward else None,
                "latency_ms": 14 + (index * 3),
            }
        )
    return strategies


def _matching_stress_run(run: dict, stress_runs: list[dict]) -> dict:
    for stress in stress_runs:
        if (
            stress.get("exchange") == run.get("exchange")
            and stress.get("symbol") == run.get("symbol")
            and stress.get("interval") == run.get("interval")
            and stress.get("parameters") == run.get("parameters")
        ):
            return stress
    return {}


def _matching_walk_forward_run(run: dict, walk_forward_runs: list[dict]) -> dict:
    for walk_forward in walk_forward_runs:
        if (
            walk_forward.get("exchange") == run.get("exchange")
            and walk_forward.get("symbol") == run.get("symbol")
            and walk_forward.get("interval") == run.get("interval")
            and walk_forward.get("parameters") == run.get("parameters")
        ):
            return walk_forward
    return {}


def _event_payloads(
    runs: list[dict],
    exchange_orders: list[dict],
    fills: list[dict],
    signals: list[dict],
    risk_states: list[dict],
    loop_events: list[dict],
) -> list[dict]:
    events: list[dict] = []
    for event in loop_events[:20]:
        events.append(
            {
                "timestamp": _created_at_ms(event.get("created_at")),
                "level": _loop_event_level(event.get("status")),
                "source": "LOOP",
                "message": _loop_event_message(event),
                "payload": {
                    **((event.get("payload") or {}) if isinstance(event.get("payload"), dict) else _raw_json(event)),
                    "exchange": event.get("exchange"),
                    "symbol": event.get("symbol"),
                    "interval": event.get("interval"),
                    "iteration": event.get("iteration"),
                    "loop_id": event.get("loop_id"),
                    "status": event.get("status"),
                },
            }
        )
    for run in runs[:12]:
        metrics = run.get("metrics", {})
        events.append(
            {
                "timestamp": _created_at_ms(run.get("created_at")),
                "level": "INFO",
                "source": "BACKTEST",
                "message": (
                    f"{run.get('symbol', '-')}/{run.get('interval', '-')} "
                    f"return {_float_metric(metrics, 'return_pct', 0.0):+.3f}% "
                    f"trades {int(_float_metric(metrics, 'trade_count', 0.0))}"
                ),
                "payload": {
                    "symbol": run.get("symbol"),
                    "interval": run.get("interval"),
                    "return_pct": _float_metric(metrics, "return_pct", 0.0),
                    "trade_count": int(_float_metric(metrics, "trade_count", 0.0)),
                },
            }
        )
    for order in exchange_orders[-12:]:
        events.append(
            {
                "timestamp": _created_at_ms(order.get("created_at")),
                "level": "WARN" if order.get("status") == "rejected" else "EXEC",
                "source": "ORDER",
                "message": f"{order.get('exchange', '-')} {order.get('symbol', '-')} {order.get('side', '-')} {order.get('status', '-')}",
                "payload": order,
            }
        )
    for fill in fills[-12:]:
        events.append(
            {
                "timestamp": _created_at_ms(fill.get("created_at")),
                "level": "EXEC" if fill.get("status") == "filled" else "WARN",
                "source": "FILL",
                "message": f"{fill.get('symbol', '-')} {fill.get('side', '-')} qty {fill.get('quantity', 0)} @ {fill.get('price', 0)}",
                "payload": fill,
            }
        )
    for signal in signals[-12:]:
        events.append(
            {
                "timestamp": _created_at_ms(signal.get("created_at")),
                "level": "INFO",
                "source": "SIGNAL",
                "message": f"{signal.get('symbol', '-')} {signal.get('side', '-')} because {signal.get('reason', '-')}",
                "payload": signal,
            }
        )
    for state in risk_states[-8:]:
        events.append(
            {
                "timestamp": _created_at_ms(state.get("created_at")),
                "level": "INFO",
                "source": "RISK",
                "message": f"risk snapshot day {state.get('day_key', '-')} trades {state.get('trades_today', 0)}",
                "payload": state,
            }
        )
    events.sort(key=lambda item: item["timestamp"], reverse=True)
    return events[:50]


def _loop_event_level(status: object) -> str:
    value = str(status or "").lower()
    if value == "error":
        return "ERROR"
    if value == "rejected":
        return "WARN"
    if value == "filled":
        return "EXEC"
    return "INFO"


def _loop_event_message(event: dict) -> str:
    payload = event.get("payload") or {}
    detail = event.get("message") or payload.get("reason") or payload.get("message") or ""
    loop_id = str(event.get("loop_id") or "-")
    prefix = (
        f"{event.get('exchange', '-')} {event.get('symbol', '-')}/{event.get('interval', '-')} "
        f"loop {loop_id[:8]} #{event.get('iteration', '-')}: {event.get('status', '-')}"
    )
    return f"{prefix} - {detail}" if detail else prefix


def _raw_json(row: dict) -> dict:
    raw = row.get("raw_json")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _table_rows(storage: SQLiteStorage, table_name: str) -> list[dict]:
    return [dict(row) for row in storage.fetch_all(table_name)]


def _float_metric(metrics: dict, key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _created_at_ms(value: object) -> int:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(numeric if numeric > 10_000_000_000 else numeric * 1000)


def _gross_exposure(markets: list[dict], fallback_equity: float) -> float:
    if not markets:
        return fallback_equity * 0.35
    notional = sum(float(market.get("last_close") or 0) * 0.015 for market in markets[:5])
    return max(notional, fallback_equity * 0.2)


def _open_alert_count(
    runs: list[dict],
    exchange_orders: list[dict],
    fills: list[dict],
    loop_events: list[dict],
) -> int:
    negative_runs = sum(1 for run in runs[:20] if _float_metric(run.get("metrics", {}), "return_pct", 0.0) < 0)
    rejected_orders = sum(1 for order in exchange_orders if order.get("status") == "rejected")
    rejected_fills = sum(1 for fill in fills if fill.get("status") == "rejected")
    loop_errors = sum(1 for event in loop_events if event.get("status") == "error")
    return negative_runs + rejected_orders + rejected_fills + loop_errors


DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Kxian Bot Dashboard</title>
  <style>
    :root {
      --ink: #17211b;
      --muted: #667269;
      --paper: #f3efe3;
      --panel: rgba(255, 252, 240, 0.82);
      --line: rgba(23, 33, 27, 0.14);
      --green: #0c8f62;
      --red: #be3e2f;
      --gold: #d69b2d;
      --coal: #101512;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 16% 18%, rgba(214, 155, 45, .28), transparent 28rem),
        radial-gradient(circle at 92% 8%, rgba(12, 143, 98, .18), transparent 24rem),
        linear-gradient(135deg, #f9f5e8 0%, #eee5cf 48%, #e5dcc3 100%);
      min-height: 100vh;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(23,33,27,.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(23,33,27,.04) 1px, transparent 1px);
      background-size: 34px 34px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.85), transparent);
    }
    .shell { width: min(1420px, calc(100vw - 36px)); margin: 0 auto; padding: 30px 0 44px; }
    header { display: grid; grid-template-columns: 1.1fr .9fr; gap: 24px; align-items: end; margin-bottom: 22px; }
    h1 {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(42px, 7vw, 88px);
      line-height: .88;
      letter-spacing: -0.07em;
    }
    .eyebrow { margin: 0 0 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .22em; font-size: 12px; }
    .brief { margin: 12px 0 0; max-width: 760px; color: #39433d; font-size: 17px; line-height: 1.6; }
    .status-card {
      background: var(--coal);
      color: #f8f2df;
      border-radius: 28px;
      padding: 24px;
      box-shadow: 0 24px 70px rgba(16,21,18,.23);
      position: relative;
      overflow: hidden;
    }
    .status-card::after {
      content: "";
      position: absolute;
      right: -80px;
      top: -80px;
      width: 190px;
      height: 190px;
      border: 1px solid rgba(246, 214, 144, .45);
      border-radius: 50%;
    }
    .status-card b { display: block; font-size: 38px; line-height: 1; }
    .status-card span { color: #d7cfb8; }
    .grid { display: grid; grid-template-columns: 1.65fr .95fr; gap: 22px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 30px;
      padding: 22px;
      box-shadow: 0 20px 70px rgba(69, 59, 39, .12);
      backdrop-filter: blur(12px);
    }
    .panel h2 { margin: 0 0 14px; font-family: Georgia, "Times New Roman", serif; font-size: 28px; letter-spacing: -.04em; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 16px; }
    select, button {
      border: 1px solid rgba(23,33,27,.18);
      border-radius: 999px;
      background: #fffbef;
      color: var(--ink);
      padding: 10px 14px;
      font: inherit;
    }
    button {
      cursor: pointer;
      background: var(--coal);
      color: #fff7e4;
      border-color: var(--coal);
      transition: transform .16s ease, box-shadow .16s ease;
    }
    button:hover { transform: translateY(-1px); box-shadow: 0 12px 28px rgba(16,21,18,.18); }
    canvas {
      width: 100%;
      height: 430px;
      display: block;
      background: linear-gradient(180deg, rgba(255,255,255,.35), rgba(255,255,255,.05));
      border-radius: 22px;
      border: 1px solid rgba(23,33,27,.1);
    }
    .metric-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 18px 0 0; }
    .metric {
      border: 1px solid rgba(23,33,27,.12);
      border-radius: 20px;
      padding: 14px;
      background: rgba(255,255,255,.34);
    }
    .metric span { display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .13em; }
    .metric b { display: block; margin-top: 6px; font-size: 24px; }
    .runs { display: grid; gap: 12px; max-height: 540px; overflow: auto; padding-right: 4px; }
    .run {
      border: 1px solid rgba(23,33,27,.12);
      border-radius: 22px;
      padding: 14px;
      background: rgba(255,255,255,.42);
      cursor: pointer;
    }
    .run.active { outline: 2px solid var(--gold); background: rgba(255, 248, 218, .8); }
    .run-top { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
    .run-code { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
    .return { font-weight: 800; }
    .return.good { color: var(--green); }
    .return.bad { color: var(--red); }
    .params { margin-top: 8px; color: #39433d; font-size: 13px; }
    table { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 13px; }
    th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid rgba(23,33,27,.1); }
    th { color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .08em; font-size: 11px; }
    .empty { color: var(--muted); padding: 20px; border: 1px dashed rgba(23,33,27,.2); border-radius: 18px; }
    @media (max-width: 980px) {
      header, .grid { grid-template-columns: 1fr; }
      .metric-row { grid-template-columns: 1fr; }
      canvas { height: 330px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <section>
        <p class="eyebrow">Local paper-trading research console</p>
        <h1>Kxian<br/>Dashboard</h1>
        <p class="brief">查看本地 SQLite 里的 K 线、批量回测排名和逐笔交易。当前界面只读，不会下单。</p>
      </section>
      <aside class="status-card">
        <span>Loaded backtest runs</span>
        <b id="runCount">0</b>
        <span id="marketCount">0 markets tracked</span>
      </aside>
    </header>

    <section class="grid">
      <div class="panel">
        <h2>K-line Tape</h2>
        <div class="toolbar">
          <select id="marketSelect"></select>
          <button id="reloadButton">Reload</button>
        </div>
        <canvas id="chart" width="1100" height="430"></canvas>
        <div class="metric-row">
          <div class="metric"><span>Candles</span><b id="candleCount">0</b></div>
          <div class="metric"><span>Last Close</span><b id="lastClose">-</b></div>
          <div class="metric"><span>Range</span><b id="priceRange">-</b></div>
        </div>
      </div>

      <div class="panel">
        <h2>Parameter Runs</h2>
        <div id="runs" class="runs"></div>
      </div>
    </section>

    <section class="panel" style="margin-top:22px;">
      <h2>Trades</h2>
      <div id="tradeEmpty" class="empty">选择一个有交易的回测 run，查看逐笔交易。</div>
      <table id="tradeTable" hidden>
        <thead>
          <tr><th>Time</th><th>Side</th><th>Qty</th><th>Exec</th><th>Fee</th><th>PNL</th><th>Reason</th></tr>
        </thead>
        <tbody id="tradeBody"></tbody>
      </table>
    </section>
  </main>

  <script>
    const state = { markets: [], runs: [], selectedRunId: null };
    const $ = (id) => document.getElementById(id);

    async function fetchJson(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Request failed: ${url}`);
      return response.json();
    }

    function formatNumber(value, digits = 2) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return Number(value).toFixed(digits);
    }

    function formatPct(value) {
      const num = Number(value || 0);
      return `${num >= 0 ? "+" : ""}${num.toFixed(3)}%`;
    }

    function formatTime(ms) {
      const numeric = Number(ms);
      if (!numeric) return "-";
      return new Date(numeric).toISOString().slice(0, 16).replace("T", " ");
    }

    async function loadOverview() {
      const data = await fetchJson("/api/overview");
      state.markets = data.markets || [];
      state.runs = data.latest_runs || [];
      $("runCount").textContent = data.totals.backtest_runs;
      $("marketCount").textContent = `${data.totals.markets} markets · ${data.totals.trades} trades`;
      renderMarketSelect();
      renderRuns();
      await loadCandles();
    }

    function renderMarketSelect() {
      const select = $("marketSelect");
      select.innerHTML = "";
      if (!state.markets.length) {
        const option = document.createElement("option");
        option.textContent = "No candles in database";
        option.value = "";
        select.appendChild(option);
        return;
      }
      for (const market of state.markets) {
        const option = document.createElement("option");
        option.value = JSON.stringify(market);
        option.textContent = `${market.exchange} · ${market.symbol} · ${market.interval} · ${market.candle_count} bars`;
        select.appendChild(option);
      }
    }

    async function loadCandles() {
      const selected = $("marketSelect").value;
      if (!selected) {
        drawChart([]);
        return;
      }
      const market = JSON.parse(selected);
      const params = new URLSearchParams({
        exchange: market.exchange,
        symbol: market.symbol,
        interval: market.interval,
        limit: "420"
      });
      const data = await fetchJson(`/api/candles?${params}`);
      const candles = data.candles || [];
      $("candleCount").textContent = candles.length;
      $("lastClose").textContent = candles.length ? formatNumber(candles[candles.length - 1].close, 4) : "-";
      if (candles.length) {
        const lows = candles.map(c => c.low);
        const highs = candles.map(c => c.high);
        $("priceRange").textContent = `${formatNumber(Math.min(...lows), 2)} - ${formatNumber(Math.max(...highs), 2)}`;
      } else {
        $("priceRange").textContent = "-";
      }
      drawChart(candles);
    }

    function drawChart(candles) {
      const canvas = $("chart");
      const ctx = canvas.getContext("2d");
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "rgba(255, 252, 240, .62)";
      ctx.fillRect(0, 0, width, height);

      if (!candles.length) {
        ctx.fillStyle = "#667269";
        ctx.font = "22px Georgia";
        ctx.fillText("No candle data yet. Run download-history first.", 40, 70);
        return;
      }

      const pad = { left: 58, right: 24, top: 24, bottom: 44 };
      const lows = candles.map(c => c.low);
      const highs = candles.map(c => c.high);
      const min = Math.min(...lows);
      const max = Math.max(...highs);
      const span = Math.max(max - min, 1);
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      const y = (price) => pad.top + (max - price) / span * plotH;
      const x = (index) => pad.left + index / Math.max(candles.length - 1, 1) * plotW;

      ctx.strokeStyle = "rgba(23, 33, 27, .10)";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const yy = pad.top + i / 5 * plotH;
        ctx.beginPath();
        ctx.moveTo(pad.left, yy);
        ctx.lineTo(width - pad.right, yy);
        ctx.stroke();
        const price = max - i / 5 * span;
        ctx.fillStyle = "#667269";
        ctx.font = "12px Aptos";
        ctx.fillText(formatNumber(price, 2), 8, yy + 4);
      }

      const candleW = Math.max(3, Math.min(13, plotW / candles.length * .62));
      for (let i = 0; i < candles.length; i++) {
        const candle = candles[i];
        const xx = x(i);
        const up = candle.close >= candle.open;
        const color = up ? "#0c8f62" : "#be3e2f";
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(xx, y(candle.high));
        ctx.lineTo(xx, y(candle.low));
        ctx.stroke();
        const bodyTop = y(Math.max(candle.open, candle.close));
        const bodyBottom = y(Math.min(candle.open, candle.close));
        ctx.fillRect(xx - candleW / 2, bodyTop, candleW, Math.max(bodyBottom - bodyTop, 2));
      }
    }

    function renderRuns() {
      const container = $("runs");
      container.innerHTML = "";
      if (!state.runs.length) {
        container.innerHTML = `<div class="empty">还没有批量回测结果。先运行 batch-backtest。</div>`;
        return;
      }
      for (const run of state.runs) {
        const metrics = run.metrics || {};
        const params = run.parameters || {};
        const item = document.createElement("div");
        item.className = "run";
        item.dataset.runId = run.run_id;
        item.innerHTML = `
          <div class="run-top">
            <span class="run-code">${run.run_id}</span>
            <span class="return ${Number(metrics.return_pct || 0) >= 0 ? "good" : "bad"}">${formatPct(metrics.return_pct)}</span>
          </div>
          <div class="params">${run.exchange} ${run.symbol} ${run.interval} · short ${params.short_window ?? "-"} / long ${params.long_window ?? "-"}</div>
          <div class="params">DD ${formatPct(-(metrics.max_drawdown_pct || 0))} · PF ${formatNumber(metrics.profit_factor, 3)} · Trades ${metrics.trade_count ?? 0}</div>
        `;
        item.addEventListener("click", () => selectRun(run.run_id, item));
        container.appendChild(item);
      }
    }

    async function selectRun(runId, element) {
      state.selectedRunId = runId;
      document.querySelectorAll(".run").forEach(node => node.classList.remove("active"));
      element.classList.add("active");
      const data = await fetchJson(`/api/trades?run_id=${encodeURIComponent(runId)}`);
      renderTrades(data.trades || []);
    }

    function renderTrades(trades) {
      const table = $("tradeTable");
      const empty = $("tradeEmpty");
      const body = $("tradeBody");
      body.innerHTML = "";
      if (!trades.length) {
        table.hidden = true;
        empty.hidden = false;
        empty.textContent = "这个 run 没有成交记录。";
        return;
      }
      for (const trade of trades) {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${formatTime(trade.timestamp)}</td>
          <td>${trade.side}</td>
          <td>${formatNumber(trade.quantity, 8)}</td>
          <td>${formatNumber(trade.execution_price, 4)}</td>
          <td>${formatNumber(trade.fee, 4)}</td>
          <td>${formatNumber(trade.pnl, 4)}</td>
          <td>${trade.reason}</td>
        `;
        body.appendChild(row);
      }
      empty.hidden = true;
      table.hidden = false;
    }

    $("reloadButton").addEventListener("click", loadOverview);
    $("marketSelect").addEventListener("change", loadCandles);
    loadOverview().catch(error => {
      document.body.innerHTML = `<pre style="padding:30px;color:#be3e2f;">${error.stack || error}</pre>`;
    });
  </script>
</body>
</html>
"""

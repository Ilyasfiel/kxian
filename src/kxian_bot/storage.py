from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from kxian_bot.models import (
    BacktestRunSummary,
    BacktestTrade,
    Candle,
    ExchangeOrder,
    Fill,
    LoopEvent,
    Signal,
    StressBacktestRunSummary,
    TradingRule,
    WalkForwardRunSummary,
)
from kxian_bot.strategy_profile import active_profile_payload, profile_key
from kxian_bot.strategies.factory import SUPPORTED_STRATEGIES

FETCH_ALL_TABLES = {
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


class SQLiteStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record_exchange_order(self, order: ExchangeOrder, mode: str, exchange: str) -> None:
        self._execute(
            """
            INSERT INTO exchange_orders
            (created_at, mode, exchange, symbol, side, quantity, price, status, exchange_order_id, reason, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                mode,
                exchange,
                order.symbol,
                order.side,
                order.quantity,
                order.price,
                order.status,
                order.exchange_order_id,
                order.reason,
                order.model_dump_json(),
            ),
        )

    def record_signal(self, signal: Signal, mode: str, exchange: str) -> None:
        self._execute(
            """
            INSERT INTO strategy_signals
            (created_at, mode, exchange, symbol, side, price, reason, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), mode, exchange, signal.symbol, signal.side, signal.price, signal.reason, signal.model_dump_json()),
        )

    def record_fill(self, fill: Fill, mode: str, exchange: str) -> None:
        self._execute(
            """
            INSERT INTO fills
            (created_at, mode, exchange, symbol, side, quantity, price, status, reason, exchange_order_id, exchange_trade_id, trade_time, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                mode,
                exchange,
                fill.symbol,
                fill.side,
                fill.quantity,
                fill.price,
                fill.status,
                fill.reason,
                fill.exchange_order_id,
                fill.exchange_trade_id,
                fill.timestamp,
                fill.model_dump_json(),
            ),
        )

    def record_fill_if_new(self, fill: Fill, mode: str, exchange: str) -> bool:
        if fill.exchange_trade_id:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT id FROM fills
                    WHERE mode = ? AND exchange = ? AND symbol = ? AND exchange_trade_id = ?
                    LIMIT 1
                    """,
                    (mode, exchange, fill.symbol, fill.exchange_trade_id),
                ).fetchone()
            if row is not None:
                return False
        self.record_fill(fill, mode=mode, exchange=exchange)
        return True

    def record_backtest_trade(self, trade: BacktestTrade, run_id: str) -> None:
        self._execute(
            """
            INSERT INTO backtest_trades
            (created_at, run_id, timestamp, symbol, side, quantity, signal_price, execution_price, fee, slippage, pnl, reason, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                run_id,
                trade.timestamp,
                trade.symbol,
                trade.side,
                trade.quantity,
                trade.signal_price,
                trade.execution_price,
                trade.fee,
                trade.slippage,
                trade.pnl,
                trade.reason,
                trade.model_dump_json(),
            ),
        )

    def record_risk_state(
        self,
        risk_manager: Any,
        mode: str,
        exchange: str = "",
        symbol: str = "",
        interval: str = "",
    ) -> None:
        payload = {
            "trades_today": risk_manager.trades_today,
            "start_equity": risk_manager.start_equity,
            "last_fill_timestamp": risk_manager.last_fill_timestamp,
            "day_key": risk_manager.day_key,
        }
        self._execute(
            """
            INSERT INTO risk_state
            (created_at, mode, exchange, symbol, interval, day_key, trades_today, start_equity, last_fill_timestamp, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                mode,
                exchange,
                symbol,
                interval,
                risk_manager.day_key,
                risk_manager.trades_today,
                risk_manager.start_equity,
                risk_manager.last_fill_timestamp,
                json.dumps(payload, separators=(",", ":")),
            ),
        )

    def record_loop_event(self, event: LoopEvent) -> None:
        self._execute(
            """
            INSERT INTO loop_events
            (created_at, loop_id, iteration, status, mode, exchange, symbol, interval, message, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                event.loop_id,
                event.iteration,
                event.status,
                event.mode,
                event.exchange,
                event.symbol,
                event.interval,
                event.message,
                event.model_dump_json(),
            ),
        )

    def upsert_trading_rule(self, rule: TradingRule) -> None:
        self._execute(
            """
            INSERT INTO trading_rules
            (updated_at, exchange, symbol, price_step, quantity_step, min_quantity, min_notional, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, symbol) DO UPDATE SET
                updated_at=excluded.updated_at,
                price_step=excluded.price_step,
                quantity_step=excluded.quantity_step,
                min_quantity=excluded.min_quantity,
                min_notional=excluded.min_notional,
                raw_json=excluded.raw_json
            """,
            (
                _now(),
                rule.exchange,
                rule.symbol,
                rule.price_step,
                rule.quantity_step,
                rule.min_quantity,
                rule.min_notional,
                rule.model_dump_json(),
            ),
        )

    def latest_trading_rule(self, exchange: str, symbol: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT updated_at, exchange, symbol, price_step, quantity_step, min_quantity, min_notional, raw_json
                FROM trading_rules
                WHERE exchange = ? AND symbol = ?
                LIMIT 1
                """,
                (exchange, symbol),
            ).fetchone()
        return dict(row) if row is not None else None

    def set_automation_paused(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        interval: str,
        paused: bool,
        reason: str = "",
        updated_by: str = "operator",
    ) -> dict[str, Any]:
        now = _now()
        control_key = _loop_lock_key(mode, exchange, symbol, interval)
        payload = {
            "mode": mode,
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "paused": paused,
            "reason": reason,
            "updated_by": updated_by,
            "updated_at": now,
        }
        self._execute(
            """
            INSERT INTO automation_controls
            (control_key, updated_at, mode, exchange, symbol, interval, paused, reason, updated_by, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(control_key) DO UPDATE SET
                updated_at=excluded.updated_at,
                mode=excluded.mode,
                exchange=excluded.exchange,
                symbol=excluded.symbol,
                interval=excluded.interval,
                paused=excluded.paused,
                reason=excluded.reason,
                updated_by=excluded.updated_by,
                raw_json=excluded.raw_json
            """,
            (
                control_key,
                now,
                mode,
                exchange,
                symbol,
                interval,
                1 if paused else 0,
                reason,
                updated_by,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ),
        )
        return self.automation_control_status(mode, exchange, symbol, interval)

    def automation_control_status(self, mode: str, exchange: str, symbol: str, interval: str) -> dict[str, Any]:
        control_key = _loop_lock_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT control_key, updated_at, mode, exchange, symbol, interval, paused, reason, updated_by, raw_json
                FROM automation_controls
                WHERE control_key = ?
                LIMIT 1
                """,
                (control_key,),
            ).fetchone()
        if row is None:
            return {
                "control_key": control_key,
                "updated_at": None,
                "mode": mode,
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
                "paused": False,
                "reason": "",
                "updated_by": "",
                "source": "default",
            }
        item = dict(row)
        item["paused"] = bool(item["paused"])
        item["source"] = "sqlite"
        return item

    def upsert_strategy_profile(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        interval: str,
        strategy: str,
        parameters: dict[str, Any],
        evidence: dict[str, Any],
        updated_by: str = "operator",
    ) -> dict[str, Any]:
        now = _now()
        payload = active_profile_payload(
            mode=mode,
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            strategy=strategy,
            parameters=parameters,
            evidence=evidence,
            updated_by=updated_by,
            updated_at=now,
        )
        self._execute(
            """
            INSERT INTO strategy_profiles
            (profile_key, updated_at, mode, exchange, symbol, interval, strategy, parameters_json, evidence_json, active, updated_by, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_key) DO UPDATE SET
                updated_at=excluded.updated_at,
                mode=excluded.mode,
                exchange=excluded.exchange,
                symbol=excluded.symbol,
                interval=excluded.interval,
                strategy=excluded.strategy,
                parameters_json=excluded.parameters_json,
                evidence_json=excluded.evidence_json,
                active=excluded.active,
                updated_by=excluded.updated_by,
                raw_json=excluded.raw_json
            """,
            (
                payload["profile_key"],
                now,
                mode,
                exchange,
                symbol,
                interval,
                strategy,
                json.dumps(payload["parameters"], separators=(",", ":"), sort_keys=True),
                json.dumps(evidence, separators=(",", ":"), sort_keys=True),
                1,
                updated_by,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ),
        )
        return self.active_strategy_profile(mode, exchange, symbol, interval) or payload

    def active_strategy_profile(self, mode: str, exchange: str, symbol: str, interval: str) -> dict[str, Any] | None:
        key = profile_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT profile_key, updated_at, mode, exchange, symbol, interval, strategy,
                       parameters_json, evidence_json, active, updated_by, raw_json
                FROM strategy_profiles
                WHERE profile_key = ? AND active = 1
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        return _strategy_profile_from_row(row) if row is not None else None

    def promote_strategy_profile_to_mode(
        self,
        source_mode: str,
        target_mode: str,
        exchange: str,
        symbol: str,
        interval: str,
        updated_by: str = "operator",
    ) -> dict[str, Any]:
        if (source_mode, target_mode) not in {("paper", "testnet"), ("testnet", "live")}:
            return {
                "status": "blocked",
                "reason": "unsupported_profile_promotion_path",
                "source_mode": source_mode,
                "target_mode": target_mode,
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
            }

        source = self.active_strategy_profile(source_mode, exchange, symbol, interval)
        if source is None:
            return {
                "status": "blocked",
                "reason": "missing_source_profile",
                "source_mode": source_mode,
                "target_mode": target_mode,
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
            }
        evidence = source.get("evidence", {})
        sample_validation = evidence.get("sample_validation") if isinstance(evidence, dict) else None
        if not isinstance(sample_validation, dict) or sample_validation.get("status") != "pass":
            return {
                "status": "blocked",
                "reason": "source_profile_missing_passing_sample_validation",
                "source_profile_key": source.get("profile_key"),
                "source_mode": source_mode,
                "target_mode": target_mode,
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
            }
        if target_mode == "live":
            promotion = evidence.get("promotion") if isinstance(evidence, dict) else None
            if not isinstance(promotion, dict) or promotion.get("target_mode") != "testnet":
                return {
                    "status": "blocked",
                    "reason": "source_profile_missing_testnet_promotion_evidence",
                    "source_profile_key": source.get("profile_key"),
                    "source_mode": source_mode,
                    "target_mode": target_mode,
                    "exchange": exchange,
                    "symbol": symbol,
                    "interval": interval,
                }
            non_order_observation = self.latest_testnet_observation(
                exchange,
                symbol,
                interval,
                execute_loop=False,
            )
            non_order_failures = _testnet_observation_acceptance_failures(non_order_observation, execute_loop=False)
            if non_order_failures:
                return {
                    "status": "blocked",
                    "reason": "source_profile_missing_passing_testnet_observation",
                    "source_profile_key": source.get("profile_key"),
                    "source_mode": source_mode,
                    "target_mode": target_mode,
                    "exchange": exchange,
                    "symbol": symbol,
                    "interval": interval,
                    "testnet_observation": non_order_observation,
                    "execute_loop_required": False,
                    "failures": non_order_failures,
                }
            order_observation = self.latest_testnet_observation(
                exchange,
                symbol,
                interval,
                execute_loop=True,
            )
            order_failures = _testnet_observation_acceptance_failures(order_observation, execute_loop=True)
            if order_failures:
                return {
                    "status": "blocked",
                    "reason": "source_profile_missing_passing_testnet_order_observation",
                    "source_profile_key": source.get("profile_key"),
                    "source_mode": source_mode,
                    "target_mode": target_mode,
                    "exchange": exchange,
                    "symbol": symbol,
                    "interval": interval,
                    "testnet_observation": order_observation,
                    "execute_loop_required": True,
                    "failures": order_failures,
                }

        promoted_evidence = {
            **evidence,
            "promotion": {
                "source_profile_key": source.get("profile_key"),
                "source_updated_at": source.get("updated_at"),
                "target_mode": target_mode,
                "promoted_by": updated_by,
            },
        }
        if target_mode == "live":
            promoted_evidence["testnet_observation"] = {
                "non_ordering": non_order_observation,
                "bounded_order": order_observation,
            }
        profile = self.upsert_strategy_profile(
            mode=target_mode,
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            strategy=source["strategy"],
            parameters=source["parameters"],
            evidence=promoted_evidence,
            updated_by=updated_by,
        )
        return {
            "status": "pass",
            "reason": f"profile_promoted_to_{target_mode}",
            "source_profile_key": source.get("profile_key"),
            "promoted": profile,
        }

    def position_runtime_state(self, mode: str, exchange: str, symbol: str, interval: str) -> dict[str, Any]:
        state_key = _loop_lock_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state_key, updated_at, mode, exchange, symbol, interval, trailing_peak_price, raw_json
                FROM position_runtime_state
                WHERE state_key = ?
                LIMIT 1
                """,
                (state_key,),
            ).fetchone()
        if row is None:
            return {
                "state_key": state_key,
                "updated_at": None,
                "mode": mode,
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
                "trailing_peak_price": 0.0,
                "source": "default",
            }
        item = dict(row)
        item["trailing_peak_price"] = float(item["trailing_peak_price"] or 0.0)
        item["source"] = "sqlite"
        return item

    def update_position_runtime_state(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        interval: str,
        trailing_peak_price: float,
    ) -> dict[str, Any]:
        now = _now()
        state_key = _loop_lock_key(mode, exchange, symbol, interval)
        trailing_peak_price = max(0.0, float(trailing_peak_price or 0.0))
        payload = {
            "mode": mode,
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "trailing_peak_price": trailing_peak_price,
            "updated_at": now,
        }
        self._execute(
            """
            INSERT INTO position_runtime_state
            (state_key, updated_at, mode, exchange, symbol, interval, trailing_peak_price, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                updated_at=excluded.updated_at,
                mode=excluded.mode,
                exchange=excluded.exchange,
                symbol=excluded.symbol,
                interval=excluded.interval,
                trailing_peak_price=excluded.trailing_peak_price,
                raw_json=excluded.raw_json
            """,
            (
                state_key,
                now,
                mode,
                exchange,
                symbol,
                interval,
                trailing_peak_price,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ),
        )
        return self.position_runtime_state(mode, exchange, symbol, interval)

    def reset_position_runtime_state(self, mode: str, exchange: str, symbol: str, interval: str) -> dict[str, Any]:
        return self.update_position_runtime_state(
            mode,
            exchange,
            symbol,
            interval,
            trailing_peak_price=0.0,
        )

    def acquire_loop_lock(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        interval: str,
        loop_id: str,
        stale_after_seconds: float,
    ) -> dict[str, Any]:
        now = _now()
        stale_before = now - stale_after_seconds
        lock_key = _loop_lock_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT lock_key, loop_id, mode, exchange, symbol, interval, acquired_at, heartbeat_at
                FROM loop_locks
                WHERE lock_key = ?
                """,
                (lock_key,),
            ).fetchone()
            if row is not None and float(row["heartbeat_at"]) >= stale_before:
                return {
                    "acquired": False,
                    "reason": "loop_lock_active",
                    "lock": dict(row),
                    "stale_after_seconds": stale_after_seconds,
                }
            connection.execute(
                """
                INSERT INTO loop_locks
                (lock_key, loop_id, mode, exchange, symbol, interval, acquired_at, heartbeat_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lock_key) DO UPDATE SET
                    loop_id = excluded.loop_id,
                    mode = excluded.mode,
                    exchange = excluded.exchange,
                    symbol = excluded.symbol,
                    interval = excluded.interval,
                    acquired_at = excluded.acquired_at,
                    heartbeat_at = excluded.heartbeat_at
                """,
                (lock_key, loop_id, mode, exchange, symbol, interval, now, now),
            )
        return {
            "acquired": True,
            "reason": "loop_lock_acquired",
            "lock": {
                "lock_key": lock_key,
                "loop_id": loop_id,
                "mode": mode,
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
                "acquired_at": now,
                "heartbeat_at": now,
            },
            "stale_after_seconds": stale_after_seconds,
        }

    def heartbeat_loop_lock(self, mode: str, exchange: str, symbol: str, interval: str, loop_id: str) -> bool:
        lock_key = _loop_lock_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE loop_locks
                SET heartbeat_at = ?
                WHERE lock_key = ? AND loop_id = ?
                """,
                (_now(), lock_key, loop_id),
            )
            return cursor.rowcount == 1

    def release_loop_lock(self, mode: str, exchange: str, symbol: str, interval: str, loop_id: str) -> bool:
        lock_key = _loop_lock_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM loop_locks WHERE lock_key = ? AND loop_id = ?",
                (lock_key, loop_id),
            )
            return cursor.rowcount == 1

    def active_loop_lock(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        interval: str,
        stale_after_seconds: float,
    ) -> dict[str, Any] | None:
        stale_before = _now() - stale_after_seconds
        lock_key = _loop_lock_key(mode, exchange, symbol, interval)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT lock_key, loop_id, mode, exchange, symbol, interval, acquired_at, heartbeat_at
                FROM loop_locks
                WHERE lock_key = ? AND heartbeat_at >= ?
                """,
                (lock_key, stale_before),
            ).fetchone()
        return dict(row) if row is not None else None

    def upsert_candles(self, candles: list[Candle], exchange: str, symbol: str, interval: str) -> int:
        if not candles:
            return 0
        rows = [
            (
                exchange,
                symbol,
                interval,
                candle.open_time,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.close_time,
                candle.model_dump_json(),
            )
            for candle in candles
        ]
        with self._connect() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO candles
                (exchange, symbol, interval, open_time, open, high, low, close, volume, close_time, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, interval, open_time) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    close_time=excluded.close_time,
                    raw_json=excluded.raw_json
                """,
                rows,
            )
            return connection.total_changes - before

    def load_candles(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Candle]:
        clauses = ["exchange = ?", "symbol = ?", "interval = ?"]
        params: list[Any] = [exchange, symbol, interval]
        if start_time is not None:
            clauses.append("open_time >= ?")
            params.append(start_time)
        if end_time is not None:
            clauses.append("open_time <= ?")
            params.append(end_time)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT open_time, open, high, low, close, volume, close_time
                FROM candles
                WHERE {" AND ".join(clauses)}
                ORDER BY open_time ASC
                """,
                tuple(params),
            ).fetchall()
        return [
            Candle(
                open_time=row["open_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                close_time=row["close_time"],
            )
            for row in rows
        ]

    def load_recent_candles(self, exchange: str, symbol: str, interval: str, limit: int) -> list[Candle]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT open_time, open, high, low, close, volume, close_time
                FROM candles
                WHERE exchange = ? AND symbol = ? AND interval = ?
                ORDER BY open_time DESC
                LIMIT ?
                """,
                (exchange, symbol, interval, limit),
            ).fetchall()
        return [
            Candle(
                open_time=row["open_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                close_time=row["close_time"],
            )
            for row in reversed(rows)
        ]

    def list_candle_markets(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT exchange, symbol, interval, COUNT(*) AS candle_count,
                       MIN(open_time) AS start_time, MAX(open_time) AS end_time
                FROM candles
                GROUP BY exchange, symbol, interval
                ORDER BY exchange, symbol, interval
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_backtest_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, run_id, exchange, symbol, interval, start_time, end_time,
                       strategy, parameters_json, metrics_json, candle_count
                FROM backtest_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        runs: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["parameters"] = json.loads(item.pop("parameters_json"))
            item["metrics"] = json.loads(item.pop("metrics_json"))
            runs.append(item)
        return runs

    def latest_backtest_run(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        short_window: int,
        long_window: int,
        parameters: dict[str, Any] | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any] | None:
        parameter_jsons = _parameter_json_candidates(parameters, short_window, long_window, strategy)
        with self._connect() as connection:
            query = """
                SELECT created_at, run_id, exchange, symbol, interval, start_time, end_time,
                       strategy, parameters_json, metrics_json, candle_count
                FROM backtest_runs
                WHERE exchange = ? AND symbol = ? AND interval = ? AND parameters_json IN ({placeholders})
            """
            query = query.format(placeholders=", ".join("?" for _ in parameter_jsons))
            values: list[Any] = [exchange, symbol, interval, *parameter_jsons]
            if strategy is not None:
                query += " AND strategy = ?"
                values.append(strategy)
            query += " ORDER BY created_at DESC LIMIT 1"
            row = connection.execute(
                query,
                values,
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item.pop("parameters_json"))
        item["metrics"] = json.loads(item.pop("metrics_json"))
        return item

    def record_stress_backtest_run(self, summary: StressBacktestRunSummary) -> None:
        metrics = {
            "scenario_count": summary.scenario_count,
            "passed_scenarios": summary.passed_scenarios,
            "failed_scenarios": summary.failed_scenarios,
            "pass_rate": summary.pass_rate,
            "worst_return_pct": summary.worst_return_pct,
            "worst_drawdown_pct": summary.worst_drawdown_pct,
            "worst_profit_factor": summary.worst_profit_factor,
            "min_trade_count": summary.min_trade_count,
        }
        self._execute(
            """
            INSERT INTO stress_backtest_runs
            (created_at, run_id, exchange, symbol, interval, start_time, end_time, strategy, parameters_json, metrics_json, scenario_json, candle_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                summary.run_id,
                summary.exchange,
                summary.symbol,
                summary.interval,
                summary.start_time,
                summary.end_time,
                summary.strategy,
                json.dumps(summary.parameters, separators=(",", ":"), sort_keys=True),
                json.dumps(metrics, separators=(",", ":"), sort_keys=True),
                json.dumps(summary.scenarios, separators=(",", ":"), sort_keys=True),
                summary.candle_count,
            ),
        )

    def list_stress_backtest_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, run_id, exchange, symbol, interval, start_time, end_time,
                       strategy, parameters_json, metrics_json, scenario_json, candle_count
                FROM stress_backtest_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_stress_run_from_row(row) for row in rows]

    def latest_stress_backtest_run(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        short_window: int,
        long_window: int,
        parameters: dict[str, Any] | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any] | None:
        parameter_jsons = _parameter_json_candidates(parameters, short_window, long_window, strategy)
        with self._connect() as connection:
            query = """
                SELECT created_at, run_id, exchange, symbol, interval, start_time, end_time,
                       strategy, parameters_json, metrics_json, scenario_json, candle_count
                FROM stress_backtest_runs
                WHERE exchange = ? AND symbol = ? AND interval = ? AND parameters_json IN ({placeholders})
            """
            query = query.format(placeholders=", ".join("?" for _ in parameter_jsons))
            values: list[Any] = [exchange, symbol, interval, *parameter_jsons]
            if strategy is not None:
                query += " AND strategy = ?"
                values.append(strategy)
            query += " ORDER BY created_at DESC LIMIT 1"
            row = connection.execute(
                query,
                values,
            ).fetchone()
        return _stress_run_from_row(row) if row is not None else None

    def record_walk_forward_run(self, summary: WalkForwardRunSummary) -> None:
        metrics = {
            "segment_count": summary.segment_count,
            "passed_segments": summary.passed_segments,
            "failed_segments": summary.failed_segments,
            "pass_rate": summary.pass_rate,
            "total_trade_count": summary.total_trade_count,
            "min_segment_trade_count": summary.min_segment_trade_count,
            "worst_return_pct": summary.worst_return_pct,
            "worst_drawdown_pct": summary.worst_drawdown_pct,
            "worst_profit_factor": summary.worst_profit_factor,
        }
        self._execute(
            """
            INSERT INTO walk_forward_runs
            (created_at, run_id, exchange, symbol, interval, start_time, end_time, strategy, parameters_json, metrics_json, segment_json, candle_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                summary.run_id,
                summary.exchange,
                summary.symbol,
                summary.interval,
                summary.start_time,
                summary.end_time,
                summary.strategy,
                json.dumps(summary.parameters, separators=(",", ":"), sort_keys=True),
                json.dumps(metrics, separators=(",", ":"), sort_keys=True),
                json.dumps(summary.segments, separators=(",", ":"), sort_keys=True),
                summary.candle_count,
            ),
        )

    def list_walk_forward_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, run_id, exchange, symbol, interval, start_time, end_time,
                       strategy, parameters_json, metrics_json, segment_json, candle_count
                FROM walk_forward_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_walk_forward_run_from_row(row) for row in rows]

    def latest_walk_forward_run(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        short_window: int,
        long_window: int,
        parameters: dict[str, Any] | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any] | None:
        parameter_jsons = _parameter_json_candidates(parameters, short_window, long_window, strategy)
        with self._connect() as connection:
            query = """
                SELECT created_at, run_id, exchange, symbol, interval, start_time, end_time,
                       strategy, parameters_json, metrics_json, segment_json, candle_count
                FROM walk_forward_runs
                WHERE exchange = ? AND symbol = ? AND interval = ? AND parameters_json IN ({placeholders})
            """
            query = query.format(placeholders=", ".join("?" for _ in parameter_jsons))
            values: list[Any] = [exchange, symbol, interval, *parameter_jsons]
            if strategy is not None:
                query += " AND strategy = ?"
                values.append(strategy)
            query += " ORDER BY created_at DESC LIMIT 1"
            row = connection.execute(
                query,
                values,
            ).fetchone()
        return _walk_forward_run_from_row(row) if row is not None else None

    def load_backtest_trades(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT timestamp, symbol, side, quantity, signal_price, execution_price,
                       fee, slippage, pnl, reason
                FROM backtest_trades
                WHERE run_id = ?
                ORDER BY timestamp ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replay_fill_balances(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        starting_usdt: float,
    ) -> dict[str, float]:
        usdt_balance = starting_usdt
        asset_balance = 0.0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT side, quantity, price, status
                FROM fills
                WHERE mode = ? AND exchange = ? AND symbol = ? AND status = 'filled'
                ORDER BY created_at ASC, id ASC
                """,
                (mode, exchange, symbol),
            ).fetchall()
        for row in rows:
            quantity = float(row["quantity"] or 0)
            price = float(row["price"] or 0)
            notional = quantity * price
            if row["side"] == "buy":
                usdt_balance -= notional
                asset_balance += quantity
            elif row["side"] == "sell":
                usdt_balance += notional
                asset_balance -= quantity
        return {
            "usdt_balance": round(usdt_balance, 8),
            "asset_balance": round(asset_balance, 8),
        }

    def replay_position_state(
        self,
        mode: str,
        exchange: str,
        symbol: str,
        starting_usdt: float,
    ) -> dict[str, float]:
        usdt_balance = starting_usdt
        asset_balance = 0.0
        cost_basis = 0.0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT side, quantity, price, status
                FROM fills
                WHERE mode = ? AND exchange = ? AND symbol = ? AND status = 'filled'
                ORDER BY created_at ASC, id ASC
                """,
                (mode, exchange, symbol),
            ).fetchall()
        for row in rows:
            quantity = float(row["quantity"] or 0)
            price = float(row["price"] or 0)
            notional = quantity * price
            if row["side"] == "buy":
                usdt_balance -= notional
                cost_basis += notional
                asset_balance += quantity
            elif row["side"] == "sell":
                sell_quantity = min(quantity, asset_balance)
                average_entry_price = cost_basis / asset_balance if asset_balance > 0 else 0.0
                usdt_balance += notional
                cost_basis -= average_entry_price * sell_quantity
                asset_balance -= sell_quantity
                if asset_balance <= 1e-12:
                    asset_balance = 0.0
                    cost_basis = 0.0
        average_entry_price = cost_basis / asset_balance if asset_balance > 0 else 0.0
        return {
            "usdt_balance": round(usdt_balance, 8),
            "asset_balance": round(asset_balance, 8),
            "average_entry_price": round(average_entry_price, 8),
        }

    def latest_risk_state(self, mode: str, exchange: str = "", symbol: str = "", interval: str = "") -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT created_at, mode, exchange, symbol, interval, day_key, trades_today, start_equity, last_fill_timestamp, raw_json
                FROM risk_state
                WHERE mode = ? AND exchange = ? AND symbol = ? AND interval = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (mode, exchange, symbol, interval),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_open_exchange_orders(self, mode: str, exchange: str, symbol: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, mode, exchange, symbol, side, quantity, price, status, exchange_order_id, reason
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY COALESCE(NULLIF(exchange_order_id, ''), CAST(id AS TEXT))
                               ORDER BY created_at DESC, id DESC
                           ) AS rank
                    FROM exchange_orders
                    WHERE mode = ? AND exchange = ? AND symbol = ?
                )
                WHERE rank = 1 AND status IN ('submitted', 'partially_filled')
                ORDER BY created_at DESC
                """,
                (mode, exchange, symbol),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_exchange_order(self, mode: str, exchange: str, symbol: str, created_after: float | None = None) -> dict[str, Any] | None:
        filters = ["mode = ?", "exchange = ?", "symbol = ?"]
        params: list[Any] = [mode, exchange, symbol]
        if created_after is not None:
            filters.append("created_at >= ?")
            params.append(created_after)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT created_at, mode, exchange, symbol, side, quantity, price, status, exchange_order_id, reason
                FROM exchange_orders
                WHERE {' AND '.join(filters)}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_loop_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, loop_id, iteration, status, mode, exchange, symbol, interval, message, raw_json
                FROM loop_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loop_event_payload(item.pop("raw_json"))
            events.append(item)
        return events

    def latest_testnet_observation(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        execute_loop: bool | None = None,
        limit: int = 500,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, loop_id, iteration, status, mode, exchange, symbol, interval, message, raw_json
                FROM loop_events
                WHERE mode = 'testnet' AND exchange = ? AND symbol = ? AND interval = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (exchange, symbol, interval, max(1, int(limit))),
            ).fetchall()

        observations: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            payload = _loop_event_payload(str(item.get("raw_json") or ""))
            if payload.get("kind") != "testnet_observe":
                continue
            event_execute_loop = bool(payload.get("execute_loop", False))
            if execute_loop is not None and event_execute_loop != execute_loop:
                continue
            observation_id = str(payload.get("observation_id") or str(item.get("loop_id") or "").removeprefix("observe-"))
            if not observation_id:
                continue
            observations.setdefault(observation_id, []).append({**item, "payload": payload, "execute_loop": event_execute_loop})

        if not observations:
            return None
        observation_id, events = next(iter(observations.items()))
        return _testnet_observation_summary(observation_id, events)

    def record_backtest_run(self, summary: BacktestRunSummary) -> None:
        metrics = {
            "initial_equity": summary.initial_equity,
            "final_equity": summary.final_equity,
            "return_pct": summary.return_pct,
            "max_drawdown_pct": summary.max_drawdown_pct,
            "win_rate": summary.win_rate,
            "profit_factor": summary.profit_factor,
            "trade_count": summary.trade_count,
            "fees_paid": summary.fees_paid,
            "slippage_paid": summary.slippage_paid,
        }
        self._execute(
            """
            INSERT INTO backtest_runs
            (created_at, run_id, exchange, symbol, interval, start_time, end_time, strategy, parameters_json, metrics_json, candle_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                summary.run_id,
                summary.exchange,
                summary.symbol,
                summary.interval,
                summary.start_time,
                summary.end_time,
                summary.strategy,
                json.dumps(summary.parameters, separators=(",", ":"), sort_keys=True),
                json.dumps(metrics, separators=(",", ":"), sort_keys=True),
                summary.candle_count,
            ),
        )

    def fetch_all(self, table_name: str) -> list[sqlite3.Row]:
        if table_name not in FETCH_ALL_TABLES:
            raise ValueError(f"Unsupported table: {table_name}")
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table_name}").fetchall()
        return rows

    def table_names(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {row["name"] for row in rows}

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS exchange_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    reason TEXT,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    reason TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    exchange_order_id TEXT NOT NULL DEFAULT '',
                    exchange_trade_id TEXT NOT NULL DEFAULT '',
                    trade_time INTEGER NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backtest_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    run_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    signal_price REAL NOT NULL,
                    execution_price REAL NOT NULL,
                    fee REAL NOT NULL,
                    slippage REAL NOT NULL,
                    pnl REAL NOT NULL,
                    reason TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trading_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at REAL NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    price_step REAL NOT NULL,
                    quantity_step REAL NOT NULL,
                    min_quantity REAL NOT NULL,
                    min_notional REAL NOT NULL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(exchange, symbol)
                );
                CREATE TABLE IF NOT EXISTS automation_controls (
                    control_key TEXT PRIMARY KEY,
                    updated_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    paused INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_automation_controls_scope
                    ON automation_controls(mode, exchange, symbol, interval, updated_at);
                CREATE TABLE IF NOT EXISTS strategy_profiles (
                    profile_key TEXT PRIMARY KEY,
                    updated_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    updated_by TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_profiles_scope
                    ON strategy_profiles(mode, exchange, symbol, interval, active, updated_at);
                CREATE TABLE IF NOT EXISTS position_runtime_state (
                    state_key TEXT PRIMARY KEY,
                    updated_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    trailing_peak_price REAL NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_position_runtime_state_scope
                    ON position_runtime_state(mode, exchange, symbol, interval, updated_at);
                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    close_time INTEGER NOT NULL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(exchange, symbol, interval, open_time)
                );
                CREATE INDEX IF NOT EXISTS idx_candles_lookup
                    ON candles(exchange, symbol, interval, open_time);
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    candle_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stress_backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    scenario_json TEXT NOT NULL,
                    candle_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS walk_forward_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    segment_json TEXT NOT NULL,
                    candle_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS risk_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL DEFAULT '',
                    interval TEXT NOT NULL DEFAULT '',
                    day_key TEXT,
                    trades_today INTEGER NOT NULL,
                    start_equity REAL,
                    last_fill_timestamp REAL,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS loop_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    message TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_loop_events_lookup
                    ON loop_events(loop_id, created_at);
                CREATE TABLE IF NOT EXISTS loop_locks (
                    lock_key TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_loop_locks_lookup
                    ON loop_locks(mode, exchange, symbol, interval, heartbeat_at);
                """
            )
            self._ensure_column(connection, "risk_state", "exchange", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "risk_state", "symbol", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "risk_state", "interval", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "fills", "exchange_order_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "fills", "exchange_trade_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "fills", "trade_time", "INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_risk_state_scope ON risk_state(mode, exchange, symbol, interval, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_fills_trade_id ON fills(mode, exchange, symbol, exchange_trade_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_stress_backtest_scope ON stress_backtest_runs(exchange, symbol, interval, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_walk_forward_scope ON walk_forward_runs(exchange, symbol, interval, created_at)"
            )

    def _execute(self, sql: str, params: tuple) -> None:
        with self._connect() as connection:
            connection.execute(sql, params)

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _now() -> float:
    return time.time()


def _loop_lock_key(mode: str, exchange: str, symbol: str, interval: str) -> str:
    return f"{mode}:{exchange}:{symbol}:{interval}"


def _parameter_json_candidates(
    parameters: dict[str, Any] | None,
    short_window: int,
    long_window: int,
    strategy: str | None,
) -> list[str]:
    base = dict(parameters or {"long_window": long_window, "short_window": short_window})
    candidates: list[dict[str, Any]] = [base]
    if "strategy" in base:
        legacy = dict(base)
        legacy.pop("strategy", None)
        candidates.append(legacy)
    else:
        strategy_names = (
            [strategy]
            if strategy is not None
            else list(SUPPORTED_STRATEGIES)
        )
        for strategy_name in strategy_names:
            candidates.append({"strategy": strategy_name, **base})
    return list(
        dict.fromkeys(
            json.dumps(candidate, separators=(",", ":"), sort_keys=True)
            for candidate in candidates
        )
    )


def _strategy_profile_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["parameters"] = json.loads(item.pop("parameters_json"))
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["active"] = bool(item["active"])
    item.pop("raw_json", None)
    return item


def _stress_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["parameters"] = json.loads(item.pop("parameters_json"))
    item["metrics"] = json.loads(item.pop("metrics_json"))
    item["scenarios"] = json.loads(item.pop("scenario_json"))
    return item


def _walk_forward_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["parameters"] = json.loads(item.pop("parameters_json"))
    item["metrics"] = json.loads(item.pop("metrics_json"))
    item["segments"] = json.loads(item.pop("segment_json"))
    return item


def _loop_event_payload(raw_json: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    payload = value.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _testnet_observation_summary(observation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    events = sorted(events, key=lambda event: (float(event.get("created_at") or 0), int(event.get("iteration") or 0)))
    cycles_completed = len(events)
    failures = sum(1 for event in events if event.get("status") != "idle")
    first = events[0] if events else {}
    latest = events[-1] if events else {}
    latest_payload = latest.get("payload") or {}
    order_lifecycle = latest_payload.get("order_lifecycle")
    lifecycle_acceptable = True
    if isinstance(order_lifecycle, dict):
        lifecycle_acceptable = bool(order_lifecycle.get("acceptable", False))
    return {
        "status": "pass" if cycles_completed > 0 and failures == 0 and lifecycle_acceptable else "fail",
        "observation_id": observation_id,
        "mode": "testnet",
        "exchange": latest.get("exchange") or first.get("exchange") or "",
        "symbol": latest.get("symbol") or first.get("symbol") or "",
        "interval": latest.get("interval") or first.get("interval") or "",
        "execute_loop": bool(latest.get("execute_loop", False)),
        "cycles_completed": cycles_completed,
        "failures": failures,
        "started_at": first.get("created_at"),
        "completed_at": latest.get("created_at"),
        "latest_reason": latest_payload.get("reason", ""),
        "latest_message": latest.get("message", ""),
        "order_lifecycle": order_lifecycle if isinstance(order_lifecycle, dict) else None,
        "profile": latest_payload.get("profile") if isinstance(latest_payload.get("profile"), dict) else None,
        "account": latest_payload.get("account") if isinstance(latest_payload.get("account"), dict) else None,
        "fill_sync": latest_payload.get("fill_sync") if isinstance(latest_payload.get("fill_sync"), dict) else None,
        "preflight": latest_payload.get("preflight") if isinstance(latest_payload.get("preflight"), dict) else None,
        "open_order_count": latest_payload.get("open_order_count"),
    }


def _testnet_observation_acceptance_failures(observation: dict[str, Any] | None, execute_loop: bool) -> list[str]:
    if observation is None:
        return ["missing_testnet_observation"]
    failures: list[str] = []
    if observation.get("status") != "pass":
        failures.append("testnet_observation_not_passed")
    if bool(observation.get("execute_loop")) != execute_loop:
        failures.append("testnet_observation_scope_mismatch")
    if int(observation.get("cycles_completed") or 0) < 6:
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

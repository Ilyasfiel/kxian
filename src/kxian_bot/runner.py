from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid

from kxian_bot.batch import run_batch_backtest
from kxian_bot.backtest import BacktestEngine, SyntheticShortBacktestEngine
from kxian_bot.brokers.base import create_broker
from kxian_bot.brokers.paper import PaperBroker
from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.execution_rules import default_trading_rule, normalize_order
from kxian_bot.market_data import (
    aggregate_candles,
    create_market_data_client,
    create_sqlite_replay_market_data_client,
    interval_to_milliseconds,
    MarketDataError,
)
from kxian_bot.market_diagnostics import diagnose_market
from kxian_bot.models import (
    BacktestRunSummary,
    BacktestResult,
    Candle,
    ExchangeOrder,
    Fill,
    LoopEvent,
    OrderRequest,
    Signal,
    StressBacktestRunSummary,
    WalkForwardRunSummary,
)
from kxian_bot.risk import RiskManager
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategy_profile import apply_active_strategy_profile
from kxian_bot.strategy_parameters import strategy_parameters
from kxian_bot.strategies.factory import RESEARCH_ONLY_STRATEGIES, create_strategy


PROTECTIVE_EXIT_REASONS = {"stop_loss_triggered", "take_profit_triggered", "trailing_stop_triggered"}
SYNTHETIC_SHORT_STRATEGIES = frozenset({"downtrend_breakdown_short"})


class TradingRunner:
    def __init__(self, config: RuntimeConfig, apply_profile: bool = True) -> None:
        self.storage = SQLiteStorage(config.db_path)
        self.config = apply_active_strategy_profile(config, self.storage) if apply_profile else config
        config = self.config
        self.market_data = (
            create_sqlite_replay_market_data_client(self.storage, config.exchange)
            if config.market_data_source == "sqlite"
            else create_market_data_client(config.exchange, use_testnet=config.mode == "testnet" and config.use_testnet)
        )
        self.strategy = create_strategy(
            config.strategy,
            short_window=config.short_window,
            long_window=config.long_window,
            symbol=config.symbol,
        )
        self.trading_rule = self._load_trading_rule()
        self.risk = self._create_risk_manager()
        self.broker = create_broker(config)
        self.average_entry_price = 0.0
        self.trailing_peak_price = 0.0
        self._restore_broker_state()
        self._restore_position_runtime_state()
        self._restore_risk_state()

    def run_once(self) -> dict:
        control = self.storage.automation_control_status(
            self.config.mode,
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
        )
        if control["paused"]:
            return {
                "status": "idle",
                "reason": "automation_paused",
                "control": control,
            }
        if self.config.mode in {"testnet", "live"}:
            refresh_result = self._refresh_exchange_open_orders()
            if refresh_result["refreshed"]:
                return refresh_result
            sync_result = self._sync_exchange_account_balances()
            if sync_result is not None and sync_result.get("status") != "synced":
                return sync_result
        candles = self.market_data.fetch_klines(self.config.symbol, self.config.interval, limit=self.config.long_window + 5)
        if not candles:
            return {"status": "idle", "reason": "no_new_candle"}
        protective_signal = self._protective_exit_signal(candles[-1].close)
        if protective_signal is not None:
            self.storage.record_signal(protective_signal, mode=self.config.mode, exchange=self.config.exchange)
            return self._execute_signal(protective_signal)
        signal = self.strategy.generate(candles)
        if signal is None:
            return {"status": "idle", "reason": "no_signal"}
        self.storage.record_signal(signal, mode=self.config.mode, exchange=self.config.exchange)
        return self._execute_signal(signal)

    def _execute_signal(self, signal) -> dict:
        if signal.side == "buy" and self.broker.asset_balance > 0:
            return {"status": "idle", "reason": "position_already_open"}

        quantity = self.risk.size_order(self.broker.usdt_balance, signal.price)
        if signal.side == "sell":
            quantity = round(self.broker.asset_balance, 8)
        if quantity <= 0:
            return {"status": "idle", "reason": "no_size"}

        current_equity = self.broker.usdt_balance + self.broker.asset_balance * signal.price
        decision = self.risk.validate(
            signal.side,
            quantity,
            signal.price,
            self.broker.usdt_balance,
            self.broker.asset_balance,
            current_equity,
            reduce_only=signal.reason in PROTECTIVE_EXIT_REASONS,
        )
        if not decision.allowed:
            return {"status": "rejected", "reason": decision.reason}

        order = OrderRequest(
            symbol=self.config.symbol,
            side=signal.side,
            quantity=quantity,
            price=signal.price,
        )
        normalized_order, rule_reason = normalize_order(order, self.trading_rule)
        if normalized_order is None:
            return {"status": "rejected", "reason": rule_reason}
        order = normalized_order
        if self.config.mode in {"testnet", "live"}:
            return self._submit_exchange_order(order, current_equity)
        fill = self.broker.execute(order)
        return self._record_fill_result(fill, signal.price)

    def run_loop(self, max_iterations: int | None = None, sleep_seconds: float | None = None) -> dict:
        loop_id = str(uuid.uuid4())
        iteration = 0
        sleep_seconds = self.config.poll_seconds if sleep_seconds is None else sleep_seconds
        last_result: dict = {}
        consecutive_failures = 0
        lock = self.storage.acquire_loop_lock(
            self.config.mode,
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
            loop_id,
            self.config.loop_lock_stale_seconds,
        )
        if not lock["acquired"]:
            result = {"status": "error", "reason": "loop_lock_active", "lock": lock["lock"]}
            self._record_loop_event(loop_id, 0, "error", "loop lock is already active", result)
            return {"loop_id": loop_id, "iterations": 0, "last_result": result}

        try:
            while max_iterations is None or iteration < max_iterations:
                iteration += 1
                try:
                    result = self.run_once()
                    last_result = result
                    self._record_loop_event(loop_id, iteration, result.get("status", "unknown"), "", result)
                    print({"loop_id": loop_id, "iteration": iteration, **result})
                except Exception as exc:
                    last_result = {"status": "error", "reason": type(exc).__name__, "message": str(exc)}
                    self._record_loop_event(loop_id, iteration, "error", str(exc), last_result)
                    print({"loop_id": loop_id, "iteration": iteration, **last_result})

                consecutive_failures = self._next_consecutive_loop_failures(last_result, consecutive_failures)
                self.storage.heartbeat_loop_lock(
                    self.config.mode,
                    self.config.exchange,
                    self.config.symbol,
                    self.config.interval,
                    loop_id,
                )
                if self._loop_circuit_breaker_tripped(consecutive_failures):
                    control = self.storage.set_automation_paused(
                        self.config.mode,
                        self.config.exchange,
                        self.config.symbol,
                        self.config.interval,
                        True,
                        reason="loop_circuit_breaker_tripped",
                        updated_by="trade-loop",
                    )
                    last_result = {
                        "status": "error",
                        "reason": "loop_circuit_breaker_tripped",
                        "consecutive_failures": consecutive_failures,
                        "max_consecutive_loop_errors": self.config.max_consecutive_loop_errors,
                        "control": control,
                        "last_failure": last_result,
                    }
                    self._record_loop_event(
                        loop_id,
                        iteration,
                        "error",
                        "loop circuit breaker tripped",
                        last_result,
                    )
                    print({"loop_id": loop_id, "iteration": iteration, **last_result})
                    break
                if max_iterations is not None and iteration >= max_iterations:
                    break
                time.sleep(max(0.0, sleep_seconds))
        finally:
            self.storage.release_loop_lock(
                self.config.mode,
                self.config.exchange,
                self.config.symbol,
                self.config.interval,
                loop_id,
            )

        return {"loop_id": loop_id, "iterations": iteration, "last_result": last_result}

    def run_forever(self) -> None:
        self.run_loop(max_iterations=None)

    def _next_consecutive_loop_failures(self, result: dict, previous: int) -> int:
        return previous + 1 if self._loop_result_counts_as_failure(result) else 0

    def _loop_result_counts_as_failure(self, result: dict) -> bool:
        status = result.get("status")
        reason = result.get("reason")
        if status == "error":
            return True
        if status == "rejected":
            return reason not in {
                "daily_trade_limit",
                "daily_loss_limit",
                "cooldown_active",
                "max_position_exceeded",
            }
        return False

    def _loop_circuit_breaker_tripped(self, consecutive_failures: int) -> bool:
        return self.config.max_consecutive_loop_errors > 0 and consecutive_failures >= self.config.max_consecutive_loop_errors

    def backtest(self, limit: int, input_file: str | None = None, resample_interval: str | None = None) -> dict:
        candles = self._load_validation_candles(limit=limit, input_file=input_file, resample_interval=resample_interval)
        return self._record_backtest_from_candles(candles)

    def market_diagnostics(
        self,
        limit: int,
        segments: int,
        input_file: str | None = None,
        resample_interval: str | None = None,
    ) -> dict:
        candles = self._load_validation_candles(limit=limit, input_file=input_file, resample_interval=resample_interval)
        return {
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "resample_interval": resample_interval,
            "limit": limit,
            "requested_segments": max(1, segments),
            **diagnose_market(
                candles,
                segments=segments,
                fee_rate=self.config.fee_rate,
                slippage_rate=self.config.slippage_rate,
            ),
        }

    def _record_backtest_from_candles(self, candles: list[Candle]) -> dict:
        return self._evaluate_backtest_from_candles(candles, persist=True)

    def _evaluate_backtest_from_candles(self, candles: list[Candle], persist: bool = False) -> dict:
        result = self._run_backtest_engine(candles)
        run_id = str(uuid.uuid4())
        summary = BacktestRunSummary(
            run_id=run_id,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            interval=self.config.interval,
            start_time=candles[0].open_time if candles else 0,
            end_time=candles[-1].open_time if candles else 0,
            strategy=self.config.strategy,
            parameters=self._strategy_parameters(),
            candle_count=len(candles),
            initial_equity=result.initial_equity,
            final_equity=result.final_equity,
            return_pct=result.return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            win_rate=result.win_rate,
            profit_factor=result.profit_factor,
            trade_count=result.trade_count,
            fees_paid=result.fees_paid,
            slippage_paid=result.slippage_paid,
        )
        if persist:
            self.storage.record_backtest_run(summary)
            for trade in result.trades:
                self.storage.record_backtest_trade(trade, run_id=run_id)
        return {"run_id": run_id, "candle_count": len(candles), **result.model_dump()}

    def _screen_backtest_from_candles(
        self,
        candles: list[Candle],
        strategy_name: str,
        short_window: int,
        long_window: int,
        stop_loss_pct: float,
        take_profit_pct: float,
        trailing_stop_pct: float,
    ) -> dict:
        result = self._run_backtest_engine(
            candles,
            strategy_name=strategy_name,
            short_window=short_window,
            long_window=long_window,
            fee_rate=self.config.fee_rate,
            slippage_rate=self.config.slippage_rate,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
        )
        return {"run_id": "screen", "candle_count": len(candles), **result.model_dump()}

    def stress_backtest(self, limit: int, input_file: str | None = None, resample_interval: str | None = None) -> dict:
        candles = self._load_validation_candles(limit=limit, input_file=input_file, resample_interval=resample_interval)
        return self._record_stress_backtest_from_candles(candles)

    def _record_stress_backtest_from_candles(self, candles: list[Candle]) -> dict:
        return self._evaluate_stress_backtest_from_candles(candles, persist=True)

    def _evaluate_stress_backtest_from_candles(self, candles: list[Candle], persist: bool = False) -> dict:
        scenarios = []
        for fee_multiplier, slippage_multiplier in [(1.0, 1.0), (1.5, 1.0), (1.0, 1.5), (1.5, 1.5), (2.0, 2.0)]:
            result = self._run_backtest_engine(
                candles,
                fee_rate=self.config.fee_rate * fee_multiplier,
                slippage_rate=self.config.slippage_rate * slippage_multiplier,
                stop_loss_pct=self.config.stop_loss_pct,
                take_profit_pct=self.config.take_profit_pct,
                trailing_stop_pct=self.config.trailing_stop_pct,
            )
            scenario = {
                "name": f"fee_{fee_multiplier:g}x_slippage_{slippage_multiplier:g}x",
                "fee_multiplier": fee_multiplier,
                "slippage_multiplier": slippage_multiplier,
                "fee_rate": self.config.fee_rate * fee_multiplier,
                "slippage_rate": self.config.slippage_rate * slippage_multiplier,
                "trade_count": result.trade_count,
                "return_pct": result.return_pct,
                "max_drawdown_pct": result.max_drawdown_pct,
                "profit_factor": result.profit_factor,
                "win_rate": result.win_rate,
                "final_equity": result.final_equity,
                "passed": self._stress_scenario_passed(result),
            }
            scenarios.append(scenario)

        scenario_count = len(scenarios)
        passed_scenarios = sum(1 for scenario in scenarios if scenario["passed"])
        run_id = str(uuid.uuid4())
        summary = StressBacktestRunSummary(
            run_id=run_id,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            interval=self.config.interval,
            start_time=candles[0].open_time if candles else 0,
            end_time=candles[-1].open_time if candles else 0,
            strategy=self.config.strategy,
            parameters=self._strategy_parameters(),
            candle_count=len(candles),
            scenario_count=scenario_count,
            passed_scenarios=passed_scenarios,
            failed_scenarios=scenario_count - passed_scenarios,
            pass_rate=round((passed_scenarios / scenario_count) * 100 if scenario_count else 0.0, 4),
            worst_return_pct=min((scenario["return_pct"] for scenario in scenarios), default=0.0),
            worst_drawdown_pct=max((abs(scenario["max_drawdown_pct"]) for scenario in scenarios), default=0.0),
            worst_profit_factor=min((scenario["profit_factor"] for scenario in scenarios), default=0.0),
            min_trade_count=min((scenario["trade_count"] for scenario in scenarios), default=0),
            scenarios=scenarios,
        )
        if persist:
            self.storage.record_stress_backtest_run(summary)
        return summary.model_dump()

    def walk_forward(
        self,
        limit: int,
        segments: int,
        input_file: str | None = None,
        resample_interval: str | None = None,
    ) -> dict:
        candles = self._load_validation_candles(limit=limit, input_file=input_file, resample_interval=resample_interval)
        return self._record_walk_forward_from_candles(candles, segments)

    def walk_forward_samples(
        self,
        limit: int,
        segments: int,
        input_files: list[str],
        resample_interval: str | None = None,
    ) -> dict:
        resample_interval = _normalize_resample_interval(resample_interval)
        runtime_interval = _runtime_interval(self.config.interval, resample_interval)
        input_files = [input_file for input_file in input_files if input_file]
        if not input_files:
            return {
                "status": "fail",
                "reason": "no_input_files",
                "exchange": self.config.exchange,
                "symbol": self.config.symbol,
                "interval": self.config.interval,
                "source_interval": self.config.interval,
                "runtime_interval": runtime_interval,
                "resample_interval": resample_interval,
                "strategy": self.config.strategy,
                "parameters": self._strategy_parameters(),
                "limit": limit,
                "segments": segments,
                "input_files": [],
                "sample_count": 0,
                "passed_samples": 0,
                "failed_samples": 0,
                "samples": [],
            }

        sample_results: list[dict] = []
        for input_file in input_files:
            candles = self._load_validation_candles(
                limit=limit,
                input_file=input_file,
                resample_interval=resample_interval,
            )
            walk_forward = self._evaluate_walk_forward_from_candles(candles, segments)
            gate = self._walk_forward_gate_result_from_summary(walk_forward)
            sample_results.append(
                {
                    "input_file": input_file,
                    "status": "pass" if gate["allowed"] else "fail",
                    "reason": "walk_forward_gate_passed" if gate["allowed"] else gate["reason"],
                    "candle_count": len(candles),
                    "walk_forward": _compact_validation_metrics(walk_forward),
                    "gate": gate,
                    "failed_segments": [
                        segment for segment in walk_forward.get("segments", []) if not segment.get("passed")
                    ],
                    "segments": walk_forward.get("segments", []),
                }
            )

        passed_samples = sum(1 for sample in sample_results if sample["status"] == "pass")
        failed_samples = len(sample_results) - passed_samples
        return {
            "status": "pass" if failed_samples == 0 else "fail",
            "reason": "all_samples_passed" if failed_samples == 0 else "sample_walk_forward_failed",
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "source_interval": self.config.interval,
            "runtime_interval": runtime_interval,
            "resample_interval": resample_interval,
            "strategy": self.config.strategy,
            "parameters": self._strategy_parameters(),
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "sample_count": len(sample_results),
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "summary": _sample_walk_forward_summary(sample_results),
            "samples": sample_results,
        }

    def _record_walk_forward_from_candles(self, candles: list[Candle], segments: int) -> dict:
        return self._evaluate_walk_forward_from_candles(candles, segments, persist=True)

    def _evaluate_walk_forward_from_candles(self, candles: list[Candle], segments: int, persist: bool = False) -> dict:
        segments = max(1, segments)
        candle_segments = _split_candles(candles, segments)
        segment_results: list[dict] = []
        for index, segment_candles in enumerate(candle_segments, start=1):
            result = self._run_backtest_engine(segment_candles)
            segment_results.append(
                {
                    "index": index,
                    "start_time": segment_candles[0].open_time if segment_candles else 0,
                    "end_time": segment_candles[-1].open_time if segment_candles else 0,
                    "candle_count": len(segment_candles),
                    "trade_count": result.trade_count,
                    "return_pct": result.return_pct,
                    "max_drawdown_pct": result.max_drawdown_pct,
                    "profit_factor": result.profit_factor,
                    "win_rate": result.win_rate,
                    "final_equity": result.final_equity,
                    "passed": self._walk_forward_segment_passed(result),
                }
            )

        segment_count = len(segment_results)
        passed_segments = sum(1 for segment in segment_results if segment["passed"])
        run_id = str(uuid.uuid4())
        summary = WalkForwardRunSummary(
            run_id=run_id,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            interval=self.config.interval,
            start_time=candles[0].open_time if candles else 0,
            end_time=candles[-1].open_time if candles else 0,
            strategy=self.config.strategy,
            parameters=self._strategy_parameters(),
            candle_count=len(candles),
            segment_count=segment_count,
            passed_segments=passed_segments,
            failed_segments=segment_count - passed_segments,
            pass_rate=round((passed_segments / segment_count) * 100 if segment_count else 0.0, 4),
            total_trade_count=sum(segment["trade_count"] for segment in segment_results),
            min_segment_trade_count=min((segment["trade_count"] for segment in segment_results), default=0),
            worst_return_pct=min((segment["return_pct"] for segment in segment_results), default=0.0),
            worst_drawdown_pct=max((abs(segment["max_drawdown_pct"]) for segment in segment_results), default=0.0),
            worst_profit_factor=min((segment["profit_factor"] for segment in segment_results), default=0.0),
            segments=segment_results,
        )
        if persist:
            self.storage.record_walk_forward_run(summary)
        return summary.model_dump()

    def validate_strategy(
        self,
        limit: int,
        segments: int,
        input_file: str | None = None,
        resample_interval: str | None = None,
    ) -> dict:
        candles = self._load_validation_candles(limit=limit, input_file=input_file, resample_interval=resample_interval)
        required_candles = self._minimum_validation_candles(segments)
        if len(candles) < required_candles:
            return {
                "status": "fail",
                "reason": "insufficient_validation_candles",
                "exchange": self.config.exchange,
                "symbol": self.config.symbol,
                "interval": self.config.interval,
                "strategy": self.config.strategy,
                "parameters": self._strategy_parameters(),
                "limit": limit,
                "segments": segments,
                "candle_count": len(candles),
                "required_candles": required_candles,
                "gates": {
                    "data_gate": {
                        "allowed": False,
                        "reason": "insufficient_validation_candles",
                        "checks": {
                            "candle_count": len(candles),
                            "required_candles": required_candles,
                            "long_window": self.config.long_window,
                            "segments": max(1, segments),
                        },
                    }
                },
            }
        backtest = self._record_backtest_from_candles(candles)
        stress = self._record_stress_backtest_from_candles(candles)
        walk_forward = self._record_walk_forward_from_candles(candles, segments)
        gates = {
            "strategy_gate": self._strategy_gate_result_from_backtest(backtest),
            "stress_gate": self._stress_gate_result_from_summary(stress),
            "walk_forward_gate": self._walk_forward_gate_result_from_summary(walk_forward),
        }
        status = "pass" if all(gate["allowed"] for gate in gates.values()) else "fail"
        return {
            "status": status,
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "strategy": self.config.strategy,
            "parameters": self._strategy_parameters(),
            "limit": limit,
            "segments": segments,
            "candle_count": len(candles),
            "backtest": backtest,
            "stress": stress,
            "walk_forward": walk_forward,
            "gates": gates,
        }

    def validate_samples(
        self,
        limit: int,
        segments: int,
        input_files: list[str],
        resample_interval: str | None = None,
    ) -> dict:
        input_files = [input_file for input_file in input_files if input_file]
        if not input_files:
            return {
                "status": "fail",
                "reason": "no_input_files",
                "exchange": self.config.exchange,
                "symbol": self.config.symbol,
                "interval": self.config.interval,
                "strategy": self.config.strategy,
                "parameters": self._strategy_parameters(),
                "limit": limit,
                "segments": segments,
                "input_files": [],
                "resample_interval": resample_interval,
                "sample_count": 0,
                "passed_samples": 0,
                "failed_samples": 0,
                "samples": [],
            }

        samples = []
        for input_file in input_files:
            result = self.validate_strategy(
                limit=limit,
                segments=segments,
                input_file=input_file,
                resample_interval=resample_interval,
            )
            samples.append(_compact_sample_validation(input_file, result))

        passed_samples = sum(1 for sample in samples if sample.get("status") == "pass")
        failed_samples = len(samples) - passed_samples
        status = "pass" if failed_samples == 0 else "fail"
        return {
            "status": status,
            "reason": "all_samples_passed" if status == "pass" else "sample_validation_failed",
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "strategy": self.config.strategy,
            "parameters": self._strategy_parameters(),
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "resample_interval": resample_interval,
            "sample_count": len(samples),
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "summary": _sample_validation_summary(samples),
            "samples": samples,
        }

    def select_strategy(
        self,
        limit: int,
        segments: int,
        input_file: str | None,
        short_windows: list[int],
        long_windows: list[int],
        top: int,
        promote: bool = False,
        strategies: list[str] | None = None,
        stop_loss_pcts: list[float] | None = None,
        take_profit_pcts: list[float] | None = None,
        trailing_stop_pcts: list[float] | None = None,
        resample_interval: str | None = None,
    ) -> dict:
        resample_interval = _normalize_resample_interval(resample_interval)
        runtime_interval = _runtime_interval(self.config.interval, resample_interval)
        candles = self._load_validation_candles(limit=limit, input_file=input_file, resample_interval=resample_interval)
        strategy_names = strategies or [self.config.strategy]
        stop_loss_values = stop_loss_pcts or [self.config.stop_loss_pct]
        take_profit_values = take_profit_pcts or [self.config.take_profit_pct]
        trailing_stop_values = trailing_stop_pcts or [self.config.trailing_stop_pct]
        exit_combination_count = len(stop_loss_values) * len(take_profit_values) * len(trailing_stop_values)
        candidates: list[dict] = []
        prefilter: list[dict] = []
        skipped = 0
        for strategy_name in strategy_names:
            for short_window in short_windows:
                for long_window in long_windows:
                    if short_window >= long_window:
                        skipped += exit_combination_count
                        continue
                    for stop_loss_pct in stop_loss_values:
                        for take_profit_pct in take_profit_values:
                            for trailing_stop_pct in trailing_stop_values:
                                candidate_runner = TradingRunner(
                                    self.config.model_copy(
                                        update={
                                            "strategy": strategy_name,
                                            "short_window": short_window,
                                            "long_window": long_window,
                                            "stop_loss_pct": float(stop_loss_pct),
                                            "take_profit_pct": float(take_profit_pct),
                                            "trailing_stop_pct": float(trailing_stop_pct),
                                            "cooldown_seconds": self.config.cooldown_seconds,
                                            "interval": runtime_interval,
                                        }
                                    ),
                                    apply_profile=False,
                                )
                                required_candles = candidate_runner._minimum_validation_candles(segments)
                                if len(candles) < required_candles:
                                    skipped += 1
                                    candidates.append(
                                        {
                                            "status": "fail",
                                            "reason": "insufficient_validation_candles",
                                            "strategy": candidate_runner.config.strategy,
                                            "parameters": candidate_runner._strategy_parameters(),
                                            "source_interval": self.config.interval,
                                            "runtime_interval": runtime_interval,
                                            "resample_interval": resample_interval,
                                            "candle_count": len(candles),
                                            "required_candles": required_candles,
                                        }
                                    )
                                    continue
                                backtest = candidate_runner._evaluate_backtest_from_candles(candles)
                                strategy_gate = candidate_runner._strategy_gate_result_from_backtest(backtest)
                                prefilter.append(
                                    {
                                        "status": "prefilter_pass" if strategy_gate["allowed"] else "fail",
                                        "strategy": candidate_runner.config.strategy,
                                        "parameters": candidate_runner._strategy_parameters(),
                                        "source_interval": self.config.interval,
                                        "runtime_interval": runtime_interval,
                                        "resample_interval": resample_interval,
                                        "backtest": _compact_validation_metrics(backtest),
                                        "gates": {"strategy_gate": strategy_gate},
                                        "_runner": candidate_runner,
                                    }
                                )

        prefiltered_ranked = sorted(prefilter, key=_candidate_rank_key, reverse=True)
        validation_budget = max(top, 1)
        validated_count = 0
        for candidate in prefiltered_ranked:
            if validated_count >= validation_budget:
                candidate.pop("_runner", None)
                candidates.append(candidate)
                continue
            candidate_runner = candidate.pop("_runner")
            stress = candidate_runner._evaluate_stress_backtest_from_candles(candles)
            walk_forward = candidate_runner._evaluate_walk_forward_from_candles(candles, segments)
            gates = {
                **candidate["gates"],
                "stress_gate": candidate_runner._stress_gate_result_from_summary(stress),
                "walk_forward_gate": candidate_runner._walk_forward_gate_result_from_summary(walk_forward),
            }
            candidate = {
                **candidate,
                "status": "pass" if all(gate["allowed"] for gate in gates.values()) else "fail",
                "stress": _compact_validation_metrics(stress),
                "walk_forward": _compact_validation_metrics(walk_forward),
                "gates": gates,
            }
            candidates.append(candidate)
            validated_count += 1

        ranked = sorted(candidates, key=_candidate_rank_key, reverse=True)
        selected = next((candidate for candidate in ranked if candidate.get("status") == "pass"), None)
        if selected and promote:
            selected = self._persist_selected_validation(selected, candles, segments)
        promoted = self._promote_strategy_profile(selected, updated_by="select-strategy") if selected and promote else None
        return {
            "status": "pass" if selected else "fail",
            "reason": "selected_strategy_found" if selected else "no_candidate_passed_validation",
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "source_interval": self.config.interval,
            "runtime_interval": runtime_interval,
            "strategies": strategy_names,
            "stop_loss_pcts": stop_loss_values,
            "take_profit_pcts": take_profit_values,
            "trailing_stop_pcts": trailing_stop_values,
            "limit": limit,
            "resample_interval": resample_interval,
            "segments": segments,
            "candle_count": len(candles),
            "total_combinations": len(strategy_names) * len(short_windows) * len(long_windows) * exit_combination_count,
            "skipped_combinations": skipped,
            "validated_candidates": validated_count,
            "selected": selected,
            "promoted": promoted,
            "candidates": ranked[:top],
        }

    def select_samples(
        self,
        limit: int,
        segments: int,
        input_files: list[str],
        short_windows: list[int],
        long_windows: list[int],
        top: int,
        promote: bool = False,
        strategies: list[str] | None = None,
        stop_loss_pcts: list[float] | None = None,
        take_profit_pcts: list[float] | None = None,
        trailing_stop_pcts: list[float] | None = None,
        resample_interval: str | None = None,
    ) -> dict:
        resample_interval = _normalize_resample_interval(resample_interval)
        runtime_interval = _runtime_interval(self.config.interval, resample_interval)
        input_files = [input_file for input_file in input_files if input_file]
        strategy_names = strategies or [self.config.strategy]
        stop_loss_values = stop_loss_pcts or [self.config.stop_loss_pct]
        take_profit_values = take_profit_pcts or [self.config.take_profit_pct]
        trailing_stop_values = trailing_stop_pcts or [self.config.trailing_stop_pct]
        exit_combination_count = len(stop_loss_values) * len(take_profit_values) * len(trailing_stop_values)
        total_combinations = len(strategy_names) * len(short_windows) * len(long_windows) * exit_combination_count
        if not input_files:
            return {
                "status": "fail",
                "reason": "no_input_files",
                "exchange": self.config.exchange,
                "symbol": self.config.symbol,
                "interval": self.config.interval,
                "source_interval": self.config.interval,
                "runtime_interval": runtime_interval,
                "strategies": strategy_names,
                "stop_loss_pcts": stop_loss_values,
                "take_profit_pcts": take_profit_values,
                "trailing_stop_pcts": trailing_stop_values,
                "limit": limit,
                "resample_interval": resample_interval,
                "segments": segments,
                "input_files": [],
                "sample_count": 0,
                "total_combinations": total_combinations,
                "skipped_combinations": 0,
                "validated_candidates": 0,
                "selected": None,
                "promoted": None,
                "candidates": [],
            }

        sample_inputs = [
            {
                "input_file": input_file,
                "candles": self._load_validation_candles(
                    limit=limit,
                    input_file=input_file,
                    resample_interval=resample_interval,
                ),
            }
            for input_file in input_files
        ]
        candidates: list[dict] = []
        prefilter: list[dict] = []
        skipped = 0
        for strategy_name in strategy_names:
            for short_window in short_windows:
                for long_window in long_windows:
                    if short_window >= long_window:
                        skipped += exit_combination_count
                        continue
                    for stop_loss_pct in stop_loss_values:
                        for take_profit_pct in take_profit_values:
                            for trailing_stop_pct in trailing_stop_values:
                                candidate_runner = TradingRunner(
                                    self.config.model_copy(
                                        update={
                                            "strategy": strategy_name,
                                            "short_window": short_window,
                                            "long_window": long_window,
                                            "stop_loss_pct": float(stop_loss_pct),
                                            "take_profit_pct": float(take_profit_pct),
                                            "trailing_stop_pct": float(trailing_stop_pct),
                                            "cooldown_seconds": self.config.cooldown_seconds,
                                            "interval": runtime_interval,
                                        }
                                    ),
                                    apply_profile=False,
                                )
                                required_candles = candidate_runner._minimum_validation_candles(segments)
                                samples: list[dict] = []
                                for sample in sample_inputs:
                                    input_file = str(sample["input_file"])
                                    candles = sample["candles"]
                                    if len(candles) < required_candles:
                                        samples.append(
                                            {
                                                "input_file": input_file,
                                                "status": "fail",
                                                "reason": "insufficient_validation_candles",
                                                "candle_count": len(candles),
                                                "required_candles": required_candles,
                                                "gates": {
                                                    "data_gate": {
                                                        "allowed": False,
                                                        "reason": "insufficient_validation_candles",
                                                        "checks": {
                                                            "candle_count": len(candles),
                                                            "required_candles": required_candles,
                                                            "long_window": candidate_runner.config.long_window,
                                                            "segments": max(1, segments),
                                                        },
                                                    }
                                                },
                                            }
                                        )
                                        continue
                                    backtest = candidate_runner._evaluate_backtest_from_candles(candles)
                                    strategy_gate = candidate_runner._strategy_gate_result_from_backtest(backtest)
                                    samples.append(
                                        {
                                            "input_file": input_file,
                                            "status": "prefilter_pass" if strategy_gate["allowed"] else "fail",
                                            "reason": "strategy_gate_passed" if strategy_gate["allowed"] else strategy_gate["reason"],
                                            "candle_count": len(candles),
                                            "backtest": _compact_validation_metrics(backtest),
                                            "gates": {"strategy_gate": strategy_gate},
                                        }
                                    )

                                passed_samples = sum(1 for sample in samples if sample.get("status") == "prefilter_pass")
                                failed_samples = len(samples) - passed_samples
                                candidate = {
                                    "status": "prefilter_pass" if failed_samples == 0 else "fail",
                                    "reason": "prefilter_passed" if failed_samples == 0 else "sample_prefilter_failed",
                                    "strategy": candidate_runner.config.strategy,
                                    "parameters": candidate_runner._strategy_parameters(),
                                    "source_interval": self.config.interval,
                                    "runtime_interval": runtime_interval,
                                    "resample_interval": resample_interval,
                                    "sample_count": len(samples),
                                    "passed_samples": passed_samples,
                                    "failed_samples": failed_samples,
                                    "summary": _sample_validation_summary(samples),
                                    "failed_sample_examples": _failed_sample_examples(samples),
                                    "samples": samples,
                                }
                                if failed_samples:
                                    if any(sample.get("reason") == "insufficient_validation_candles" for sample in samples):
                                        skipped += 1
                                    candidates.append(candidate)
                                    continue
                                candidate["_runner"] = candidate_runner
                                prefilter.append(candidate)

        prefiltered_ranked = sorted(prefilter, key=_multi_sample_candidate_rank_key, reverse=True)
        validation_budget = max(top, 1)
        validated_count = 0
        for candidate in prefiltered_ranked:
            if validated_count >= validation_budget:
                candidate.pop("_runner", None)
                candidates.append(candidate)
                continue
            candidate_runner = candidate.pop("_runner")
            validated_samples: list[dict] = []
            for sample_input, sample in zip(sample_inputs, candidate["samples"]):
                candles = sample_input["candles"]
                stress = candidate_runner._evaluate_stress_backtest_from_candles(candles)
                walk_forward = candidate_runner._evaluate_walk_forward_from_candles(candles, segments)
                gates = {
                    **sample["gates"],
                    "stress_gate": candidate_runner._stress_gate_result_from_summary(stress),
                    "walk_forward_gate": candidate_runner._walk_forward_gate_result_from_summary(walk_forward),
                }
                sample_status = "pass" if all(gate["allowed"] for gate in gates.values()) else "fail"
                validated_samples.append(
                    {
                        **sample,
                        "status": sample_status,
                        "reason": "all_gates_passed" if sample_status == "pass" else "sample_validation_failed",
                        "stress": _compact_validation_metrics(stress),
                        "walk_forward": _compact_validation_metrics(walk_forward),
                        "gates": gates,
                    }
                )
            passed_samples = sum(1 for sample in validated_samples if sample.get("status") == "pass")
            failed_samples = len(validated_samples) - passed_samples
            candidate = {
                **candidate,
                "status": "pass" if failed_samples == 0 else "fail",
                "reason": "all_samples_passed" if failed_samples == 0 else "sample_validation_failed",
                "passed_samples": passed_samples,
                "failed_samples": failed_samples,
                "summary": _sample_validation_summary(validated_samples),
                "samples": validated_samples,
            }
            candidates.append(candidate)
            validated_count += 1

        ranked = sorted(candidates, key=_multi_sample_candidate_rank_key, reverse=True)
        selected = next((candidate for candidate in ranked if candidate.get("status") == "pass"), None)
        if selected and promote:
            selected = self._persist_selected_sample_validation(selected, sample_inputs, segments)
        promoted = (
            self._promote_strategy_profile(selected, updated_by="select-samples")
            if selected and promote and selected.get("status") == "pass"
            else None
        )
        return {
            "status": "pass" if selected else "fail",
            "reason": "selected_strategy_found" if selected else "no_candidate_passed_validation",
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "source_interval": self.config.interval,
            "runtime_interval": runtime_interval,
            "strategies": strategy_names,
            "stop_loss_pcts": stop_loss_values,
            "take_profit_pcts": take_profit_values,
            "trailing_stop_pcts": trailing_stop_values,
            "limit": limit,
            "resample_interval": resample_interval,
            "segments": segments,
            "input_files": input_files,
            "sample_count": len(sample_inputs),
            "total_combinations": total_combinations,
            "skipped_combinations": skipped,
            "validated_candidates": validated_count,
            "selected": selected,
            "promoted": promoted,
            "candidates": ranked[:top],
        }

    def screen_samples(
        self,
        limit: int,
        segments: int,
        input_files: list[str],
        short_windows: list[int],
        long_windows: list[int],
        top: int,
        resample_intervals: list[str | None],
        strategies: list[str] | None = None,
        stop_loss_pcts: list[float] | None = None,
        take_profit_pcts: list[float] | None = None,
        trailing_stop_pcts: list[float] | None = None,
        max_combinations: int | None = None,
        skip_combinations: int = 0,
        screen_min_trades: int | None = None,
    ) -> dict:
        intervals = _dedupe_resample_intervals(resample_intervals)
        input_files = [input_file for input_file in input_files if input_file]
        strategy_names = strategies or [self.config.strategy]
        stop_loss_values = stop_loss_pcts or [self.config.stop_loss_pct]
        take_profit_values = take_profit_pcts or [self.config.take_profit_pct]
        trailing_stop_values = trailing_stop_pcts or [self.config.trailing_stop_pct]
        skip_combinations = max(0, skip_combinations)
        exit_combination_count = len(stop_loss_values) * len(take_profit_values) * len(trailing_stop_values)
        total_combinations = (
            len(intervals)
            * len(strategy_names)
            * len(short_windows)
            * len(long_windows)
            * exit_combination_count
        )
        base = {
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "source_interval": self.config.interval,
            "resample_intervals": intervals,
            "strategies": strategy_names,
            "stop_loss_pcts": stop_loss_values,
            "take_profit_pcts": take_profit_values,
            "trailing_stop_pcts": trailing_stop_values,
            "limit": limit,
            "segments": segments,
            "input_files": input_files,
            "sample_count": len(input_files),
            "short_windows": short_windows,
            "long_windows": long_windows,
            "top": top,
            "total_combinations": total_combinations,
            "max_combinations": max_combinations,
            "skip_combinations": skip_combinations,
            "screen_min_trades": screen_min_trades,
            "validated_candidates": 0,
            "screen_only": True,
        }
        if not intervals:
            return {
                **base,
                "status": "fail",
                "reason": "no_resample_intervals",
                "runtime_interval": None,
                "skipped_combinations": 0,
                "prefilter_pass_count": 0,
                "selected": None,
                "intervals": [],
                "candidates": [],
            }
        if not input_files:
            return {
                **base,
                "status": "fail",
                "reason": "no_input_files",
                "runtime_interval": None,
                "skipped_combinations": 0,
                "prefilter_pass_count": 0,
                "selected": None,
                "intervals": [],
                "candidates": [],
            }

        try:
            raw_sample_inputs = [
                {"input_file": input_file, "candles": self.market_data.load_klines_from_file(input_file)}
                for input_file in input_files
            ]
        except (FileNotFoundError, MarketDataError) as exc:
            return {
                **base,
                "status": "fail",
                "reason": "input_file_load_failed",
                "runtime_interval": None,
                "skipped_combinations": 0,
                "skipped_by_offset": 0,
                "seen_combinations": 0,
                "evaluated_combinations": 0,
                "budget_exhausted": False,
                "prefilter_pass_count": 0,
                "selected": None,
                "intervals": [],
                "candidates": [],
                "error": str(exc),
            }
        candidates: list[dict] = []
        interval_summaries: list[dict] = []
        skipped = 0
        seen_combinations = 0
        evaluated_combinations = 0
        skipped_by_offset = 0
        budget_exhausted = False
        for resample_interval in intervals:
            if budget_exhausted:
                break
            runtime_interval = _runtime_interval(self.config.interval, resample_interval)
            sample_inputs: list[dict] = []
            for sample in raw_sample_inputs:
                candles = list(sample["candles"])
                if resample_interval:
                    candles = aggregate_candles(candles, resample_interval)
                if limit > 0:
                    candles = candles[-limit:]
                sample_inputs.append({"input_file": sample["input_file"], "candles": candles})
            evaluation_sample_inputs = sorted(
                sample_inputs,
                key=lambda sample: sample["candles"][-1].open_time if sample["candles"] else 0,
                reverse=True,
            )

            interval_candidates: list[dict] = []
            for strategy_name in strategy_names:
                if budget_exhausted:
                    break
                for short_window in short_windows:
                    if budget_exhausted:
                        break
                    for long_window in long_windows:
                        if budget_exhausted:
                            break
                        if short_window >= long_window:
                            skipped += exit_combination_count
                            continue
                        for stop_loss_pct in stop_loss_values:
                            if budget_exhausted:
                                break
                            for take_profit_pct in take_profit_values:
                                if budget_exhausted:
                                    break
                                for trailing_stop_pct in trailing_stop_values:
                                    if seen_combinations < skip_combinations:
                                        seen_combinations += 1
                                        skipped_by_offset += 1
                                        continue
                                    if max_combinations is not None and evaluated_combinations >= max_combinations:
                                        budget_exhausted = True
                                        break
                                    seen_combinations += 1
                                    evaluated_combinations += 1
                                    parameters = strategy_parameters(
                                        strategy_name,
                                        short_window,
                                        long_window,
                                        float(stop_loss_pct),
                                        float(take_profit_pct),
                                        float(trailing_stop_pct),
                                        self.config.cooldown_seconds,
                                    )
                                    required_candles = max(1, segments) * (long_window + 1)
                                    samples: list[dict] = []
                                    for sample in evaluation_sample_inputs:
                                        input_file = str(sample["input_file"])
                                        candles = sample["candles"]
                                        if len(candles) < required_candles:
                                            samples.append(
                                                {
                                                    "input_file": input_file,
                                                    "status": "fail",
                                                    "reason": "insufficient_validation_candles",
                                                    "candle_count": len(candles),
                                                    "required_candles": required_candles,
                                                    "gates": {
                                                        "data_gate": {
                                                            "allowed": False,
                                                            "reason": "insufficient_validation_candles",
                                                            "checks": {
                                                                "candle_count": len(candles),
                                                                "required_candles": required_candles,
                                                                "long_window": long_window,
                                                                "segments": max(1, segments),
                                                            },
                                                        }
                                                    },
                                                }
                                            )
                                            break
                                        backtest = self._screen_backtest_from_candles(
                                            candles,
                                            strategy_name=strategy_name,
                                            short_window=short_window,
                                            long_window=long_window,
                                            stop_loss_pct=float(stop_loss_pct),
                                            take_profit_pct=float(take_profit_pct),
                                            trailing_stop_pct=float(trailing_stop_pct),
                                        )
                                        strategy_gate = self._strategy_gate_result_from_backtest(
                                            backtest,
                                            min_trade_count=screen_min_trades,
                                        )
                                        samples.append(
                                            {
                                                "input_file": input_file,
                                                "status": "prefilter_pass" if strategy_gate["allowed"] else "fail",
                                                "reason": "strategy_gate_passed"
                                                if strategy_gate["allowed"]
                                                else strategy_gate["reason"],
                                                "candle_count": len(candles),
                                                "backtest": _compact_validation_metrics(backtest),
                                                "gates": {"strategy_gate": strategy_gate},
                                            }
                                        )
                                        if not strategy_gate["allowed"]:
                                            break

                                    passed_samples = sum(1 for sample in samples if sample.get("status") == "prefilter_pass")
                                    failed_samples = len(samples) - passed_samples
                                    if any(sample.get("reason") == "insufficient_validation_candles" for sample in samples):
                                        skipped += 1
                                    candidate = {
                                        "status": "prefilter_pass" if failed_samples == 0 else "fail",
                                        "reason": "prefilter_passed" if failed_samples == 0 else "sample_prefilter_failed",
                                        "strategy": strategy_name,
                                        "parameters": parameters,
                                        "source_interval": self.config.interval,
                                        "runtime_interval": runtime_interval,
                                        "resample_interval": resample_interval,
                                        "sample_count": len(samples),
                                        "evaluated_sample_count": len(samples),
                                        "total_sample_count": len(sample_inputs),
                                        "passed_samples": passed_samples,
                                        "failed_samples": failed_samples,
                                        "screen_min_trades": screen_min_trades,
                                        "summary": _sample_validation_summary(samples),
                                        "failed_sample_examples": _failed_sample_examples(samples),
                                        "samples": samples,
                                    }
                                    candidates.append(candidate)
                                    interval_candidates.append(candidate)

            interval_ranked = sorted(interval_candidates, key=_screen_candidate_rank_key, reverse=True)
            best_candidate = _screen_interval_best_candidate(interval_ranked[0]) if interval_ranked else None
            interval_pass_count = sum(1 for candidate in interval_candidates if candidate.get("status") == "prefilter_pass")
            interval_summaries.append(
                {
                    "status": "pass" if interval_pass_count else "fail",
                    "reason": "prefilter_candidate_found" if interval_pass_count else "no_candidate_passed_prefilter",
                    "source_interval": self.config.interval,
                    "runtime_interval": runtime_interval,
                    "resample_interval": resample_interval,
                    "sample_count": len(sample_inputs),
                    "candle_counts": [len(sample["candles"]) for sample in sample_inputs],
                    "candidate_count": len(interval_candidates),
                    "prefilter_pass_count": interval_pass_count,
                    "best_candidate": best_candidate,
                }
            )

        ranked = sorted(candidates, key=_screen_candidate_rank_key, reverse=True)
        selected = next((candidate for candidate in ranked if candidate.get("status") == "prefilter_pass"), None)
        return {
            **base,
            "status": "pass" if selected else "fail",
            "reason": "prefilter_candidate_found" if selected else "no_candidate_passed_prefilter",
            "runtime_interval": selected.get("runtime_interval") if selected else None,
            "skipped_combinations": skipped,
            "skipped_by_offset": skipped_by_offset,
            "seen_combinations": seen_combinations,
            "evaluated_combinations": evaluated_combinations,
            "budget_exhausted": budget_exhausted,
            "prefilter_pass_count": sum(1 for candidate in candidates if candidate.get("status") == "prefilter_pass"),
            "selected": selected,
            "intervals": sorted(interval_summaries, key=_screen_interval_rank_key, reverse=True),
            "candidates": ranked[:top],
            "next_steps": [
                "rerun the selected candidate with select-samples for stress and walk-forward validation before promotion"
            ]
            if selected
            else ["expand the strategy, interval, or sample grid; do not promote failed prefilter candidates"],
        }

    def select_sample_intervals(
        self,
        limit: int,
        segments: int,
        input_files: list[str],
        short_windows: list[int],
        long_windows: list[int],
        top: int,
        resample_intervals: list[str | None],
        promote: bool = False,
        strategies: list[str] | None = None,
        stop_loss_pcts: list[float] | None = None,
        take_profit_pcts: list[float] | None = None,
        trailing_stop_pcts: list[float] | None = None,
    ) -> dict:
        intervals = _dedupe_resample_intervals(resample_intervals)
        strategy_names = strategies or [self.config.strategy]
        stop_loss_values = stop_loss_pcts or [self.config.stop_loss_pct]
        take_profit_values = take_profit_pcts or [self.config.take_profit_pct]
        trailing_stop_values = trailing_stop_pcts or [self.config.trailing_stop_pct]
        if not intervals:
            return {
                "status": "fail",
                "reason": "no_resample_intervals",
                "exchange": self.config.exchange,
                "symbol": self.config.symbol,
                "source_interval": self.config.interval,
                "resample_intervals": [],
                "limit": limit,
                "segments": segments,
                "input_files": [input_file for input_file in input_files if input_file],
                "short_windows": short_windows,
                "long_windows": long_windows,
                "strategies": strategy_names,
                "stop_loss_pcts": stop_loss_values,
                "take_profit_pcts": take_profit_values,
                "trailing_stop_pcts": trailing_stop_values,
                "top": top,
                "promote": promote,
                "passing_interval_count": 0,
                "selected_interval": None,
                "promoted": None,
                "intervals": [],
            }

        interval_results = [
            self.select_samples(
                limit=limit,
                segments=segments,
                input_files=input_files,
                short_windows=short_windows,
                long_windows=long_windows,
                top=top,
                promote=False,
                strategies=strategy_names,
                stop_loss_pcts=stop_loss_values,
                take_profit_pcts=take_profit_values,
                trailing_stop_pcts=trailing_stop_values,
                resample_interval=resample_interval,
            )
            for resample_interval in intervals
        ]
        ranked = sorted(interval_results, key=_sample_interval_rank_key, reverse=True)
        selected_index = next(
            (index for index, result in enumerate(interval_results) if result.get("status") == "pass" and result is ranked[0]),
            None,
        )
        selected_result = ranked[0] if ranked and ranked[0].get("status") == "pass" else None
        if selected_result is not None and promote:
            promoted_result = self.select_samples(
                limit=limit,
                segments=segments,
                input_files=input_files,
                short_windows=short_windows,
                long_windows=long_windows,
                top=top,
                promote=True,
                strategies=strategy_names,
                stop_loss_pcts=stop_loss_values,
                take_profit_pcts=take_profit_values,
                trailing_stop_pcts=trailing_stop_values,
                resample_interval=selected_result.get("resample_interval"),
            )
            if selected_index is None:
                selected_index = interval_results.index(selected_result)
            interval_results[selected_index] = promoted_result
            ranked = sorted(interval_results, key=_sample_interval_rank_key, reverse=True)
            selected_result = ranked[0] if ranked and ranked[0].get("status") == "pass" else promoted_result

        return {
            "status": "pass" if selected_result and selected_result.get("status") == "pass" else "fail",
            "reason": "selected_interval_found" if selected_result and selected_result.get("status") == "pass" else "no_interval_passed_validation",
            "exchange": self.config.exchange,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "source_interval": self.config.interval,
            "runtime_interval": selected_result.get("runtime_interval") if selected_result else None,
            "resample_intervals": intervals,
            "limit": limit,
            "segments": segments,
            "input_files": [input_file for input_file in input_files if input_file],
            "short_windows": short_windows,
            "long_windows": long_windows,
            "strategies": strategy_names,
            "stop_loss_pcts": stop_loss_values,
            "take_profit_pcts": take_profit_values,
            "trailing_stop_pcts": trailing_stop_values,
            "top": top,
            "promote": promote,
            "passing_interval_count": sum(1 for result in interval_results if result.get("status") == "pass"),
            "selected_interval": selected_result,
            "promoted": selected_result.get("promoted") if selected_result else None,
            "intervals": ranked[:top],
        }

    def _persist_selected_validation(self, selected: dict, candles: list[Candle], segments: int) -> dict:
        candidate_runner = TradingRunner(
            self.config.model_copy(
                update={
                    "strategy": selected["strategy"],
                    "short_window": int(selected["parameters"]["short_window"]),
                    "long_window": int(selected["parameters"]["long_window"]),
                    "stop_loss_pct": float(selected["parameters"].get("stop_loss_pct", 0.0)),
                    "take_profit_pct": float(selected["parameters"].get("take_profit_pct", 0.0)),
                    "trailing_stop_pct": float(selected["parameters"].get("trailing_stop_pct", 0.0)),
                    "cooldown_seconds": int(selected["parameters"].get("cooldown_seconds", 0)),
                    "interval": str(selected.get("runtime_interval") or self.config.interval),
                }
            ),
            apply_profile=False,
        )
        backtest = candidate_runner._record_backtest_from_candles(candles)
        stress = candidate_runner._record_stress_backtest_from_candles(candles)
        walk_forward = candidate_runner._record_walk_forward_from_candles(candles, segments)
        gates = {
            "strategy_gate": candidate_runner._strategy_gate_result_from_backtest(backtest),
            "stress_gate": candidate_runner._stress_gate_result_from_summary(stress),
            "walk_forward_gate": candidate_runner._walk_forward_gate_result_from_summary(walk_forward),
        }
        return {
            **selected,
            "status": "pass" if all(gate["allowed"] for gate in gates.values()) else "fail",
            "backtest": _compact_validation_metrics(backtest),
            "stress": _compact_validation_metrics(stress),
            "walk_forward": _compact_validation_metrics(walk_forward),
            "gates": gates,
        }

    def _persist_selected_sample_validation(self, selected: dict, sample_inputs: list[dict], segments: int) -> dict:
        persisted_samples: list[dict] = []
        last_persisted: dict = {}
        for sample in sample_inputs:
            persisted = self._persist_selected_validation(selected, sample["candles"], segments)
            last_persisted = persisted
            persisted_samples.append(
                {
                    "input_file": str(sample["input_file"]),
                    "status": persisted["status"],
                    "reason": "all_gates_passed" if persisted["status"] == "pass" else "sample_validation_failed",
                    "candle_count": len(sample["candles"]),
                    "backtest": persisted["backtest"],
                    "stress": persisted["stress"],
                    "walk_forward": persisted["walk_forward"],
                    "gates": persisted["gates"],
                }
            )
        passed_samples = sum(1 for sample in persisted_samples if sample.get("status") == "pass")
        failed_samples = len(persisted_samples) - passed_samples
        status = "pass" if failed_samples == 0 else "fail"
        return {
            **selected,
            "status": status,
            "reason": "all_samples_passed" if status == "pass" else "sample_validation_failed",
            "sample_count": len(persisted_samples),
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "summary": _sample_validation_summary(persisted_samples),
            "samples": persisted_samples,
            "backtest": last_persisted.get("backtest", {}),
            "stress": last_persisted.get("stress", {}),
            "walk_forward": last_persisted.get("walk_forward", {}),
            "gates": last_persisted.get("gates", {}),
        }

    def _promote_strategy_profile(self, selected: dict | None, updated_by: str = "operator") -> dict | None:
        if selected is None:
            return None
        if selected.get("strategy") in RESEARCH_ONLY_STRATEGIES or selected.get("parameters", {}).get("research_only"):
            return {
                "status": "blocked",
                "reason": "research_only_strategy_not_promotable",
                "strategy": selected.get("strategy"),
                "parameters": selected.get("parameters", {}),
            }
        profile_interval = str(selected.get("runtime_interval") or self.config.interval)
        evidence = {
            "backtest": selected.get("backtest", {}),
            "stress": selected.get("stress", {}),
            "walk_forward": selected.get("walk_forward", {}),
            "gates": selected.get("gates", {}),
            "source_interval": selected.get("source_interval", self.config.interval),
            "runtime_interval": profile_interval,
            "resample_interval": selected.get("resample_interval"),
        }
        if selected.get("samples") is not None:
            evidence["sample_validation"] = {
                "status": selected.get("status"),
                "reason": selected.get("reason"),
                "sample_count": selected.get("sample_count"),
                "passed_samples": selected.get("passed_samples"),
                "failed_samples": selected.get("failed_samples"),
                "summary": selected.get("summary", {}),
                "samples": selected.get("samples", []),
                "source_interval": selected.get("source_interval", self.config.interval),
                "runtime_interval": profile_interval,
                "resample_interval": selected.get("resample_interval"),
            }
        return self.storage.upsert_strategy_profile(
            mode=self.config.mode,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            interval=profile_interval,
            strategy=str(selected.get("strategy") or self.config.strategy),
            parameters=selected.get("parameters", {}),
            evidence=evidence,
            updated_by=updated_by,
        )

    def download_history(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit_per_request: int | None,
        sleep_seconds: float,
    ) -> dict:
        candles = self.market_data.fetch_historical_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            limit_per_request=limit_per_request,
            sleep_seconds=sleep_seconds,
        )
        changed_rows = self.storage.upsert_candles(candles, self.config.exchange, symbol, interval)
        return {
            "status": "ok",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "downloaded_candles": len(candles),
            "changed_rows": changed_rows,
            "first_open_time": candles[0].open_time if candles else None,
            "last_open_time": candles[-1].open_time if candles else None,
        }

    def import_candles(self, input_file: str, symbol: str, interval: str) -> dict:
        candles = self.market_data.load_klines_from_file(input_file)
        changed_rows = self.storage.upsert_candles(candles, self.config.exchange, symbol, interval)
        return {
            "status": "ok",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "input_file": input_file,
            "imported_candles": len(candles),
            "changed_rows": changed_rows,
            "first_open_time": candles[0].open_time if candles else None,
            "last_open_time": candles[-1].open_time if candles else None,
        }

    def import_candle_archives(
        self,
        input_dir: str,
        symbol: str,
        interval: str,
        pattern: str = "*.zip",
        recursive: bool = False,
    ) -> dict:
        input_path = Path(input_dir)
        files = _archive_input_files(input_path, pattern, recursive)
        if not files:
            return {
                "status": "fail",
                "reason": "no_archive_files",
                "exchange": self.config.exchange,
                "symbol": symbol,
                "interval": interval,
                "input_dir": str(input_path),
                "pattern": pattern,
                "recursive": recursive,
                "file_count": 0,
                "imported_file_count": 0,
                "failed_file_count": 0,
                "imported_candles": 0,
                "changed_rows": 0,
                "first_open_time": None,
                "last_open_time": None,
                "files": [],
            }

        results: list[dict] = []
        for file_path in files:
            try:
                results.append(self.import_candles(str(file_path), symbol, interval))
            except MarketDataError as exc:
                results.append(
                    {
                        "status": "error",
                        "input_file": str(file_path),
                        "reason": str(exc),
                    }
                )

        successful = [result for result in results if result.get("status") == "ok"]
        failed = [result for result in results if result.get("status") != "ok"]
        first_times = [result["first_open_time"] for result in successful if result.get("first_open_time") is not None]
        last_times = [result["last_open_time"] for result in successful if result.get("last_open_time") is not None]
        status = "ok" if not failed else "partial" if successful else "fail"
        return {
            "status": status,
            "reason": "archives_imported" if status == "ok" else "some_archives_failed",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "input_dir": str(input_path),
            "pattern": pattern,
            "recursive": recursive,
            "file_count": len(results),
            "imported_file_count": len(successful),
            "failed_file_count": len(failed),
            "imported_candles": sum(int(result.get("imported_candles", 0)) for result in successful),
            "changed_rows": sum(int(result.get("changed_rows", 0)) for result in successful),
            "first_open_time": min(first_times) if first_times else None,
            "last_open_time": max(last_times) if last_times else None,
            "files": results,
        }

    def prepare_samples(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        sample_days: int,
        output_dir: str,
        source: str = "auto",
        limit_per_request: int | None = None,
        sleep_seconds: float = 0.0,
        min_candles: int = 1,
    ) -> dict:
        if start_time >= end_time:
            return {"status": "fail", "reason": "invalid_time_range", "start_time": start_time, "end_time": end_time}

        source = str(source).lower()
        sample_days = max(1, int(sample_days))
        min_candles = max(1, int(min_candles))
        sample_ms = sample_days * 86_400_000
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        local_candles = self.storage.load_candles(self.config.exchange, symbol, interval, start_time=start_time, end_time=end_time)
        download = None
        source_used = "sqlite"
        if source == "exchange" or (source == "auto" and _needs_sample_download(local_candles, start_time, end_time, interval)):
            fetched = self.market_data.fetch_historical_klines(
                symbol=symbol,
                interval=interval,
                start_time=start_time,
                end_time=end_time,
                limit_per_request=limit_per_request,
                sleep_seconds=sleep_seconds,
            )
            changed_rows = self.storage.upsert_candles(fetched, self.config.exchange, symbol, interval)
            download = {
                "downloaded_candles": len(fetched),
                "changed_rows": changed_rows,
                "first_open_time": fetched[0].open_time if fetched else None,
                "last_open_time": fetched[-1].open_time if fetched else None,
            }
            local_candles = self.storage.load_candles(
                self.config.exchange,
                symbol,
                interval,
                start_time=start_time,
                end_time=end_time,
            )
            source_used = "exchange"

        candles = [candle for candle in local_candles if start_time <= candle.open_time < end_time]
        samples = []
        skipped = []
        cursor = start_time
        while cursor < end_time:
            window_end = min(cursor + sample_ms, end_time)
            window_candles = [candle for candle in candles if cursor <= candle.open_time < window_end]
            if len(window_candles) >= min_candles:
                file_path = output_path / _sample_file_name(self.config.exchange, symbol, interval, cursor, window_end)
                _write_candle_csv(file_path, window_candles)
                samples.append(
                    {
                        "input_file": str(file_path),
                        "start_time": cursor,
                        "end_time": window_end,
                        "candle_count": len(window_candles),
                        "first_open_time": window_candles[0].open_time,
                        "last_open_time": window_candles[-1].open_time,
                    }
                )
            else:
                skipped.append(
                    {
                        "start_time": cursor,
                        "end_time": window_end,
                        "candle_count": len(window_candles),
                        "reason": "insufficient_candles",
                    }
                )
            cursor = window_end

        input_files = [sample["input_file"] for sample in samples]
        status = "ok" if input_files else "fail"
        return {
            "status": status,
            "reason": "samples_prepared" if status == "ok" else "no_samples_prepared",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "source_requested": source,
            "source_used": source_used,
            "start_time": start_time,
            "end_time": end_time,
            "sample_days": sample_days,
            "min_candles": min_candles,
            "output_dir": str(output_path),
            "local_candle_count": len(candles),
            "sample_count": len(samples),
            "skipped_window_count": len(skipped),
            "download": download,
            "input_files": input_files,
            "input_files_arg": ",".join(input_files),
            "next_command": _sample_selection_command(input_files),
            "samples": samples,
            "skipped_windows": skipped,
        }

    def research_strategy(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        sample_days: int,
        output_dir: str,
        source: str,
        limit_per_request: int | None,
        sleep_seconds: float,
        min_candles: int,
        limit: int,
        segments: int,
        short_windows: list[int],
        long_windows: list[int],
        top: int,
        resample_intervals: list[str | None],
        promote: bool = False,
        strategies: list[str] | None = None,
        stop_loss_pcts: list[float] | None = None,
        take_profit_pcts: list[float] | None = None,
        trailing_stop_pcts: list[float] | None = None,
    ) -> dict:
        prepare = self.prepare_samples(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            sample_days=sample_days,
            output_dir=output_dir,
            source=source,
            limit_per_request=limit_per_request,
            sleep_seconds=sleep_seconds,
            min_candles=min_candles,
        )
        if prepare.get("status") != "ok":
            return {
                "status": "fail",
                "reason": "sample_preparation_failed",
                "exchange": self.config.exchange,
                "symbol": symbol,
                "interval": interval,
                "prepare": prepare,
                "selection": None,
                "ready_for_promotion": False,
                "promoted": None,
                "summary": _research_summary(prepare, None),
                "next_steps": ["prepare more historical samples before selecting a strategy"],
            }

        selection = self.select_sample_intervals(
            limit=limit,
            segments=segments,
            input_files=list(prepare.get("input_files", [])),
            short_windows=short_windows,
            long_windows=long_windows,
            top=top,
            resample_intervals=resample_intervals,
            promote=promote,
            strategies=strategies,
            stop_loss_pcts=stop_loss_pcts,
            take_profit_pcts=take_profit_pcts,
            trailing_stop_pcts=trailing_stop_pcts,
        )
        ready = selection.get("status") == "pass"
        return {
            "status": "pass" if ready else "fail",
            "reason": "strategy_research_passed" if ready else "strategy_research_failed",
            "exchange": self.config.exchange,
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "sample_days": sample_days,
            "limit": limit,
            "segments": segments,
            "short_windows": short_windows,
            "long_windows": long_windows,
            "resample_intervals": _dedupe_resample_intervals(resample_intervals),
            "strategies": strategies or [self.config.strategy],
            "stop_loss_pcts": stop_loss_pcts or [self.config.stop_loss_pct],
            "take_profit_pcts": take_profit_pcts or [self.config.take_profit_pct],
            "trailing_stop_pcts": trailing_stop_pcts or [self.config.trailing_stop_pct],
            "promote_requested": promote,
            "ready_for_promotion": ready,
            "promoted": selection.get("promoted"),
            "prepare": prepare,
            "selection": selection,
            "summary": _research_summary(prepare, selection),
            "next_steps": _research_next_steps(selection, promote),
        }

    def batch_backtest(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        short_windows: list[int],
        long_windows: list[int],
        sort_by: str,
        top: int,
    ) -> dict:
        result = run_batch_backtest(
            config=self.config,
            storage=self.storage,
            exchange=self.config.exchange,
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            short_windows=short_windows,
            long_windows=long_windows,
            sort_by=sort_by,
            top=top,
        )
        return result.model_dump()

    def _create_risk_manager(self) -> RiskManager:
        return RiskManager(
            risk_per_trade=self.config.risk_per_trade,
            max_position_usdt=self.config.max_position_usdt,
            min_order_usdt=self.config.min_order_usdt,
            max_daily_trades=self.config.max_daily_trades,
            max_daily_loss_usdt=self.config.max_daily_loss_usdt,
            cooldown_seconds=self.config.cooldown_seconds,
            allow_sell_without_position=self.config.allow_sell_without_position,
        )

    def _load_trading_rule(self):
        stored = self.storage.latest_trading_rule(self.config.exchange, self.config.symbol)
        if stored is not None:
            return default_trading_rule(self.config).model_copy(
                update={
                    "price_step": float(stored["price_step"]),
                    "quantity_step": float(stored["quantity_step"]),
                    "min_quantity": float(stored["min_quantity"]),
                    "min_notional": float(stored["min_notional"]),
                }
            )
        rule = default_trading_rule(self.config)
        self.storage.upsert_trading_rule(rule)
        return rule

    def _restore_broker_state(self) -> None:
        if self.config.mode not in {"paper", "testnet", "live"}:
            return
        balances = self.storage.replay_position_state(
            mode=self.config.mode,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            starting_usdt=self.config.starting_usdt,
        )
        self.broker.usdt_balance = balances["usdt_balance"]
        self.broker.asset_balance = max(0.0, balances["asset_balance"])
        self.average_entry_price = max(0.0, balances["average_entry_price"])

    def _replay_local_position_state(self) -> None:
        balances = self.storage.replay_position_state(
            mode=self.config.mode,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            starting_usdt=self.config.starting_usdt,
        )
        self.average_entry_price = max(0.0, balances["average_entry_price"])

    def _restore_risk_state(self) -> None:
        state = self.storage.latest_risk_state(
            self.config.mode,
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
        )
        if state is None:
            return
        self.risk.trades_today = int(state.get("trades_today") or 0)
        self.risk.day_key = state.get("day_key")
        self.risk.start_equity = state.get("start_equity")
        self.risk.last_fill_timestamp = state.get("last_fill_timestamp")

    def _submit_exchange_order(self, order: OrderRequest, current_equity: float) -> dict:
        enabled, disabled_reason = self._exchange_autotrade_enabled()
        if not enabled:
            rejected = ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=disabled_reason,
            )
            self.storage.record_exchange_order(rejected, mode=self.config.mode, exchange=self.config.exchange)
            return rejected.model_dump()

        live_gate = self._live_order_gate(order)
        if not live_gate["allowed"]:
            rejected = ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=live_gate["reason"],
            )
            self.storage.record_exchange_order(rejected, mode=self.config.mode, exchange=self.config.exchange)
            return {**rejected.model_dump(), "live_gate": live_gate}

        gate = self._strategy_gate()
        if not gate["allowed"]:
            rejected = ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=gate["reason"],
            )
            self.storage.record_exchange_order(rejected, mode=self.config.mode, exchange=self.config.exchange)
            return {**rejected.model_dump(), "strategy_gate": gate}

        sample_validation_gate = self._sample_validation_gate()
        if not sample_validation_gate["allowed"]:
            rejected = ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=sample_validation_gate["reason"],
            )
            self.storage.record_exchange_order(rejected, mode=self.config.mode, exchange=self.config.exchange)
            return {**rejected.model_dump(), "sample_validation_gate": sample_validation_gate}

        stress_gate = self._stress_gate()
        if not stress_gate["allowed"]:
            rejected = ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=stress_gate["reason"],
            )
            self.storage.record_exchange_order(rejected, mode=self.config.mode, exchange=self.config.exchange)
            return {**rejected.model_dump(), "stress_gate": stress_gate}

        walk_forward_gate = self._walk_forward_gate()
        if not walk_forward_gate["allowed"]:
            rejected = ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=walk_forward_gate["reason"],
            )
            self.storage.record_exchange_order(rejected, mode=self.config.mode, exchange=self.config.exchange)
            return {**rejected.model_dump(), "walk_forward_gate": walk_forward_gate}

        open_orders = self.storage.list_open_exchange_orders(self.config.mode, self.config.exchange, order.symbol)
        if open_orders:
            return {
                "status": "idle",
                "reason": "open_exchange_order_exists",
                "exchange_order_id": open_orders[0].get("exchange_order_id", ""),
            }

        exchange_order = self.broker.submit_order(order)
        self.storage.record_exchange_order(exchange_order, mode=self.config.mode, exchange=self.config.exchange)
        if exchange_order.status in {"submitted", "partially_filled", "filled"}:
            # Count accepted exchange orders for cooldown and daily risk limits even before a final fill arrives.
            self.risk.record_fill(equity=current_equity)
            self._record_risk_state()
        if exchange_order.status == "filled":
            fill = Fill(
                symbol=exchange_order.symbol,
                side=exchange_order.side or order.side,
                quantity=exchange_order.quantity,
                price=exchange_order.price or order.price,
                status="filled",
                reason=exchange_order.reason,
            )
            self._apply_broker_fill(fill)
            self.storage.record_fill(fill, mode=self.config.mode, exchange=self.config.exchange)
            self._apply_filled_position_update(fill)
        return exchange_order.model_dump()

    def _submit_testnet_order(self, order: OrderRequest, current_equity: float) -> dict:
        return self._submit_exchange_order(order, current_equity)

    def _exchange_autotrade_enabled(self) -> tuple[bool, str]:
        if self.config.mode == "testnet":
            return self.config.enable_testnet_autotrade, "testnet_autotrade_disabled"
        if self.config.mode == "live":
            if not self.config.allow_live:
                return False, "live_not_allowed"
            if self.config.live_dry_run:
                return False, "live_dry_run_enabled"
            if not self.config.enable_live_autotrade:
                return False, "live_autotrade_disabled"
            if not self.config.live_credentials_confirmed:
                return False, "live_credentials_not_confirmed"
            if self.config.use_testnet:
                return False, "live_endpoint_points_to_testnet"
            if self.config.live_confirmation != expected_live_confirmation(self.config):
                return False, "live_confirmation_required"
            return True, ""
        return False, "exchange_autotrade_mode_required"

    def _live_order_gate(self, order: OrderRequest) -> dict:
        if self.config.mode != "live":
            return {"allowed": True, "reason": "not_live_mode"}
        checks = {
            "mode": self.config.mode,
            "allow_live": self.config.allow_live,
            "live_dry_run": self.config.live_dry_run,
            "enable_live_autotrade": self.config.enable_live_autotrade,
            "live_credentials_confirmed": self.config.live_credentials_confirmed,
            "use_testnet": self.config.use_testnet,
            "order_notional": round(order.quantity * order.price, 8),
            "max_live_order_usdt": self.config.max_live_order_usdt,
            "exchange": self.config.exchange,
            "max_live_canary_order_usdt": 5.0 if self.config.exchange == "bitget" else self.config.max_live_order_usdt,
        }
        if self.config.use_testnet:
            return {"allowed": False, "reason": "live_endpoint_points_to_testnet", "checks": checks}
        limit = checks["max_live_canary_order_usdt"]
        if checks["order_notional"] > limit:
            return {"allowed": False, "reason": "live_order_notional_exceeds_limit", "checks": checks}
        return {"allowed": True, "reason": "live_order_gate_passed", "checks": checks}

    def _strategy_gate(self) -> dict:
        if not self.config.require_strategy_gate:
            return {"allowed": True, "reason": "strategy_gate_disabled"}

        run = self.storage.latest_backtest_run(
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
            self.config.short_window,
            self.config.long_window,
            parameters=self._strategy_parameters(),
            strategy=self.config.strategy,
        )
        if run is None:
            return {"allowed": False, "reason": "strategy_gate_missing_backtest"}

        metrics = run.get("metrics", {})
        return self._strategy_gate_result_from_backtest({"run_id": run["run_id"], **metrics})

    def _sample_validation_gate(self) -> dict:
        if not self.config.require_sample_validation_gate:
            return {"allowed": True, "reason": "sample_validation_gate_disabled"}

        profile = self.storage.active_strategy_profile(
            self.config.mode,
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
        )
        if profile is None:
            return {"allowed": False, "reason": "sample_validation_gate_missing_profile"}
        evidence = profile.get("evidence", {}).get("sample_validation")
        if not isinstance(evidence, dict):
            return {"allowed": False, "reason": "sample_validation_gate_missing_evidence"}

        sample_count = int(_metric(evidence, "sample_count", 0))
        passed_samples = int(_metric(evidence, "passed_samples", 0))
        failed_samples = int(_metric(evidence, "failed_samples", 0))
        summary = evidence.get("summary", {}) if isinstance(evidence.get("summary"), dict) else {}
        checks = {
            "status": evidence.get("status"),
            "sample_count": sample_count,
            "passed_samples": passed_samples,
            "failed_samples": failed_samples,
            "total_trade_count": int(_metric(summary, "total_trade_count", 0)),
            "min_return_pct": _metric(summary, "min_return_pct", 0),
            "min_profit_factor": _metric(summary, "min_profit_factor", 0),
            "min_stress_pass_rate": _metric(summary, "min_stress_pass_rate", 0),
            "min_walk_forward_pass_rate": _metric(summary, "min_walk_forward_pass_rate", 0),
        }
        if evidence.get("status") != "pass":
            return {"allowed": False, "reason": "sample_validation_gate_not_passed", "checks": checks}
        if sample_count < 1:
            return {"allowed": False, "reason": "sample_validation_gate_no_samples", "checks": checks}
        if failed_samples > 0 or passed_samples < sample_count:
            return {"allowed": False, "reason": "sample_validation_gate_failed_samples", "checks": checks}
        if checks["total_trade_count"] < self.config.min_gate_trades:
            return {"allowed": False, "reason": "sample_validation_gate_insufficient_trades", "checks": checks}
        if checks["min_return_pct"] < self.config.min_gate_return_pct:
            return {"allowed": False, "reason": "sample_validation_gate_return_too_low", "checks": checks}
        if checks["min_profit_factor"] < self.config.min_gate_profit_factor:
            return {"allowed": False, "reason": "sample_validation_gate_profit_factor_too_low", "checks": checks}
        if checks["min_stress_pass_rate"] < self.config.min_stress_pass_rate:
            return {"allowed": False, "reason": "sample_validation_gate_stress_pass_rate_too_low", "checks": checks}
        if checks["min_walk_forward_pass_rate"] < self.config.min_walk_forward_pass_rate:
            return {"allowed": False, "reason": "sample_validation_gate_walk_forward_pass_rate_too_low", "checks": checks}
        return {"allowed": True, "reason": "sample_validation_gate_passed", "checks": checks}

    def _stress_gate(self) -> dict:
        if not self.config.require_stress_gate:
            return {"allowed": True, "reason": "stress_gate_disabled"}

        run = self.storage.latest_stress_backtest_run(
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
            self.config.short_window,
            self.config.long_window,
            parameters=self._strategy_parameters(),
            strategy=self.config.strategy,
        )
        if run is None:
            return {"allowed": False, "reason": "stress_gate_missing_backtest"}

        metrics = run.get("metrics", {})
        return self._stress_gate_result_from_summary({"run_id": run["run_id"], **metrics})

    def _stress_scenario_passed(self, result) -> bool:
        return (
            result.trade_count >= self.config.min_gate_trades
            and result.return_pct >= self.config.min_gate_return_pct
            and abs(result.max_drawdown_pct) <= self.config.max_stress_drawdown_pct
            and result.profit_factor >= self.config.min_gate_profit_factor
        )

    def _walk_forward_gate(self) -> dict:
        if not self.config.require_walk_forward_gate:
            return {"allowed": True, "reason": "walk_forward_gate_disabled"}

        run = self.storage.latest_walk_forward_run(
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
            self.config.short_window,
            self.config.long_window,
            parameters=self._strategy_parameters(),
            strategy=self.config.strategy,
        )
        if run is None:
            return {"allowed": False, "reason": "walk_forward_gate_missing_run"}

        metrics = run.get("metrics", {})
        return self._walk_forward_gate_result_from_summary({"run_id": run["run_id"], **metrics})

    def _strategy_gate_result_from_backtest(self, result: dict, min_trade_count: int | None = None) -> dict:
        trade_count = int(_metric(result, "trade_count", 0))
        return_pct = _metric(result, "return_pct", 0)
        drawdown_pct = abs(_metric(result, "max_drawdown_pct", 0))
        profit_factor = _metric(result, "profit_factor", 0)
        required_trade_count = self.config.min_gate_trades if min_trade_count is None else max(0, int(min_trade_count))
        checks = {
            "trade_count": trade_count,
            "min_trade_count": required_trade_count,
            "return_pct": return_pct,
            "max_drawdown_pct": drawdown_pct,
            "profit_factor": profit_factor,
        }
        run_id = result.get("run_id", "")
        if trade_count < required_trade_count:
            return {"allowed": False, "reason": "strategy_gate_insufficient_trades", "run_id": run_id, "checks": checks}
        if return_pct < self.config.min_gate_return_pct:
            return {"allowed": False, "reason": "strategy_gate_return_too_low", "run_id": run_id, "checks": checks}
        if drawdown_pct > self.config.max_gate_drawdown_pct:
            return {"allowed": False, "reason": "strategy_gate_drawdown_too_high", "run_id": run_id, "checks": checks}
        if profit_factor < self.config.min_gate_profit_factor:
            return {"allowed": False, "reason": "strategy_gate_profit_factor_too_low", "run_id": run_id, "checks": checks}
        return {"allowed": True, "reason": "strategy_gate_passed", "run_id": run_id, "checks": checks}

    def _stress_gate_result_from_summary(self, result: dict) -> dict:
        pass_rate = _metric(result, "pass_rate", 0)
        min_trade_count = int(_metric(result, "min_trade_count", 0))
        worst_return_pct = _metric(result, "worst_return_pct", 0)
        worst_drawdown_pct = abs(_metric(result, "worst_drawdown_pct", 0))
        worst_profit_factor = _metric(result, "worst_profit_factor", 0)
        checks = {
            "pass_rate": pass_rate,
            "min_trade_count": min_trade_count,
            "worst_return_pct": worst_return_pct,
            "worst_drawdown_pct": worst_drawdown_pct,
            "worst_profit_factor": worst_profit_factor,
        }
        run_id = result.get("run_id", "")
        if pass_rate < self.config.min_stress_pass_rate:
            return {"allowed": False, "reason": "stress_gate_pass_rate_too_low", "run_id": run_id, "checks": checks}
        if min_trade_count < self.config.min_gate_trades:
            return {"allowed": False, "reason": "stress_gate_insufficient_trades", "run_id": run_id, "checks": checks}
        if worst_return_pct < self.config.min_gate_return_pct:
            return {"allowed": False, "reason": "stress_gate_return_too_low", "run_id": run_id, "checks": checks}
        if worst_drawdown_pct > self.config.max_stress_drawdown_pct:
            return {"allowed": False, "reason": "stress_gate_drawdown_too_high", "run_id": run_id, "checks": checks}
        if worst_profit_factor < self.config.min_gate_profit_factor:
            return {"allowed": False, "reason": "stress_gate_profit_factor_too_low", "run_id": run_id, "checks": checks}
        return {"allowed": True, "reason": "stress_gate_passed", "run_id": run_id, "checks": checks}

    def _walk_forward_gate_result_from_summary(self, result: dict) -> dict:
        segment_count = int(_metric(result, "segment_count", 0))
        pass_rate = _metric(result, "pass_rate", 0)
        total_trade_count = int(_metric(result, "total_trade_count", 0))
        worst_return_pct = _metric(result, "worst_return_pct", 0)
        worst_drawdown_pct = abs(_metric(result, "worst_drawdown_pct", 0))
        worst_profit_factor = _metric(result, "worst_profit_factor", 0)
        checks = {
            "segment_count": segment_count,
            "pass_rate": pass_rate,
            "total_trade_count": total_trade_count,
            "worst_return_pct": worst_return_pct,
            "worst_drawdown_pct": worst_drawdown_pct,
            "worst_profit_factor": worst_profit_factor,
        }
        run_id = result.get("run_id", "")
        if segment_count < self.config.min_walk_forward_segments:
            return {"allowed": False, "reason": "walk_forward_gate_insufficient_segments", "run_id": run_id, "checks": checks}
        if pass_rate < self.config.min_walk_forward_pass_rate:
            return {"allowed": False, "reason": "walk_forward_gate_pass_rate_too_low", "run_id": run_id, "checks": checks}
        if total_trade_count < self.config.min_walk_forward_trades:
            return {"allowed": False, "reason": "walk_forward_gate_insufficient_trades", "run_id": run_id, "checks": checks}
        if worst_return_pct < self.config.min_gate_return_pct:
            return {"allowed": False, "reason": "walk_forward_gate_return_too_low", "run_id": run_id, "checks": checks}
        if worst_drawdown_pct > self.config.max_gate_drawdown_pct:
            return {"allowed": False, "reason": "walk_forward_gate_drawdown_too_high", "run_id": run_id, "checks": checks}
        if worst_profit_factor < self.config.min_gate_profit_factor:
            return {"allowed": False, "reason": "walk_forward_gate_profit_factor_too_low", "run_id": run_id, "checks": checks}
        return {"allowed": True, "reason": "walk_forward_gate_passed", "run_id": run_id, "checks": checks}

    def _walk_forward_segment_passed(self, result: BacktestResult) -> bool:
        if result.trade_count == 0:
            return (
                result.return_pct >= self.config.min_gate_return_pct
                and abs(result.max_drawdown_pct) <= self.config.max_gate_drawdown_pct
            )
        return (
            result.return_pct >= self.config.min_gate_return_pct
            and abs(result.max_drawdown_pct) <= self.config.max_gate_drawdown_pct
            and result.profit_factor >= self.config.min_gate_profit_factor
        )

    def _load_validation_candles(
        self,
        limit: int,
        input_file: str | None = None,
        resample_interval: str | None = None,
    ) -> list[Candle]:
        if input_file:
            candles = self.market_data.load_klines_from_file(input_file)
            if resample_interval:
                candles = aggregate_candles(candles, resample_interval)
            return candles[-limit:] if limit > 0 else candles
        candles = self.market_data.fetch_klines(self.config.symbol, self.config.interval, limit=limit)
        if resample_interval:
            candles = aggregate_candles(candles, resample_interval)
        return candles[-limit:] if limit > 0 else candles

    def _minimum_validation_candles(self, segments: int) -> int:
        return max(1, segments) * (self.config.long_window + 1)

    def _run_backtest_engine(
        self,
        candles: list[Candle],
        strategy_name: str | None = None,
        short_window: int | None = None,
        long_window: int | None = None,
        fee_rate: float | None = None,
        slippage_rate: float | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        trailing_stop_pct: float | None = None,
    ) -> BacktestResult:
        strategy_name = strategy_name or self.config.strategy
        strategy = (
            self.strategy
            if strategy_name == self.config.strategy
            and short_window is None
            and long_window is None
            else create_strategy(
                strategy_name,
                short_window=short_window or self.config.short_window,
                long_window=long_window or self.config.long_window,
                symbol=self.config.symbol,
            )
        )
        fee_rate = self.config.fee_rate if fee_rate is None else fee_rate
        slippage_rate = self.config.slippage_rate if slippage_rate is None else slippage_rate
        stop_loss_pct = self.config.stop_loss_pct if stop_loss_pct is None else stop_loss_pct
        take_profit_pct = self.config.take_profit_pct if take_profit_pct is None else take_profit_pct
        trailing_stop_pct = self.config.trailing_stop_pct if trailing_stop_pct is None else trailing_stop_pct
        if strategy_name in SYNTHETIC_SHORT_STRATEGIES:
            engine = SyntheticShortBacktestEngine(
                strategy,
                self._create_risk_manager(),
                self.config.starting_usdt,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                trailing_stop_pct=trailing_stop_pct,
            )
            return engine.run(candles, self.config.symbol)
        engine = BacktestEngine(
            strategy,
            self._create_risk_manager(),
            PaperBroker(self.config.starting_usdt),
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
        )
        return engine.run(candles, self.config.symbol)

    def _refresh_exchange_open_orders(self) -> dict:
        enabled, disabled_reason = self._exchange_autotrade_enabled()
        if not enabled:
            return {"status": "idle", "reason": disabled_reason, "refreshed": False}

        open_orders = self.storage.list_open_exchange_orders(self.config.mode, self.config.exchange, self.config.symbol)
        updates: list[dict] = []
        for order in open_orders:
            order_id = str(order.get("exchange_order_id") or "")
            if not order_id:
                continue
            updated = self.broker.order_status(self.config.symbol, order_id)
            self.storage.record_exchange_order(updated, mode=self.config.mode, exchange=self.config.exchange)
            updates.append(updated.model_dump())
            if updated.status == "filled":
                fill = Fill(
                    symbol=updated.symbol,
                    side=updated.side or order.get("side") or "buy",
                    quantity=updated.quantity or float(order.get("quantity") or 0),
                    price=updated.price or float(order.get("price") or 0),
                    status="filled",
                    reason=updated.reason,
                )
                self._apply_broker_fill(fill)
                self.storage.record_fill(fill, mode=self.config.mode, exchange=self.config.exchange)
                self._apply_filled_position_update(fill)

        if not updates:
            return {"status": "idle", "reason": "no_open_exchange_orders", "refreshed": False}

        remaining = self.storage.list_open_exchange_orders(self.config.mode, self.config.exchange, self.config.symbol)
        return {
            "status": "idle" if remaining else "synced",
            "reason": "open_exchange_orders_refreshed",
            "refreshed": True,
            "updated_orders": updates,
            "open_order_count": len(remaining),
        }

    def _refresh_testnet_open_orders(self) -> dict:
        return self._refresh_exchange_open_orders()

    def _sync_exchange_account_balances(self) -> dict | None:
        enabled, _disabled_reason = self._exchange_autotrade_enabled()
        if not enabled:
            return None
        account = self.broker.account_balance(self.config.symbol)
        if account.status != "synced":
            return {
                **account.model_dump(),
                "status": "rejected",
                "reason": account.reason or "account_sync_failed",
            }
        self.broker.usdt_balance = max(0.0, account.usdt_balance)
        self.broker.asset_balance = max(0.0, account.asset_balance)
        if self.broker.asset_balance <= 0:
            self.average_entry_price = 0.0
            self._reset_trailing_peak()
        elif self.average_entry_price <= 0:
            sync_result = self.sync_exchange_fills()
            if sync_result["status"] == "synced" and self.average_entry_price > 0:
                return account.model_dump()
            return {
                **account.model_dump(),
                "status": "rejected",
                "reason": "missing_local_entry_price",
                "fill_sync": sync_result,
            }
        return account.model_dump()

    def _sync_testnet_account_balances(self) -> dict | None:
        return self._sync_exchange_account_balances()

    def sync_exchange_fills(self, limit: int = 500) -> dict:
        if self.config.mode not in {"testnet", "live"}:
            return {"status": "idle", "reason": "testnet_or_live_mode_required", "imported_fills": 0, "seen_fills": 0}
        history = self.broker.trade_history(self.config.symbol, limit=limit)
        if isinstance(history, list):
            fills = history
            history_status = "synced"
            history_reason = ""
        else:
            fills = history.fills
            history_status = history.status
            history_reason = history.reason
        if history_status != "synced":
            return {
                "status": "rejected",
                "reason": history_reason or "trade_history_sync_failed",
                "symbol": self.config.symbol,
                "seen_fills": 0,
                "imported_fills": 0,
                "average_entry_price": self.average_entry_price,
            }
        imported = 0
        for fill in sorted(fills, key=lambda item: item.timestamp or 0):
            if fill.status != "filled":
                continue
            if self.storage.record_fill_if_new(fill, mode=self.config.mode, exchange=self.config.exchange):
                imported += 1
        if fills:
            self._replay_local_position_state()
            self._restore_position_runtime_state()
        return {
            "status": "synced",
            "symbol": self.config.symbol,
            "seen_fills": len(fills),
            "imported_fills": imported,
            "average_entry_price": self.average_entry_price,
        }

    def _record_fill_result(self, fill: Fill, mark_price: float) -> dict:
        if fill.status == "filled":
            equity = self.broker.usdt_balance + self.broker.asset_balance * mark_price
            self.risk.record_fill(equity=equity)
            self._apply_filled_position_update(fill)
        self.storage.record_fill(fill, mode=self.config.mode, exchange=self.config.exchange)
        self._record_risk_state()
        return fill.model_dump()

    def _protective_exit_signal(self, mark_price: float) -> Signal | None:
        if self.broker.asset_balance <= 0 or self.average_entry_price <= 0:
            self._reset_trailing_peak()
            return None
        self._sync_trailing_peak(mark_price)
        stop_loss_pct = self.config.stop_loss_pct
        take_profit_pct = self.config.take_profit_pct
        trailing_stop_pct = self.config.trailing_stop_pct
        if stop_loss_pct > 0:
            stop_price = self.average_entry_price * (1 - stop_loss_pct / 100)
            if mark_price <= stop_price:
                return self._strategy_signal("sell", mark_price, "stop_loss_triggered")
        if take_profit_pct > 0:
            take_profit_price = self.average_entry_price * (1 + take_profit_pct / 100)
            if mark_price >= take_profit_price:
                return self._strategy_signal("sell", mark_price, "take_profit_triggered")
        if trailing_stop_pct > 0 and self.trailing_peak_price > self.average_entry_price:
            trailing_stop_price = self.trailing_peak_price * (1 - trailing_stop_pct / 100)
            if mark_price <= trailing_stop_price:
                return self._strategy_signal("sell", mark_price, "trailing_stop_triggered")
        return None

    def _strategy_signal(self, side: str, price: float, reason: str) -> Signal:
        return Signal(symbol=self.config.symbol, side=side, price=price, reason=reason)

    def _restore_position_runtime_state(self) -> None:
        state = self.storage.position_runtime_state(
            self.config.mode,
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
        )
        if self.broker.asset_balance > 0 and self.average_entry_price > 0:
            self.trailing_peak_price = max(
                self.average_entry_price,
                float(state.get("trailing_peak_price") or 0.0),
            )
        else:
            self.trailing_peak_price = 0.0

    def _sync_trailing_peak(self, mark_price: float) -> None:
        next_peak = max(self.trailing_peak_price, self.average_entry_price, mark_price)
        if next_peak > self.trailing_peak_price:
            self.trailing_peak_price = next_peak
            self.storage.update_position_runtime_state(
                self.config.mode,
                self.config.exchange,
                self.config.symbol,
                self.config.interval,
                self.trailing_peak_price,
            )

    def _reset_trailing_peak(self) -> None:
        if self.trailing_peak_price <= 0:
            return
        self.trailing_peak_price = 0.0
        self.storage.reset_position_runtime_state(
            self.config.mode,
            self.config.exchange,
            self.config.symbol,
            self.config.interval,
        )

    def _apply_filled_position_update(self, fill: Fill) -> None:
        self._update_average_entry_price(fill)
        if fill.side == "buy" and self.broker.asset_balance > 0:
            self.trailing_peak_price = max(self.trailing_peak_price, self.average_entry_price, fill.price)
            self.storage.update_position_runtime_state(
                self.config.mode,
                self.config.exchange,
                self.config.symbol,
                self.config.interval,
                self.trailing_peak_price,
            )
        elif fill.side == "sell" and self.broker.asset_balance <= 0:
            self._reset_trailing_peak()

    def _apply_broker_fill(self, fill: Fill) -> None:
        if fill.status != "filled":
            return
        notional = fill.quantity * fill.price
        if fill.side == "buy":
            self.broker.usdt_balance -= notional
            self.broker.asset_balance += fill.quantity
        elif fill.side == "sell":
            self.broker.usdt_balance += notional
            self.broker.asset_balance = max(0.0, self.broker.asset_balance - fill.quantity)

    def _update_average_entry_price(self, fill: Fill) -> None:
        if fill.side == "buy":
            total_quantity = self.broker.asset_balance
            previous_quantity = max(0.0, total_quantity - fill.quantity)
            previous_cost = previous_quantity * self.average_entry_price
            total_cost = previous_cost + fill.quantity * fill.price
            self.average_entry_price = total_cost / total_quantity if total_quantity > 0 else 0.0
        elif fill.side == "sell" and self.broker.asset_balance <= 0:
            self.average_entry_price = 0.0

    def _strategy_parameters(self) -> dict:
        parameters = strategy_parameters(
            self.config.strategy,
            self.config.short_window,
            self.config.long_window,
            self.config.stop_loss_pct,
            self.config.take_profit_pct,
            self.config.trailing_stop_pct,
            self.config.cooldown_seconds,
        )
        if self.config.strategy in SYNTHETIC_SHORT_STRATEGIES:
            parameters["position_mode"] = "synthetic_short"
            parameters["research_only"] = True
        return parameters

    def _record_risk_state(self) -> None:
        self.storage.record_risk_state(
            self.risk,
            mode=self.config.mode,
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            interval=self.config.interval,
        )

    def _record_loop_event(
        self,
        loop_id: str,
        iteration: int,
        status: str,
        message: str,
        payload: dict,
    ) -> None:
        self.storage.record_loop_event(
            LoopEvent(
                loop_id=loop_id,
                iteration=iteration,
                status=status,
                mode=self.config.mode,
                exchange=self.config.exchange,
                symbol=self.config.symbol,
                interval=self.config.interval,
                message=message,
                payload=payload,
            )
        )


def _metric(metrics: dict, key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _normalize_resample_interval(interval: str | None) -> str | None:
    if interval is None:
        return None
    value = str(interval).strip()
    if not value or value.lower() in {"raw", "none", "native", "source"}:
        return None
    return value


def _dedupe_resample_intervals(intervals: list[str | None]) -> list[str | None]:
    output: list[str | None] = []
    seen: set[str] = set()
    for interval in intervals:
        normalized = _normalize_resample_interval(interval)
        key = normalized or ""
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _runtime_interval(source_interval: str, resample_interval: str | None) -> str:
    return resample_interval or source_interval


def _needs_sample_download(candles: list[Candle], start_time: int, end_time: int, interval: str) -> bool:
    if not candles:
        return True
    interval_ms = interval_to_milliseconds(interval)
    return candles[0].open_time > start_time or candles[-1].open_time < end_time - interval_ms


def _sample_file_name(exchange: str, symbol: str, interval: str, start_time: int, end_time: int) -> str:
    start_label = _date_label(start_time)
    end_label = _date_label(max(start_time, end_time - 1))
    return f"{exchange}-{symbol}-{interval}-{start_label}_{end_label}.csv"


def _date_label(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _write_candle_csv(path: Path, candles: list[Candle]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "close_time"])
        for candle in candles:
            writer.writerow(
                [
                    candle.open_time,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.close_time,
                ]
            )


def _sample_selection_command(input_files: list[str]) -> str:
    if not input_files:
        return ""
    return (
        "kxian-bot select-sample-intervals "
        f"--input-files {','.join(input_files)} "
        "--resample-intervals raw,5m,15m,30m,1h "
        "--strategies moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion,momentum_breakout,bollinger_mean_reversion,regime_breakout,trend_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,downtrend_breakdown_short "
        "--short-windows 3,5,8 --long-windows 12,20,30 "
        "--stop-loss-pcts 0,1,2 --take-profit-pcts 0,2,4 --trailing-stop-pcts 0,1.5 "
        "--segments 6 --top 10"
    )


def _archive_input_files(input_path: Path, pattern: str, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.exists():
        return []
    iterator = input_path.rglob(pattern) if recursive else input_path.glob(pattern)
    return sorted(path for path in iterator if path.is_file())


def _research_next_steps(selection: dict, promote: bool) -> list[str]:
    if selection.get("status") == "pass":
        if promote and selection.get("promoted"):
            return [
                "run readiness to confirm the promoted profile gates",
                "run testnet-dry-run before enabling any longer testnet loop",
            ]
        return [
            "rerun research-strategy with --promote if this candidate is acceptable",
            "run readiness and testnet-dry-run after promotion",
        ]
    return [
        "do not promote this sample set",
        "add more historical samples or broaden the candidate grid",
        "review selection.candidates for the least-bad failure modes",
    ]


def _research_summary(prepare: dict, selection: dict | None) -> dict:
    summary = {
        "prepare_status": prepare.get("status"),
        "prepare_reason": prepare.get("reason"),
        "sample_count": int(_metric(prepare, "sample_count", 0)),
        "skipped_window_count": int(_metric(prepare, "skipped_window_count", 0)),
        "local_candle_count": int(_metric(prepare, "local_candle_count", 0)),
        "input_file_count": len(prepare.get("input_files") or []),
    }
    if selection is None:
        return {
            **summary,
            "status": "fail",
            "reason": "sample_preparation_failed",
            "passing_interval_count": 0,
            "selected_runtime_interval": None,
            "best_candidate": None,
            **_research_decision_fields(
                "fail",
                _top_counts(_research_prepare_failures(prepare)),
                None,
                prepare,
            ),
        }

    candidates = _research_candidates(selection)
    best_candidate = candidates[0] if candidates else None
    top_failure_reasons = _top_counts(_research_failure_reasons(selection))
    return {
        **summary,
        "status": selection.get("status"),
        "reason": selection.get("reason"),
        "passing_interval_count": int(_metric(selection, "passing_interval_count", 0)),
        "selected_runtime_interval": (selection.get("selected_interval") or {}).get("runtime_interval"),
        "best_candidate": _compact_research_candidate(best_candidate) if best_candidate else None,
        **_research_decision_fields(selection.get("status"), top_failure_reasons, best_candidate, prepare),
    }


def _research_candidates(selection: dict) -> list[dict]:
    candidates: list[dict] = []
    for interval in selection.get("intervals") or []:
        for candidate in interval.get("candidates") or []:
            candidates.append(
                {
                    **candidate,
                    "interval_status": interval.get("status"),
                    "interval_reason": interval.get("reason"),
                    "source_interval": candidate.get("source_interval") or interval.get("source_interval"),
                    "runtime_interval": candidate.get("runtime_interval") or interval.get("runtime_interval"),
                    "resample_interval": candidate.get("resample_interval", interval.get("resample_interval")),
                }
            )
    selected_interval = selection.get("selected_interval") or {}
    selected = selected_interval.get("selected")
    if isinstance(selected, dict):
        candidates.append(
            {
                **selected,
                "interval_status": selected_interval.get("status"),
                "interval_reason": selected_interval.get("reason"),
                "source_interval": selected.get("source_interval") or selected_interval.get("source_interval"),
                "runtime_interval": selected.get("runtime_interval") or selected_interval.get("runtime_interval"),
                "resample_interval": selected.get("resample_interval", selected_interval.get("resample_interval")),
            }
        )
    return sorted(candidates, key=_multi_sample_candidate_rank_key, reverse=True)


def _compact_research_candidate(candidate: dict) -> dict:
    summary = candidate.get("summary") if isinstance(candidate.get("summary"), dict) else {}
    compact = {
        "status": candidate.get("status"),
        "reason": candidate.get("reason"),
        "strategy": candidate.get("strategy"),
        "parameters": candidate.get("parameters"),
        "source_interval": candidate.get("source_interval"),
        "runtime_interval": candidate.get("runtime_interval"),
        "resample_interval": candidate.get("resample_interval"),
        "sample_count": candidate.get("sample_count"),
        "passed_samples": candidate.get("passed_samples"),
        "failed_samples": candidate.get("failed_samples"),
        "summary": summary,
    }
    failed_samples = [
        _compact_research_sample(sample)
        for sample in candidate.get("samples") or []
        if sample.get("status") not in {"pass", "prefilter_pass"}
    ][:3]
    if failed_samples:
        compact["failed_sample_examples"] = failed_samples
    return {key: value for key, value in compact.items() if value is not None}


def _compact_research_sample(sample: dict) -> dict:
    compact = {
        "input_file": sample.get("input_file"),
        "status": sample.get("status"),
        "reason": sample.get("reason"),
        "candle_count": sample.get("candle_count"),
        "required_candles": sample.get("required_candles"),
        "failed_gates": _failed_gate_reasons(sample.get("gates") or {}),
    }
    return {key: value for key, value in compact.items() if value not in (None, [], {})}


def _research_decision_fields(
    status: object,
    top_failure_reasons: list[dict],
    best_candidate: dict | None,
    prepare: dict,
) -> dict:
    decision = "promotable" if status == "pass" else "blocked"
    return {
        "decision": decision,
        "top_failure_reasons": top_failure_reasons,
        "diagnostics": _research_diagnostics(decision, top_failure_reasons, best_candidate, prepare),
        "recommended_actions": _research_recommended_actions(decision, top_failure_reasons, best_candidate, prepare),
    }


def _research_diagnostics(
    decision: str,
    top_failure_reasons: list[dict],
    best_candidate: dict | None,
    prepare: dict,
) -> list[dict]:
    diagnostics: list[dict] = []
    if decision == "promotable":
        runtime_interval = best_candidate.get("runtime_interval") if best_candidate else None
        diagnostics.append(
            {
                "code": "candidate_passed_all_gates",
                "severity": "info",
                "message": "A candidate passed sample, stress, and walk-forward validation.",
                "runtime_interval": runtime_interval,
            }
        )
        return diagnostics

    for item in top_failure_reasons:
        reason = str(item.get("reason") or "")
        count = int(item.get("count") or 0)
        diagnostics.append(_research_reason_diagnostic(reason, count, best_candidate, prepare))
    if not diagnostics:
        diagnostics.append(
            {
                "code": "no_passing_candidate",
                "severity": "blocker",
                "message": "No candidate passed the research gates.",
            }
        )
    return diagnostics


def _research_reason_diagnostic(reason: str, count: int, best_candidate: dict | None, prepare: dict) -> dict:
    summary = best_candidate.get("summary", {}) if isinstance(best_candidate, dict) else {}
    if reason in {
        "insufficient_validation_candles",
        "no_samples_prepared",
        "invalid_time_range",
        "insufficient_candles",
    }:
        return {
            "code": reason,
            "severity": "blocker",
            "count": count,
            "message": "The sample set is too small or has an invalid time range, so validation evidence is not usable.",
            "sample_count": int(_metric(prepare, "sample_count", 0)),
            "skipped_window_count": int(_metric(prepare, "skipped_window_count", 0)),
        }
    if reason in {"strategy_gate_insufficient_trades", "sample_validation_gate_insufficient_trades"}:
        return {
            "code": reason,
            "severity": "blocker",
            "count": count,
            "message": "The best candidate does not generate enough trades for statistical confidence.",
            "total_trade_count": int(_metric(summary, "total_trade_count", 0)),
        }
    if reason in {
        "strategy_gate_return_too_low",
        "sample_validation_gate_return_too_low",
        "return_too_low",
    }:
        return {
            "code": reason,
            "severity": "blocker",
            "count": count,
            "message": "Returns are too weak after fees and slippage.",
            "min_return_pct": _metric(summary, "min_return_pct", 0),
        }
    if reason in {
        "strategy_gate_profit_factor_too_low",
        "sample_validation_gate_profit_factor_too_low",
        "profit_factor_too_low",
    }:
        return {
            "code": reason,
            "severity": "blocker",
            "count": count,
            "message": "Profit factor is too low, so losses overwhelm wins.",
            "min_profit_factor": _metric(summary, "min_profit_factor", 0),
        }
    if "stress" in reason:
        return {
            "code": reason,
            "severity": "blocker",
            "count": count,
            "message": "The candidate fails under higher friction or adverse execution assumptions.",
            "min_stress_pass_rate": _metric(summary, "min_stress_pass_rate", 0),
        }
    if "walk_forward" in reason:
        return {
            "code": reason,
            "severity": "blocker",
            "count": count,
            "message": "The candidate is not stable across chronological segments.",
            "min_walk_forward_pass_rate": _metric(summary, "min_walk_forward_pass_rate", 0),
        }
    return {
        "code": reason or "unknown_failure",
        "severity": "blocker",
        "count": count,
        "message": "The candidate did not pass the full research gate.",
    }


def _research_recommended_actions(
    decision: str,
    top_failure_reasons: list[dict],
    best_candidate: dict | None,
    prepare: dict,
) -> list[str]:
    if decision == "promotable":
        return [
            "rerun research-strategy with --promote if this candidate is acceptable",
            "run readiness after promotion",
            "run testnet-dry-run before enabling a longer testnet loop",
        ]

    reasons = {str(item.get("reason") or "") for item in top_failure_reasons}
    actions: list[str] = ["do not promote this result"]
    if reasons & {"insufficient_validation_candles", "no_samples_prepared", "invalid_time_range", "insufficient_candles"}:
        actions.append("prepare a longer date range or reduce sample-days only after enough candles are available per window")
    if reasons & {"strategy_gate_insufficient_trades", "sample_validation_gate_insufficient_trades"}:
        actions.append("increase historical coverage, test more intervals, or include strategies that trade more frequently")
    if any("return_too_low" in reason or "profit_factor_too_low" in reason for reason in reasons):
        actions.append("broaden strategy and protective-exit grids; do not lower profitability gates to force a pass")
    if any("stress" in reason for reason in reasons):
        actions.append("prefer candidates that survive higher fee/slippage stress before testnet automation")
    if any("walk_forward" in reason for reason in reasons):
        actions.append("prefer candidates with stable results across chronological segments, not one lucky window")
    if best_candidate:
        runtime_interval = best_candidate.get("runtime_interval")
        strategy = best_candidate.get("strategy")
        if runtime_interval and strategy:
            actions.append(f"inspect the best failed candidate on {runtime_interval} / {strategy} before expanding the grid")
    return _dedupe_strings(actions)


def _research_failure_reasons(selection: dict) -> list[str]:
    reasons: list[str] = []
    reason = selection.get("reason")
    if reason and selection.get("status") != "pass":
        reasons.append(str(reason))
    for interval in selection.get("intervals") or []:
        if interval.get("status") != "pass" and interval.get("reason"):
            reasons.append(str(interval["reason"]))
        for candidate in interval.get("candidates") or []:
            reasons.extend(_candidate_failure_reasons(candidate))
    return reasons


def _candidate_failure_reasons(candidate: dict) -> list[str]:
    reasons: list[str] = []
    if candidate.get("status") != "pass" and candidate.get("reason"):
        reasons.append(str(candidate["reason"]))
    reasons.extend(_failed_gate_reasons(candidate.get("gates") or {}))
    for sample in candidate.get("samples") or []:
        if sample.get("status") not in {"pass", "prefilter_pass"} and sample.get("reason"):
            reasons.append(str(sample["reason"]))
        reasons.extend(_failed_gate_reasons(sample.get("gates") or {}))
    return reasons


def _failed_gate_reasons(gates: dict) -> list[str]:
    reasons: list[str] = []
    for gate in gates.values():
        if isinstance(gate, dict) and gate.get("allowed") is False and gate.get("reason"):
            reasons.append(str(gate["reason"]))
    return reasons


def _research_prepare_failures(prepare: dict) -> list[str]:
    reasons = [str(prepare["reason"])] if prepare.get("reason") else []
    reasons.extend(str(window["reason"]) for window in prepare.get("skipped_windows") or [] if window.get("reason"))
    return reasons


def _top_counts(values: list[str], limit: int = 5) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _compact_validation_metrics(result: dict) -> dict:
    keys = [
        "run_id",
        "candle_count",
        "trade_count",
        "return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "win_rate",
        "pass_rate",
        "min_trade_count",
        "total_trade_count",
        "worst_return_pct",
        "worst_drawdown_pct",
        "worst_profit_factor",
    ]
    return {key: result[key] for key in keys if key in result}


def _compact_sample_validation(input_file: str, result: dict) -> dict:
    compact = {
        "input_file": input_file,
        "status": result.get("status"),
        "reason": result.get("reason"),
        "candle_count": result.get("candle_count"),
        "required_candles": result.get("required_candles"),
        "gates": result.get("gates", {}),
    }
    for key in ("backtest", "stress", "walk_forward"):
        value = result.get(key)
        if isinstance(value, dict):
            compact[key] = _compact_validation_metrics(value)
    return {key: value for key, value in compact.items() if value is not None}


def _sample_validation_summary(samples: list[dict]) -> dict:
    backtests = [sample["backtest"] for sample in samples if isinstance(sample.get("backtest"), dict)]
    stresses = [sample["stress"] for sample in samples if isinstance(sample.get("stress"), dict)]
    walk_forwards = [sample["walk_forward"] for sample in samples if isinstance(sample.get("walk_forward"), dict)]
    return {
        "total_trade_count": sum(int(_metric(backtest, "trade_count", 0)) for backtest in backtests),
        "min_return_pct": min((_metric(backtest, "return_pct", 0) for backtest in backtests), default=0.0),
        "worst_drawdown_pct": max((abs(_metric(backtest, "max_drawdown_pct", 0)) for backtest in backtests), default=0.0),
        "min_profit_factor": min((_metric(backtest, "profit_factor", 0) for backtest in backtests), default=0.0),
        "min_stress_pass_rate": min((_metric(stress, "pass_rate", 0) for stress in stresses), default=0.0),
        "min_walk_forward_pass_rate": min(
            (_metric(walk_forward, "pass_rate", 0) for walk_forward in walk_forwards),
            default=0.0,
        ),
    }


def _sample_walk_forward_summary(samples: list[dict]) -> dict:
    walk_forwards = [sample["walk_forward"] for sample in samples if isinstance(sample.get("walk_forward"), dict)]
    return {
        "min_pass_rate": min((_metric(walk_forward, "pass_rate", 0) for walk_forward in walk_forwards), default=0.0),
        "min_total_trade_count": min(
            (_metric(walk_forward, "total_trade_count", 0) for walk_forward in walk_forwards),
            default=0.0,
        ),
        "min_segment_trade_count": min(
            (_metric(walk_forward, "min_segment_trade_count", 0) for walk_forward in walk_forwards),
            default=0.0,
        ),
        "worst_return_pct": min(
            (_metric(walk_forward, "worst_return_pct", 0) for walk_forward in walk_forwards),
            default=0.0,
        ),
        "worst_drawdown_pct": max(
            (abs(_metric(walk_forward, "worst_drawdown_pct", 0)) for walk_forward in walk_forwards),
            default=0.0,
        ),
        "worst_profit_factor": min(
            (_metric(walk_forward, "worst_profit_factor", 0) for walk_forward in walk_forwards),
            default=0.0,
        ),
    }


def _candidate_rank_key(candidate: dict) -> tuple:
    backtest = candidate.get("backtest") or {}
    stress = candidate.get("stress") or {}
    walk_forward = candidate.get("walk_forward") or {}
    return (
        1 if candidate.get("status") == "pass" else 0,
        _metric(walk_forward, "pass_rate", 0),
        _metric(stress, "pass_rate", 0),
        _metric(backtest, "return_pct", -1_000_000),
        -abs(_metric(backtest, "max_drawdown_pct", 1_000_000)),
        _metric(backtest, "profit_factor", 0),
    )


def _multi_sample_candidate_rank_key(candidate: dict) -> tuple:
    summary = candidate.get("summary") or {}
    return (
        1 if candidate.get("status") == "pass" else 0,
        -int(candidate.get("failed_samples", 0) or 0),
        _metric(summary, "min_walk_forward_pass_rate", 0),
        _metric(summary, "min_stress_pass_rate", 0),
        _metric(summary, "min_return_pct", -1_000_000),
        -abs(_metric(summary, "worst_drawdown_pct", 1_000_000)),
        _metric(summary, "min_profit_factor", 0),
        _metric(summary, "total_trade_count", 0),
    )


def _screen_candidate_rank_key(candidate: dict) -> tuple:
    summary = candidate.get("summary") or {}
    return (
        1 if candidate.get("status") == "prefilter_pass" else 0,
        int(candidate.get("passed_samples", 0) or 0),
        -int(candidate.get("failed_samples", 0) or 0),
        _metric(summary, "min_return_pct", -1_000_000),
        -abs(_metric(summary, "worst_drawdown_pct", 1_000_000)),
        _metric(summary, "min_profit_factor", 0),
        _metric(summary, "total_trade_count", 0),
    )


def _screen_interval_best_candidate(candidate: dict) -> dict:
    compact = {
        "status": candidate.get("status"),
        "reason": candidate.get("reason"),
        "strategy": candidate.get("strategy"),
        "parameters": candidate.get("parameters"),
        "source_interval": candidate.get("source_interval"),
        "runtime_interval": candidate.get("runtime_interval"),
        "resample_interval": candidate.get("resample_interval"),
        "sample_count": candidate.get("sample_count"),
        "passed_samples": candidate.get("passed_samples"),
        "failed_samples": candidate.get("failed_samples"),
        "summary": candidate.get("summary"),
        "failed_sample_examples": candidate.get("failed_sample_examples"),
    }
    return {key: value for key, value in compact.items() if value not in (None, [], {})}


def _failed_sample_examples(samples: list[dict], limit: int = 3) -> list[dict]:
    failed = [sample for sample in samples if sample.get("status") not in {"pass", "prefilter_pass"}]
    ranked = sorted(failed, key=_failed_sample_rank_key)
    return [_compact_failed_sample(sample) for sample in ranked[:limit]]


def _failed_sample_rank_key(sample: dict) -> tuple:
    backtest = sample.get("backtest") or {}
    return (
        _metric(backtest, "return_pct", 0),
        _metric(backtest, "profit_factor", 0),
        -abs(_metric(backtest, "max_drawdown_pct", 0)),
    )


def _compact_failed_sample(sample: dict) -> dict:
    compact = {
        "input_file": sample.get("input_file"),
        "status": sample.get("status"),
        "reason": sample.get("reason"),
        "candle_count": sample.get("candle_count"),
        "required_candles": sample.get("required_candles"),
        "backtest": sample.get("backtest"),
        "failed_gates": _failed_gate_reasons(sample.get("gates") or {}),
    }
    return {key: value for key, value in compact.items() if value not in (None, [], {})}


def _screen_interval_rank_key(result: dict) -> tuple:
    return (
        1 if result.get("status") == "pass" else 0,
        int(result.get("prefilter_pass_count", 0) or 0),
        _screen_candidate_rank_key(result.get("best_candidate") or {}),
    )


def _sample_interval_rank_key(result: dict) -> tuple:
    selected = result.get("selected") or {}
    return (
        1 if result.get("status") == "pass" else 0,
        _multi_sample_candidate_rank_key(selected),
        -int(result.get("skipped_combinations", 0) or 0),
    )


def _split_candles(candles: list[Candle], segments: int) -> list[list[Candle]]:
    if not candles:
        return []
    segments = max(1, min(segments, len(candles)))
    base_size, remainder = divmod(len(candles), segments)
    output: list[list[Candle]] = []
    offset = 0
    for index in range(segments):
        size = base_size + (1 if index < remainder else 0)
        output.append(candles[offset : offset + size])
        offset += size
    return output
